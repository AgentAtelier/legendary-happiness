"""The foundry spine: spec → compile → Blender build → gate → register.
Offline, serial, single-asset. Live-scene instancing is a later slice.

Slice 5: forge_from_request integrates the AssetPlanner LLM."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from compiler import compile_spec, load_spec
from gate import GateResult, gate_asset
from library import read_envelope, register_asset
from sidecar import build_sidecar, write_sidecar

_BUILD_SCRIPT = str(Path(__file__).resolve().parent / "blender" / "build_asset.py")


@dataclass
class ForgeResult:
    glb_path: str
    gate: GateResult
    registered: bool


def _build(spec_path: str, out_glb: str, blender: str) -> None:
    proc = subprocess.run(
        [blender, "--background", "--python", _BUILD_SCRIPT, "--", spec_path, out_glb],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not os.path.exists(out_glb):
        raise RuntimeError(f"Blender build failed:\n{proc.stderr or proc.stdout}")


def forge(spec_path: str, lexicon_path: str, library_dir: str, blender: str = "blender") -> ForgeResult:
    spec = compile_spec(load_spec(spec_path))
    footprint, height = read_envelope(lexicon_path, spec["asset_id"])

    Path(library_dir).mkdir(parents=True, exist_ok=True)
    basename = f"{spec['asset_id']}_{spec['material']}"
    out_glb = str(Path(library_dir) / f"{basename}.glb")

    _build(spec_path, out_glb, blender)
    result = gate_asset(out_glb, footprint, height)

    # Emit sidecar alongside the GLB (after build+gate, per C-07).
    sidecar = build_sidecar(spec, Path(out_glb).name)
    write_sidecar(library_dir, basename, sidecar)

    registered = False
    if result.passed:
        register_asset(lexicon_path, spec["asset_id"], out_glb)
        registered = True

    return ForgeResult(glb_path=out_glb, gate=result, registered=registered)


def forge_from_request(
    request: str,
    lexicon_path: str,
    library_dir: str,
    llm=None,
    blender: str = "blender",
) -> ForgeResult:
    """Plan → compile → build → gate → register from natural language.

    Args:
        request: Natural-language asset description (e.g. "a low wooden coffee table").
        lexicon_path: Path to the asset lexicon JSON.
        library_dir: Directory to write the built GLB into.
        llm: Callable (prompt, grammar) -> str.  Defaults to FoundryLLM().
        blender: Path to the Blender executable.
    """
    from planner import AssetPlanner

    if llm is None:
        from llm import FoundryLLM
        llm = FoundryLLM()

    planner = AssetPlanner()
    spec = planner.plan(request, llm)

    # Write the spec to a temp file so _build can read it
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(spec, f)
        spec_path = f.name

    try:
        sp = load_spec(spec_path)
        footprint, height = read_envelope(lexicon_path, sp["asset_id"])

        Path(library_dir).mkdir(parents=True, exist_ok=True)
        basename = f"{sp['asset_id']}_{sp['material']}"
        out_glb = str(Path(library_dir) / f"{basename}.glb")

        _build(spec_path, out_glb, blender)
        result = gate_asset(out_glb, footprint, height)

        # Emit sidecar alongside the GLB (after build+gate, per C-07).
        sidecar = build_sidecar(sp, Path(out_glb).name)
        write_sidecar(library_dir, basename, sidecar)

        registered = False
        if result.passed:
            register_asset(lexicon_path, sp["asset_id"], out_glb)
            registered = True

        return ForgeResult(glb_path=out_glb, gate=result, registered=registered)
    finally:
        os.unlink(spec_path)
