"""The foundry spine: spec → compile → Blender build → gate → register.
Offline, serial, single-asset. Live-scene instancing is a later slice."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from compiler import compile_spec, load_spec
from gate import GateResult, gate_asset
from library import read_envelope, register_asset

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
    out_glb = str(Path(library_dir) / f"{spec['asset_id']}.glb")

    _build(spec_path, out_glb, blender)
    result = gate_asset(out_glb, footprint, height)

    registered = False
    if result.passed:
        register_asset(lexicon_path, spec["asset_id"], out_glb)
        registered = True

    return ForgeResult(glb_path=out_glb, gate=result, registered=registered)
