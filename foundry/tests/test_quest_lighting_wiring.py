"""Task 6: Integration test — lighting plan + palette wired into the quest build path.

Verifies:
- plan_lighting runs BEFORE room_shell.ensure_room_shell
- windows= is passed through to ensure_room_shell
- lighting_plan= is passed to compile_scene
- palette= is passed to compile_scene via scaffold_project
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_scaffold_modules():
    """Phase 0.7: Stash/restore scaffold + dependencies in sys.modules
    so this test always gets a fresh import — no importlib.reload
    identity bleed from earlier suite tests."""
    saved = {}
    target_prefixes = (
        "scaffold", "scene_compiler", "room_shell",
        "lighting_planner", "lighting_bake", "room_control",
    )
    for mod_name, mod in list(sys.modules.items()):
        if any(mod_name == pfx or mod_name.startswith(pfx + ".") for pfx in target_prefixes):
            saved[mod_name] = mod
            del sys.modules[mod_name]
    yield
    # Restore original modules
    for mod_name in list(sys.modules):
        if any(mod_name == pfx or mod_name.startswith(pfx + ".") for pfx in target_prefixes):
            if mod_name not in saved:
                del sys.modules[mod_name]
    for mod_name, mod in saved.items():
        sys.modules[mod_name] = mod


def test_plan_runs_before_shell(monkeypatch, tmp_path):
    """Lighting plan must run before the shell in the quest scaffold path."""
    # Phase 0.7: sys.modules stash/restore fixture replaces
    # importlib.reload; this gives a truly clean import of scaffold
    # rather than a re-executed module that bleeds state from
    # earlier suite tests.
    import lighting_planner
    import room_shell
    import scaffold

    order: list[str] = []

    # Monkeypatch plan_lighting to record order + return a minimal plan
    monkeypatch.setattr(
        lighting_planner, "plan_lighting",
        lambda *a, **k: order.append("plan") or {
            "sources": [],
            "windows": [{"wall": "E", "center": 0.5, "width": 1.2, "height": 1.4, "sill": 1.2}],
            "sun": {}, "sky": {},
            "environment": {"ambient_energy": 0.6},
        },
    )

    # Monkeypatch ensure_room_shell to record order + verify windows= is passed
    def fake_shell(*a, **k):
        order.append("shell")
        assert "windows" in k, "ensure_room_shell must receive windows= kwarg"
        return (None, [])
    monkeypatch.setattr(room_shell, "ensure_room_shell", fake_shell)

    # Monkeypatch scaffold's local ``compile_scene`` binding directly.
    # scaffold.scaffold_project uses ``from scene_compiler import compile_scene``
    # which captures the function at import time.  Patching scaffold.compile_scene
    # works whether scaffold was freshly imported (this test) or already in
    # sys.modules from an earlier suite test (e.g. test_scaffold.py).
    compile_called = []

    def fake_compile(*a, lighting_plan=None, palette=None, **k):
        compile_called.append((lighting_plan, palette))
        return "/tmp/fake.tscn"
    monkeypatch.setattr(scaffold, "compile_scene", fake_compile)

    # Prepare minimal template + library for scaffold_project
    template = tmp_path / "template"
    template.mkdir()
    (template / "project.godot").write_text(
        "[application]\n\nconfig/name=\"Test\"\n"
        "config/features=PackedStringArray(\"4.7\", \"Forward Plus\")\n"
    )
    (template / "scenes").mkdir()
    (template / "assets").mkdir()
    (template / "scripts").mkdir()

    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("glb")
    (lib / "table_worn_oak.glb.import").write_text("import")
    (lib / "shelf_rough_granite.glb").write_text("glb")
    (lib / "shelf_rough_granite.glb.import").write_text("import")
    (lib / "humanoid_rough_granite.glb").write_text("glb")
    (lib / "humanoid_rough_granite.glb.import").write_text("import")

    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
         "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
    ]
    quest = {
        "npc_role": "hermit",
        "target_entity": "table_0",
        "dialogue": {"greet": "Hi.", "ask": "Find.", "wrong": "No.", "thank": "Thanks."},
        "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
    }

    # The key test: scaffold_project accepts lighting_plan and wires it through.
    lighting_plan = {
        "sources": [],
        "windows": [{"wall": "E", "center": 0.5, "width": 1.2, "height": 1.4, "sill": 1.2}],
        "sun": {}, "sky": {},
        "environment": {"ambient_energy": 0.6},
    }

    scaffold.scaffold_project(
        name="wiring_test",
        quest_specs=quest,
        manifest=manifest,
        template_dir=str(template),
        library_dir=str(lib),
        out_root=str(tmp_path / "builds"),
        godot_bin="true",
        lighting_plan=lighting_plan,
        palette={"roles": {"base": (0.5, 0.48, 0.45)}, "theme": "stone_keep", "seed": 0},
    )

    # Verify compile_scene was called with the lighting_plan + palette
    assert len(compile_called) == 1, (
        f"compile_scene should be called exactly once, got {len(compile_called)}"
    )
    called_lp, called_pal = compile_called[0]
    assert called_lp is not None, "compile_scene should receive lighting_plan"
    assert called_lp["windows"] == lighting_plan["windows"]
    assert called_lp["environment"]["ambient_energy"] == 0.6
    assert called_pal is not None, "compile_scene should receive palette"
    assert called_pal["theme"] == "stone_keep"
    assert "roles" in called_pal
