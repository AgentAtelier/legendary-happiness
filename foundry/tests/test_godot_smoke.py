"""Godot-in-the-loop smoke test (FIX-0).

Compiles a scene from a synthetic spec+manifest, runs Godot headless
with probe_smoke.gd, and asserts the scene is actually playable —
not just parseable.  Written to FAIL on current main (red test).

Assertions:
    1. MeshInstance3D_count > 0  (props rendered)
    2. A floor StaticBody3D + CollisionShape3D (BoxShape) exists
    3. Player has a CollisionShape3D (CapsuleShape)
    4. Zero "Resource file not found" / "non-existent resource" errors
       in stderr
    5. The target prop is reachable by a downward/forward raycast
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from scene_compiler import compile_scene

# ── Test data ─────────────────────────────────────────────────────────

_RPG_PROJECT_DIR = "/home/mrg/dev/games/rpg"
_GODOT_BIN = "/usr/bin/godot"

_SYNTHETIC_MANIFEST = [
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
     "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
    {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
     "wear": 0.7, "x": 2.5, "y": 0.0, "z": -1.5},
    {"id": "table_1", "category": "table", "material": "worn_oak",
     "wear": 0.2, "x": -1.0, "y": 0.0, "z": -1.0},
]

_SYNTHETIC_QUEST_SPEC = {
    "npc_role": "hermit",
    "target_entity": "shelf_0",
    "dialogue": {
        "greet": "Ah, a visitor! Welcome.",
        "ask": "Find my lost book on the shelf.",
        "wrong": "No, that is not my book.",
        "thank": "You found it! Thank you.",
    },
    "objective": {
        "type": "fetch",
        "target": "shelf_0",
        "giver": "npc",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────

def _godot_available() -> bool:
    """Return True if Godot and the rpg project are available."""
    return os.path.exists(_GODOT_BIN) and os.path.isdir(_RPG_PROJECT_DIR)


def _compile_and_probe(quest_spec, manifest, tmp_dir: str) -> dict:
    """Compile a scene, run the Godot probe, return the parsed JSON result."""
    scene_path = str(Path(tmp_dir) / "smoke_test.tscn")
    compile_scene(quest_spec, manifest, scene_path, assets_subdir="assets")

    assert Path(scene_path).exists(), f"Scene not written: {scene_path}"

    cmd = [
        _GODOT_BIN, "--headless",
        "--path", _RPG_PROJECT_DIR,
        "-s", "probe_smoke.gd",
        scene_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=60,
    )

    # Parse the JSON from stdout (last non-empty line that starts with {)
    probe_json = None
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                probe_json = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if probe_json is None:
        raise RuntimeError(
            f"No JSON output from probe. stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Attach stderr for error checking
    probe_json["_stderr"] = result.stderr
    probe_json["_returncode"] = result.returncode

    return probe_json


# ── Tests ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _godot_available(), reason="Godot not found at /usr/bin/godot or rpg project missing")
def test_mesh_count_positive():
    """FIX-0: MeshInstance3D_count > 0 (props rendered).

    EXPECTED TO FAIL on current main — no MeshInstance3D nodes because
    GLBs are instanced as Node3D with instance= on a property line, not
    in the [node] header.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(_SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td)

    checks = result.get("checks", [])
    mesh_count = result.get("mesh_count", -1)
    assert mesh_count > 0, (
        f"Expected MeshInstance3D_count > 0, got {mesh_count}\n"
        f"Checks: {checks}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )


@pytest.mark.skipif(not _godot_available(), reason="Godot not found at /usr/bin/godot or rpg project missing")
def test_floor_collision_exists():
    """FIX-0: Floor StaticBody3D + CollisionShape3D (BoxShape) exists.

    EXPECTED TO FAIL on current main — no floor node emitted.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(_SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td)

    assert result.get("floor_collision", False), (
        f"Expected floor collision shape, got floor_collision=False\n"
        f"Checks: {result.get('checks', [])}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )


@pytest.mark.skipif(not _godot_available(), reason="Godot not found at /usr/bin/godot or rpg project missing")
def test_player_collision_exists():
    """FIX-0: Player has a CollisionShape3D.

    EXPECTED TO FAIL on current main — no collision shape on Player.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(_SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td)

    assert result.get("player_collision", False), (
        f"Expected player collision shape, got player_collision=False\n"
        f"Checks: {result.get('checks', [])}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )


@pytest.mark.skipif(not _godot_available(), reason="Godot not found at /usr/bin/godot or rpg project missing")
def test_no_resource_errors_in_stderr():
    """FIX-0: Zero 'Resource file not found' / 'non-existent resource'
    errors in Godot stderr.

    EXPECTED TO FAIL on current main — humanoid_rough_granite.glb
    is not yet published, so the NPC body GLB reference will error.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(_SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td)

    stderr = result.get("_stderr", "")
    resource_errors = any(
        phrase.lower() in stderr.lower()
        for phrase in ["resource file not found", "non-existent resource"]
    )
    assert not resource_errors, (
        f"Found resource errors in Godot stderr:\n{stderr}\n"
        f"Checks: {result.get('checks', [])}"
    )


@pytest.mark.skipif(not _godot_available(), reason="Godot not found at /usr/bin/godot or rpg project missing")
def test_target_reachable_by_raycast():
    """FIX-0: The target prop is reachable by a downward/forward raycast.

    EXPECTED TO FAIL on current main — no collision shapes on props
    means raycasts pass through them.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(_SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td)

    assert result.get("target_reachable", False), (
        f"Expected target prop to be reachable by raycast\n"
        f"Checks: {result.get('checks', [])}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )
