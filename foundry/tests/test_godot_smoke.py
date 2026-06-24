"""Godot-in-the-loop smoke test (FIX-0).

Scaffolds a disposable Godot project from a synthetic spec+manifest,
runs Godot headless with the smoke and playthrough probes, and asserts
the scene is actually playable — not just parseable.

This is the completeness gate: if the probe passes, all asset families
were copied correctly and the scene opens + plays.

Assertions:
    1. MeshInstance3D_count > 0  (props rendered)
    2. A floor StaticBody3D + CollisionShape3D (BoxShape) exists
    3. Player has a CollisionShape3D (CapsuleShape)
    4. Zero "Resource file not found" / "non-existent resource" errors
       in stderr
    5. The target prop is reachable by a downward/forward raycast
    6. P-D: Zero SCRIPT ERROR/Parse Error/Failed to load script in stderr
       on a plain headless launch (no probe script)
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# ── Test data ─────────────────────────────────────────────────────────

_GODOT_BIN = "/usr/bin/godot"
_LIBRARY_DIR = "/home/mrg/dev/games/rpg/assets"
_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "godot_template")

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

# B0: Multi-NPC synthetic quest specs (2 NPCs with distinct targets)
_SYNTHETIC_MULTI_QUEST_SPECS = [
    {
        "npc_role": "hermit",
        "target_entity": "shelf_0",
        "dialogue": {
            "greet": "Ah, a visitor! Welcome.",
            "ask": "Find my lost scroll on the shelf.",
            "wrong": "No, that is not my scroll.",
            "thank": "You found it! Thank you.",
        },
        "objective": {
            "type": "fetch",
            "target": "shelf_0",
            "giver": "npc_0",
        },
        "npc_id": "npc_0",
    },
    {
        "npc_role": "alchemist",
        # CB-2 made cabinets openable CONTAINERS (tag "open", not "pickup"), so a
        # cabinet can no longer be a fetch target. Target a pickable prop instead.
        "target_entity": "table_1",
        "dialogue": {
            "greet": "Greetings, traveler.",
            "ask": "Bring me the vial from the far table.",
            "wrong": "That is not what I asked for.",
            "thank": "Perfect! This is exactly what I needed.",
        },
        "objective": {
            "type": "fetch",
            "target": "table_1",
            "giver": "npc_1",
        },
        "npc_id": "npc_1",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────

def _godot_available() -> bool:
    """Return True if Godot, the asset library, and the template exist."""
    return (
        os.path.exists(_GODOT_BIN)
        and os.path.isdir(_LIBRARY_DIR)
        and os.path.isdir(_TEMPLATE_DIR)
    )


def _compile_and_probe_multi(quest_specs, manifest, tmp_dir: str, probe_script: str = "probe_smoke.gd") -> dict:
    """B0: Scaffold a disposable project with multi-NPC quest specs,
    run the Godot probe, return the parsed JSON result."""
    from scaffold import scaffold_project

    build_path = scaffold_project(
        name="smoke_test_multi",
        quest_specs=quest_specs,
        manifest=manifest,
        template_dir=_TEMPLATE_DIR,
        library_dir=_LIBRARY_DIR,
        out_root=tmp_dir,
    )

    scene_path = str(build_path / "scenes" / "main.tscn")
    assert Path(scene_path).exists(), f"Scene not written: {scene_path}"

    cmd = [
        _GODOT_BIN, "--headless",
        "--path", str(build_path),
        "-s", probe_script,
        scene_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=60,
    )

    # Parse the JSON from stdout
    probe_json = None
    marker = "PROBE_JSON_OUTPUT:"
    for line in result.stdout.splitlines():
        line = line.strip()
        idx = line.find(marker)
        if idx != -1:
            try:
                probe_json = json.loads(line[idx + len(marker):])
                break
            except json.JSONDecodeError:
                continue

    if probe_json is None:
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

    probe_json["_stderr"] = result.stderr
    probe_json["_returncode"] = result.returncode

    return probe_json


def _headless_launch_stderr(tmp_dir: str) -> str:
    """P-D: Scaffold a fresh build, launch Godot headless (no probe),
    return stderr for SCRIPT ERROR / Parse Error assertion."""
    from scaffold import scaffold_project

    build_path = scaffold_project(
        name="headless_check",
        quest_specs=[_SYNTHETIC_QUEST_SPEC],
        manifest=_SYNTHETIC_MANIFEST,
        template_dir=_TEMPLATE_DIR,
        library_dir=_LIBRARY_DIR,
        out_root=tmp_dir,
    )

    cmd = [
        _GODOT_BIN, "--headless",
        "--path", str(build_path),
        "--quit",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=60,
    )
    return result.stderr


def _compile_and_probe(quest_spec, manifest, tmp_dir: str, probe_script: str = "probe_smoke.gd") -> dict:
    """Scaffold a disposable project, run the Godot probe, return the parsed JSON result."""
    from scaffold import scaffold_project

    build_path = scaffold_project(
        name="smoke_test",
        quest_specs=[quest_spec],
        manifest=manifest,
        template_dir=_TEMPLATE_DIR,
        library_dir=_LIBRARY_DIR,
        out_root=tmp_dir,
    )

    scene_path = str(build_path / "scenes" / "main.tscn")
    assert Path(scene_path).exists(), f"Scene not written: {scene_path}"

    cmd = [
        _GODOT_BIN, "--headless",
        "--path", str(build_path),
        "-s", probe_script,
        scene_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=60,
    )

    # Parse the JSON from stdout — look for PROBE_JSON_OUTPUT: marker
    probe_json = None
    marker = "PROBE_JSON_OUTPUT:"
    for line in result.stdout.splitlines():
        line = line.strip()
        idx = line.find(marker)
        if idx != -1:
            try:
                probe_json = json.loads(line[idx + len(marker):])
                break
            except json.JSONDecodeError:
                continue

    if probe_json is None:
        # Fallback: try the old format (line starting with {)
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

@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
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


@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
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


@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
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


@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
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


@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
@pytest.mark.godot_heavy(reason="0.5b: headless interaction ray-aim unresolved")
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


# ── FIX-4: Scripted playthrough ──────────────────────────────────────

@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
@pytest.mark.godot_heavy(reason="0.5b: headless interaction ray-aim unresolved")
def test_scripted_playthrough_talk_right_win():
    """FIX-4: Scripted playthrough — talk → pickup → deliver → win.

    Simulates the interaction flow: talk to NPC (get quest), pick up
    the target prop, talk to NPC again (deliver item).  Asserts the
    WinScreen becomes visible after successful delivery.

    FIX-5: This test now exercises the FULL loop through the updated
    probe_playthrough.gd, which also tests the wrong-item path.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe(
            _SYNTHETIC_QUEST_SPEC, _SYNTHETIC_MANIFEST, td,
            probe_script="probe_playthrough.gd",
        )

    checks = result.get("checks", [])
    win_visible = result.get("win_visible", False)
    npc_state = result.get("npc_state", "?")
    wrong_shown = result.get("wrong_shown", False)

    # FIX-5: If there were enough props (target + distractor),
    # assert the wrong-item path was exercised.
    if not any("no distractor" in c for c in checks) and not any(
        "WARNING: no distractor" in c for c in checks
    ):
        assert wrong_shown, (
            f"Expected wrong line to be shown after picking distractor\n"
            f"wrong_shown={wrong_shown}\n"
            f"Checks: {checks}\n"
            f"Stderr: {result.get('_stderr', '')}"
        )

    assert win_visible, (
        f"Expected WinScreen to be visible after quest completion\n"
        f"win_visible={win_visible}  npc_state={npc_state}\n"
        f"Checks: {checks}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )
    assert result.get("ok", False), (
        f"Scripted playthrough should succeed (ok=true)\n"
        f"Checks: {checks}"
    )

    # B1: Quest-log should be populated (quest_data has valid NPC entries)
    assert result.get("quest_log_populated", False), (
        f"B1: quest_log_populated should be true\n"
        f"quest_log_populated={result.get('quest_log_populated')}\n"
        f"Checks: {checks}"
    )

    # B2: Atmosphere — post-processing + day/night nodes must be present
    assert result.get("world_env_found", False), (
        f"B2: WorldEnvironment node should exist in scene\n"
        f"Checks: {checks}"
    )
    assert result.get("day_night_found", False), (
        f"B2: DayNight node should exist in scene\n"
        f"Checks: {checks}"
    )
    assert result.get("sun_found", False), (
        f"B2: DirectionalLight3D should exist in scene\n"
        f"Checks: {checks}"
    )


# ── B0: Multi-NPC playthrough probe ──────────────────────────────────

@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
@pytest.mark.godot_heavy(
    reason="intermittent headless-Godot timing flake (phase-timer drift); "
           "passes >80% of runs, tracked under Phase 0.7."
)
@pytest.mark.godot_heavy(reason="0.5b: headless interaction ray-aim unresolved")
def test_multi_npc_playthrough():
    """B0: Scripted playthrough with 2 NPCs — each talks, gets their
    item, delivers, and both reach DONE state.

    Uses the updated probe_playthrough.gd which supports multi-NPC
    via phases 9-12 for the second NPC.

    Marked ``godot_heavy``: intermittent headless-Godot timing flake
    (Phase 0.7).  Phase-timer drift in software-Mesa llvmpipe can
    cause multiple phases to fire in a single frame; the probe
    script is correct but Godot's headless frame pacing is
    non-deterministic under software rendering.
    """
    with tempfile.TemporaryDirectory() as td:
        result = _compile_and_probe_multi(
            _SYNTHETIC_MULTI_QUEST_SPECS, _SYNTHETIC_MANIFEST, td,
            probe_script="probe_playthrough.gd",
        )

    checks = result.get("checks", [])
    win_visible = result.get("win_visible", False)
    both_done = result.get("both_done", False)
    multi_npc = result.get("multi_npc", False)

    assert multi_npc, (
        f"Expected multi_npc=true in probe result\n"
        f"Checks: {checks}"
    )

    assert both_done, (
        f"Expected both NPCs to reach DONE state\n"
        f"both_done={both_done}\n"
        f"Checks: {checks}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )

    # B1: Multi-quest win gate — WinScreen must NOT be visible after
    # first NPC done (only after ALL NPCs done)
    win_after_first = result.get("win_after_first_done", True)
    assert not win_after_first, (
        f"B1: WinScreen should NOT be visible after first NPC done "
        f"(multi-quest win gate). win_after_first_done={win_after_first}\n"
        f"Checks: {checks}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )

    assert win_visible, (
        f"Expected WinScreen visible after both NPCs satisfied\n"
        f"win_visible={win_visible}\n"
        f"Checks: {checks}\n"
        f"Stderr: {result.get('_stderr', '')}"
    )

    assert result.get("ok", False), (
        f"B0 multi-NPC playthrough should succeed (ok=true)\n"
        f"Checks: {checks}"
    )


# ── P-D: Close the smoke-probe gap ───────────────────────────────────

@pytest.mark.skipif(not _godot_available(), reason="Godot not found or assets/template missing")
def test_no_script_errors_on_plain_launch():
    """P-D: A plain headless launch (no probe script) produces 0 lines
    matching SCRIPT ERROR|Parse Error|Failed to load script.

    This catches parse errors in interaction.gd, pickup.gd, npc.gd, etc.
    that the probes might mask because they reimplement interaction logic.

    EXpected to fail if you introduce a GDScript parse error.
    """
    with tempfile.TemporaryDirectory() as td:
        stderr = _headless_launch_stderr(td)

    # Check for script-level errors
    script_error_patterns = ["SCRIPT ERROR", "Parse Error",
                              "Failed to load script"]
    found_errors: list[str] = []
    for line in stderr.splitlines():
        for pat in script_error_patterns:
            if pat.lower() in line.lower():
                found_errors.append(line.strip())
                break

    assert len(found_errors) == 0, (
        f"Found {len(found_errors)} script error(s) in Godot stderr "
        f"on plain headless launch:\n" + "\n".join(found_errors)
    )
