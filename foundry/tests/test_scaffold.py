"""Unit tests for scaffold.py — disposable Godot project scaffolding.

Tests assert scaffold_project produces a correct build directory:
- project.godot with Godot 4.7 and correct main_scene
- scenes/main.tscn and scenes/main_quest_data.json exist
- Shell scripts are present
- Asset family copy covers GLBs + sidecars

These tests do NOT require Godot — they're pure Python assertions on the
file system output.  Godot-in-the-loop tests are in test_godot_smoke.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from publish import copy_asset_family
from scaffold import _find_godot, _set_main_scene, scaffold_project
from scene_compiler import resolve_unique_glbs_with_npc

# ── Test data ─────────────────────────────────────────────────────────

_MANIFEST = [
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
     "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
]

_QUEST_SPEC = {
    "npc_role": "hermit",
    "target_entity": "table_0",
    "dialogue": {
        "greet": "Hello.",
        "ask": "Find the table.",
        "wrong": "Not that.",
        "thank": "Thanks!",
    },
    "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
}


# ── resolve_unique_glbs_with_npc ──────────────────────────────────────

def test_unique_glbs_includes_npc():
    """The NPC body pair is always included even when absent from manifest."""
    glbs = resolve_unique_glbs_with_npc(_MANIFEST)
    # manifest entries
    assert ("table", "worn_oak") in glbs
    assert ("shelf", "rough_granite") in glbs
    # injected NPC
    assert ("humanoid", "rough_granite") in glbs


def test_unique_glbs_is_sorted():
    glbs = resolve_unique_glbs_with_npc(_MANIFEST)
    assert glbs == sorted(glbs)


# ── _find_godot ───────────────────────────────────────────────────────

def test_find_godot_returns_absolute_path():
    """Auto-detect returns an absolute path on a system with Godot installed."""
    # This test is skipped if Godot is not at the known path.
    from scaffold import _find_godot as find_godot
    try:
        path = find_godot()
    except FileNotFoundError:
        pytest.skip("Godot binary not found")
    assert Path(path).is_file()
    assert str(Path(path)) == str(path)  # normalized


# ── _set_main_scene ───────────────────────────────────────────────────

def test_set_main_scene_writes_config(tmp_path):
    """_set_main_scene sets run/main_scene in project.godot."""
    pg = tmp_path / "project.godot"
    # Write a minimal project.godot
    pg.write_text("""\
[application]

config/name="ForgeTemplate"
config/features=PackedStringArray("4.7", "Forward Plus")
""")
    _set_main_scene(pg, "res://scenes/main.tscn")

    text = pg.read_text()
    assert 'run/main_scene="res://scenes/main.tscn"' in text


def test_set_main_scene_preserves_existing_entries(tmp_path):
    """Existing config sections are preserved after writing."""
    pg = tmp_path / "project.godot"
    pg.write_text("""\
[application]

config/name="ForgeTemplate"
config/features=PackedStringArray("4.7", "Forward Plus")

[physics]

3d/physics_engine="Jolt Physics"
""")
    _set_main_scene(pg, "res://scenes/main.tscn")

    text = pg.read_text()
    assert 'config/name="ForgeTemplate"' in text
    assert 'physics_engine="Jolt Physics"' in text
    assert 'run/main_scene="res://scenes/main.tscn"' in text


# ── copy_asset_family ─────────────────────────────────────────────────

def test_copy_asset_family_copies_glb_and_sidecars(tmp_path):
    """Copies GLB, .glb.import, _baked_*.png, *.png.import, .sidecar.json."""
    lib = tmp_path / "library"
    lib.mkdir()
    assets = tmp_path / "assets"

    # Create a family of files for table_worn_oak
    (lib / "table_worn_oak.glb").write_text("glb")
    (lib / "table_worn_oak.glb.import").write_text("glb-import")
    (lib / "table_worn_oak_baked_wood.png").write_text("png")
    (lib / "table_worn_oak_baked_wood.png.import").write_text("png-import")
    (lib / "table_worn_oak.sidecar.json").write_text("sidecar")
    # Unrelated file — should NOT be copied
    (lib / "shelf_rough_granite.glb").write_text("unrelated")

    copied = copy_asset_family("table", "worn_oak", str(lib), str(assets))

    assert len(copied) == 5
    for fname in [
        "table_worn_oak.glb",
        "table_worn_oak.glb.import",
        "table_worn_oak_baked_wood.png",
        "table_worn_oak_baked_wood.png.import",
        "table_worn_oak.sidecar.json",
    ]:
        assert fname in copied, f"expected {fname} in copied"
        assert (assets / fname).exists(), f"{fname} not copied"

    # Unrelated file should NOT be copied
    assert not (assets / "shelf_rough_granite.glb").exists()


def test_copy_asset_family_empty_when_no_match(tmp_path):
    """Returns empty list when no files match the stem."""
    lib = tmp_path / "library"
    lib.mkdir()
    assets = tmp_path / "assets"

    copied = copy_asset_family("nonexistent", "blue", str(lib), str(assets))
    assert copied == []


# ── scaffold_project ──────────────────────────────────────────────────

def test_scaffold_project_writes_correct_structure(tmp_path):
    """scaffold_project produces a valid build directory."""
    template = tmp_path / "template"
    template.mkdir()
    # Minimal template
    (template / "project.godot").write_text("""\
[application]

config/name="ForgeTemplate"
config/features=PackedStringArray("4.7", "Forward Plus")

[physics]

3d/physics_engine="Jolt Physics"
""")
    (template / ".gitignore").write_text(".godot/\n")
    (template / "scenes").mkdir()
    (template / "assets").mkdir()
    (template / "scripts").mkdir()

    lib = tmp_path / "library"
    lib.mkdir()
    # Create asset family for table_worn_oak (NEEDED by manifest)
    (lib / "table_worn_oak.glb").write_text("glb")
    (lib / "table_worn_oak.glb.import").write_text("import")
    (lib / "table_worn_oak_baked_wood.png").write_text("png")
    # Create asset family for shelf_rough_granite (NEEDED by manifest)
    (lib / "shelf_rough_granite.glb").write_text("glb")
    (lib / "shelf_rough_granite.glb.import").write_text("import")
    # Create asset family for humanoid_rough_granite (NEEDED — NPC injected)
    (lib / "humanoid_rough_granite.glb").write_text("glb")
    (lib / "humanoid_rough_granite.glb.import").write_text("import")
    (lib / "humanoid_rough_granite_baked_wood.png").write_text("png")
    # Unrelated: should NOT be copied
    (lib / "cabinet_wrought_iron.glb").write_text("unrelated")

    # Build path under tmp_path so we don't touch real builds/
    out_root = tmp_path / "builds"

    build = scaffold_project(
        name="test_scaffold",
        quest_specs=_QUEST_SPEC,
        manifest=_MANIFEST,
        template_dir=str(template),
        library_dir=str(lib),
        out_root=str(out_root),
        godot_bin="true",  # stub — pre-import warns non-zero, doesn't fail
    )

    build_path = out_root / "test_scaffold"
    assert build_path.exists()

    # project.godot should be a copy with main_scene set
    pg = build_path / "project.godot"
    assert pg.exists()
    pg_text = pg.read_text()
    assert 'run/main_scene="res://scenes/main.tscn"' in pg_text
    assert '4.7' in pg_text

    # scenes/main.tscn should exist
    scene = build_path / "scenes" / "main.tscn"
    assert scene.exists()
    scene_text = scene.read_text()
    assert "Floor" in scene_text
    assert "Player" in scene_text

    # quest data JSON
    data = build_path / "scenes" / "main_quest_data.json"
    assert data.exists()
    qd = json.loads(data.read_text())
    assert qd["npcs"]["npc_0"]["target_entity"] == "table_0"

    # Asset families should be copied
    assert (build_path / "assets" / "table_worn_oak.glb").exists()
    assert (build_path / "assets" / "table_worn_oak.glb.import").exists()
    assert (build_path / "assets" / "shelf_rough_granite.glb").exists()
    # humanoid (NPC injection) should be copied even though not in manifest
    assert (build_path / "assets" / "humanoid_rough_granite.glb").exists()
    # Unrelated asset should NOT be copied
    assert not (build_path / "assets" / "cabinet_wrought_iron.glb").exists()


def test_scaffold_project_preserves_gitignore(tmp_path):
    """The template's .gitignore is carried into the build."""
    template = tmp_path / "template"
    template.mkdir()
    (template / "project.godot").write_text("[application]\n\nconfig/name=\"Test\"\n")
    (template / ".gitignore").write_text(".godot/\n")
    (template / "scripts").mkdir()
    (template / "scenes").mkdir()
    (template / "assets").mkdir()

    lib = tmp_path / "library"
    lib.mkdir()

    out_root = tmp_path / "builds"

    scaffold_project(
        name="test_gi",
        quest_specs=_QUEST_SPEC,
        manifest=_MANIFEST,
        template_dir=str(template),
        library_dir=str(lib),
        out_root=str(out_root),
        godot_bin="true",
    )

    build = out_root / "test_gi"
    gi = build / ".gitignore"
    assert gi.exists()
    assert ".godot/" in gi.read_text()


# ── Task 7: room-shell GLB copy + obsolete texture bake removal ────

def test_copy_room_shell_glb(tmp_path):
    """_copy_room_shell copies the shell GLB into build assets."""
    import scaffold
    src = tmp_path / "cache" / "shell.glb"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"GLB")
    dest_assets = tmp_path / "build" / "assets"
    dest_assets.mkdir(parents=True)
    scaffold._copy_room_shell(str(src), str(dest_assets))
    assert (dest_assets / "shell.glb").exists()


def test_copy_room_shell_glb_none_is_noop(tmp_path):
    """_copy_room_shell with None path is a no-op."""
    import scaffold
    dest_assets = tmp_path / "build" / "assets"
    dest_assets.mkdir(parents=True)
    scaffold._copy_room_shell(None, str(dest_assets))
    assert not (dest_assets / "shell.glb").exists()


def test_no_ensure_shell_textures_symbol():
    """The broken old _ensure_shell_textures has been removed."""
    import scaffold
    assert not hasattr(scaffold, "_ensure_shell_textures")


# ── Import-ordering fix: pass-2 must run after _copy_room_shell ────

def test_scaffold_runs_post_shell_import_pass(tmp_path, monkeypatch):
    """Showcase2 fix: scaffold_project must run a SECOND headless
    ``--import`` pass AFTER ``_copy_room_shell`` so shell.glb +
    its image refs end up with ``.godot/imported/*.ctex`` sidecars.

    Asserts:
      1. ``_copy_room_shell`` is called at least once.
      2. ``_pre_import`` is called at least twice (two passes).
      3. The last ``_copy_room_shell`` invocation precedes the last
         ``_pre_import`` invocation (second pass imports what
         just got copied).
    """
    import scaffold
    import room_shell as _room_shell
    from scene_compiler import compile_scene  # noqa: F401  (used by scaffold)
    from publish import copy_asset_family

    call_log: list[tuple[str, dict]] = []

    def fake_ensure_room_shell(w, d, wall_height, theme, seed=0, cache_root=None):
        return tmp_path / "fake" / "shell.glb"

    def fake_copy_room_shell(glb_path, dest_assets_dir):
        call_log.append(("copy_room_shell", {"path": glb_path}))

    def fake_pre_import(build_path, godot_bin, *, label="first"):
        call_log.append(("pre_import", {"label": label, "path": str(build_path)}))

    monkeypatch.setattr(_room_shell, "ensure_room_shell", fake_ensure_room_shell)
    monkeypatch.setattr(scaffold, "_copy_room_shell", fake_copy_room_shell)
    monkeypatch.setattr(scaffold, "_pre_import", fake_pre_import)

    template = tmp_path / "template"
    template.mkdir()
    (template / "project.godot").write_text(
        "[application]\n\nconfig/name=\"ForgeTemplate\"\n"
        "config/features=PackedStringArray(\"4.7\", \"Forward Plus\")\n"
    )
    (template / "scenes").mkdir()
    (template / "assets").mkdir()
    (template / "scripts").mkdir()

    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("glb")
    (lib / "table_worn_oak.glb.import").write_text("imp")
    (lib / "shelf_rough_granite.glb").write_text("glb")
    (lib / "shelf_rough_granite.glb.import").write_text("imp")
    (lib / "humanoid_rough_granite.glb").write_text("glb")
    (lib / "humanoid_rough_granite.glb.import").write_text("imp")

    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
         "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
    ]
    quest = {
        "npc_role": "hermit",
        "target_entity": "table_0",
        "dialogue": {"greet": "Hi.", "ask": "Find.", "wrong": "No.",
                     "thank": "Thanks."},
        "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
    }

    scaffold.scaffold_project(
        name="order_check",
        quest_specs=quest,
        manifest=manifest,
        template_dir=str(template),
        library_dir=str(lib),
        out_root=str(tmp_path / "builds"),
        godot_bin="true",
    )

    copy_calls = [c for c in call_log if c[0] == "copy_room_shell"]
    import_calls = [c for c in call_log if c[0] == "pre_import"]

    assert len(copy_calls) >= 1, (
        f"_copy_room_shell was never called — call log: {call_log}"
    )
    assert len(import_calls) >= 2, (
        f"Expected exactly 2 _pre_import calls (first + after-shell); "
        f"got {len(import_calls)}. call log: {call_log}"
    )

    # Two import passes with two distinct labels — protects against
    # someone deleting the second pass and bumping the first label,
    # without coupling the assertion to literal label strings.
    labels = [c[1]["label"] for c in import_calls]
    assert len(set(labels)) == 2, (
        f"_pre_import must run twice with distinct labels; got {labels}. "
        f"call log: {call_log}"
    )

    # The last copy must precede the last import.
    last_copy_idx = max(i for i, c in enumerate(call_log) if c[0] == "copy_room_shell")
    last_import_idx = max(i for i, c in enumerate(call_log) if c[0] == "pre_import")
    assert last_copy_idx < last_import_idx, (
        f"Order violation: last _copy_room_shell came AFTER last _pre_import. "
        f"call log: {call_log}"
    )
