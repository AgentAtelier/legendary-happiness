"""Unit and integration tests for foundry.visual.screenshot (V Task 1).

Tests cover:
- _set_capture_config  — writes/updates capture config in project.godot
- _scaffold_minimal_project — creates a disposable Godot project
- _read_manifest — parses output manifest
- _ensure_capture_scene — copies capture script into build
- capture_scene / capture_prop — integration tests with stubbed Godot

Godot-dependent tests use ``godot_bin="true"`` (exits 0, no rendering)
so the scaffolding + config path is validated without a real Godot.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from visual.screenshot import (
    _ensure_capture_scene,
    _read_manifest,
    _scaffold_minimal_project,
    _set_capture_config,
    capture_prop,
    capture_scene,
)


# ── _set_capture_config ────────────────────────────────────────────

def test_set_capture_config_injects_into_fresh_project(tmp_path):
    """On a project.godot without _forge_capture, injects the setting."""
    pg = tmp_path / "project.godot"
    pg.write_text("""\
[application]

config/name="Test"

[rendering]

renderer/rendering_method="mobile"
""")
    config = {"mode": "scene", "out_dir": "/tmp/out", "angles": [0.0, 1.5]}
    _set_capture_config(str(tmp_path), config)

    text = pg.read_text()
    assert "_forge_capture=" in text
    # Verify the JSON is correctly escaped and parseable
    # Extract the value between quotes after _forge_capture=
    import re
    m = re.search(r'_forge_capture="(.*)"', text)
    assert m is not None, f"_forge_capture not found in:\n{text}"
    raw_value = m.group(1)
    # Godot unescapes \" → ", \n → newline
    unescaped = raw_value.replace('\\"', '"')
    parsed = json.loads(unescaped)
    assert parsed["mode"] == "scene"
    assert parsed["angles"] == [0.0, 1.5]
    # Original sections preserved
    assert 'config/name="Test"' in text


def test_set_capture_config_preserves_other_sections(tmp_path):
    """Existing config sections survive the injection."""
    pg = tmp_path / "project.godot"
    pg.write_text("""\
[application]

config/name="Test"
config/features=PackedStringArray("4.7")

[physics]

3d/physics_engine="Jolt Physics"
""")
    config = {"mode": "prop", "angles": [2.0]}
    _set_capture_config(str(tmp_path), config)

    text = pg.read_text()
    assert 'config/name="Test"' in text
    assert 'Jolt Physics' in text
    assert "_forge_capture=" in text


def test_set_capture_config_updates_existing(tmp_path):
    """If _forge_capture already exists, it is replaced, not duplicated."""
    pg = tmp_path / "project.godot"
    pg.write_text("""\
[application]
config/name="Test"
_forge_capture="{\\\"mode\\\": \\\"old\\\"}"
""")
    config = {"mode": "scene", "angles": [3.0]}
    _set_capture_config(str(tmp_path), config)

    text = pg.read_text()
    # Should only appear once
    assert text.count("_forge_capture=") == 1
    # Old value gone
    assert "old" not in text
    # New value present
    assert "scene" in text


def test_set_capture_config_round_trip(tmp_path):
    """Config written → read by same Python code should round-trip."""
    pg = tmp_path / "project.godot"
    pg.write_text("[application]\n\nconfig/name=\"Test\"\n")

    original = {
        "mode": "prop",
        "out_dir": "/tmp/roundtrip",
        "angles": [0.0, 2.094, 4.189],
        "radius": 2.5,
        "height": 1.2,
        "glb_path": "res://assets/prop.glb",
    }
    _set_capture_config(str(tmp_path), original)

    # Simulate what Godot does: read the value, unescape \" → "
    text = pg.read_text()
    import re
    m = re.search(r'_forge_capture="(.*)"', text)
    raw = m.group(1)
    unescaped = raw.replace('\\"', '"')
    parsed = json.loads(unescaped)

    assert parsed == original


def test_set_capture_config_escapes_quotes(tmp_path):
    """JSON string values with quotes don't break Godot config format."""
    pg = tmp_path / "project.godot"
    pg.write_text("[application]\n\nconfig/name=\"Test\"\n")

    config = {"notes": 'This has "quotes" inside', "path": "C:\\path"}
    _set_capture_config(str(tmp_path), config)

    text = pg.read_text()
    # The line should be a single _forge_capture= entry
    lines = [l for l in text.split("\n") if l.startswith("_forge_capture")]
    assert len(lines) == 1
    # The raw line should have escaped quotes
    assert '\\"' in lines[0]


# ── _scaffold_minimal_project ──────────────────────────────────────

def test_scaffold_minimal_project_creates_structure(tmp_path):
    """Creates project.godot, capture.tscn, assets/prop.glb, scripts/."""
    glb = tmp_path / "test_prop.glb"
    glb.write_text("glb-binary")

    _scaffold_minimal_project(tmp_path / "proj", str(glb))

    proj = tmp_path / "proj"
    assert (proj / "project.godot").exists()
    assert (proj / "capture.tscn").exists()
    assert (proj / "assets" / "prop.glb").exists()
    assert (proj / "scripts" / "capture_screenshot.gd").exists()


def test_scaffold_minimal_project_godot_config(tmp_path):
    """project.godot has mobile renderer and correct main_scene."""
    glb = tmp_path / "test_prop.glb"
    glb.write_text("glb")

    _scaffold_minimal_project(tmp_path / "proj", str(glb))

    pg = (tmp_path / "proj" / "project.godot").read_text()
    assert 'config/name="prop_capture"' in pg
    assert 'run/main_scene="res://capture.tscn"' in pg
    assert 'rendering_method="mobile"' in pg


def test_scaffold_minimal_project_capture_scene(tmp_path):
    """capture.tscn has correct load_steps and script reference."""
    glb = tmp_path / "test_prop.glb"
    glb.write_text("glb")

    _scaffold_minimal_project(tmp_path / "proj", str(glb))

    tscn = (tmp_path / "proj" / "capture.tscn").read_text()
    assert "load_steps=2" in tscn
    assert 'capture_screenshot.gd' in tscn
    assert 'ExtResource("1_script")' in tscn


# ── _read_manifest ─────────────────────────────────────────────────

def test_read_manifest_returns_paths(tmp_path):
    """Parses manifest JSON and returns the path list."""
    manifest = tmp_path / "capture_manifest.json"
    manifest.write_text(json.dumps({
        "paths": ["/tmp/a.png", "/tmp/b.png"],
    }))
    assert _read_manifest(tmp_path) == ["/tmp/a.png", "/tmp/b.png"]


def test_read_manifest_missing_returns_empty(tmp_path):
    """No manifest file → empty list."""
    assert _read_manifest(tmp_path) == []


def test_read_manifest_empty_paths(tmp_path):
    """Manifest with empty paths → empty list."""
    manifest = tmp_path / "capture_manifest.json"
    manifest.write_text(json.dumps({"paths": []}))
    assert _read_manifest(tmp_path) == []


# ── _ensure_capture_scene ──────────────────────────────────────────

def test_ensure_capture_scene_copies_script(tmp_path):
    """Copies the capture script into the build scripts/ dir."""
    build = tmp_path / "build"
    build.mkdir()
    dest = _ensure_capture_scene(str(build))
    assert dest
    assert (build / "scripts" / "capture_screenshot.gd").exists()


def test_ensure_capture_scene_idempotent(tmp_path):
    """Second call doesn't fail and returns same path."""
    build = tmp_path / "build"
    build.mkdir()
    first = _ensure_capture_scene(str(build))
    second = _ensure_capture_scene(str(build))
    assert first == second


# ── capture_scene (integration, Godot stubbed) ─────────────────────

def test_capture_scene_sets_up_config(tmp_path):
    """capture_scene writes capture config and runs without error (stubbed Godot)."""
    # Scaffold a minimal build directory
    build = tmp_path / "build"
    build.mkdir()
    (build / "project.godot").write_text("""\
[application]

config/name="Test"

[rendering]

renderer/rendering_method="mobile"
""")
    (build / "scenes").mkdir()
    (build / "scenes" / "main.tscn").write_text("[gd_scene]\n")
    (build / "scripts").mkdir()

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = capture_scene(
        str(build), str(out_dir),
        godot_bin="true",  # exits 0, no actual rendering
    )

    # With stubbed Godot, no manifest → empty list
    assert isinstance(result, list)

    # But config should have been written
    pg = (build / "project.godot").read_text()
    assert "_forge_capture=" in pg

    # capture script should have been copied
    assert (build / "scripts" / "capture_screenshot.gd").exists()


def test_capture_scene_returns_empty_on_stub_godot(tmp_path):
    """With godot_bin='true', no images produced → empty result, no error."""
    build = tmp_path / "build"
    build.mkdir()
    (build / "project.godot").write_text("[application]\n\nconfig/name=\"Test\"\n")
    (build / "scenes").mkdir()
    (build / "scenes" / "main.tscn").write_text("[gd_scene]\n")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Should NOT raise
    result = capture_scene(str(build), str(out_dir), godot_bin="true")
    assert result == []


# ── capture_prop (integration, Godot stubbed) ────────────────────

def test_capture_prop_sets_up_temp_project(tmp_path):
    """capture_prop creates a temp project with GLB and runs without error."""
    glb = tmp_path / "prop.glb"
    glb.write_text("fake-glb")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = capture_prop(str(glb), str(out_dir), godot_bin="true")

    # Stubbed Godot → no manifest → empty list, but no error
    assert isinstance(result, list)
    assert result == []  # no manifest written by stubbed Godot


def test_capture_prop_output_dir_created(tmp_path):
    """Output directory is created if it doesn't exist."""
    glb = tmp_path / "prop.glb"
    glb.write_text("fake-glb")

    out_dir = tmp_path / "nonexistent_out"

    capture_prop(str(glb), str(out_dir), godot_bin="true")
    assert out_dir.exists()


def test_capture_prop_custom_angles(tmp_path):
    """Custom angles are accepted."""
    glb = tmp_path / "prop.glb"
    glb.write_text("fake-glb")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Should not raise with custom angles
    result = capture_prop(
        str(glb), str(out_dir),
        angles=[0.0, 3.1416],
        godot_bin="true",
    )
    assert isinstance(result, list)


def test_capture_scene_custom_angles_radius(tmp_path):
    """Custom angles, radius, and height are accepted."""
    build = tmp_path / "build"
    build.mkdir()
    (build / "project.godot").write_text("[application]\n\nconfig/name=\"Test\"\n")
    (build / "scenes").mkdir()
    (build / "scenes" / "main.tscn").write_text("[gd_scene]\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = capture_scene(
        str(build), str(out_dir),
        angles=[0.0, 1.0, 2.0, 3.0],
        radius=10.0,
        height=5.0,
        godot_bin="true",
    )
    assert isinstance(result, list)
