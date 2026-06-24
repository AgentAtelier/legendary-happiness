"""foundry.build_state — Brief + seed + plan persistence per build.

Writes a single re-loadable artifact, ``build_state.json``, into each build
directory. The substrate a future "adjust the scene with a follow-up prompt"
loop reloads — insurance for iterative editing (ROADMAP phase 0.10).

The artefact is JSON with sorted keys so two identical builds produce
byte-identical files (deterministic, diff-friendly).

Public API:
    save_build_state(build_dir, *, brief, seed, theme, room_size,
                     lighting_plan, palette, manifest_ref) -> Path
    load_build_state(build_dir) -> dict | None
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Single source of truth for the filename — referenced by tests and
# any future follow-up loop that finds the artefact by name.
SAVE_FILENAME = "build_state.json"


def save_build_state(
    build_dir: Path | str,
    *,
    brief: dict,
    seed: int | None,
    theme: str,
    room_size: dict,
    lighting_plan: dict,
    palette: dict,
    manifest_ref: str,
) -> Path:
    """Write ``build_state.json`` into *build_dir* and return its Path.

    Deterministic: ``json.dumps(..., sort_keys=True)`` makes the file
    byte-stable across identical builds (deep-sorts all dict keys).
    Lists preserve their input order; tuples become lists — the JSON
    contract is the canonical form.

    Args:
        build_dir: Path to the scaffolded build (e.g. ``builds/<scene>/``).
        brief: The validated Brief dict from the Interpreter.
        seed: Random seed used for the build (may be ``None``).
        theme: Theme tag (also carried in the Brief, but kept at the
            top level for cheap, intent-revealing access).
        room_size: ``{"w": ..., "d": ..., "h": ...}``.
        lighting_plan: Output of ``lighting_planner.plan_lighting()``.
        palette: Output of ``palette.build_palette()``.
        manifest_ref: Path to the manifest file, **relative to
            ``build_dir``** (e.g. ``"scenes/main_manifest.json"``).
    """
    build_dir = Path(build_dir)
    payload: dict[str, Any] = {
        "brief": brief,
        "seed": seed,
        "theme": theme,
        "room_size": room_size,
        "lighting_plan": lighting_plan,
        "palette": palette,
        "manifest_ref": manifest_ref,
    }
    out_path = build_dir / SAVE_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def load_build_state(build_dir: Path | str) -> dict | None:
    """Read ``build_state.json`` from *build_dir*.

    Returns ``None`` if the artefact does not exist. Raises
    ``json.JSONDecodeError`` if the file exists but is malformed —
    callers SHOULD surface that as a hard error, not swallow it
    (a corrupt artefact is a real bug, not a missing-file case).
    """
    path = Path(build_dir) / SAVE_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
