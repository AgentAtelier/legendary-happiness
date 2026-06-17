"""Unit tests for Template Forge: template IR, slot resolution, engine.

Tests: template_from_dict, resolve_slot_values, substitute_slots,
substitute_operations, preview_template, list_templates.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ─────────────────────────────────────────────────────


def _make_template_json(slug="test_template", **overrides) -> dict:
    """Build a minimal template dict for testing."""
    data = {
        "slug": slug,
        "name": "Test Template",
        "description": "A test template.",
        "version": 1,
        "slots": [],
        "requires": [],
        "scripts": [],
        "operations": [],
        "collision_check": [],
    }
    data.update(overrides)
    return data


# ── template_from_dict ──────────────────────────────────────────


def test_template_from_dict_minimal() -> None:
    """Minimal template dict parses correctly."""
    from devforge.forge.template_ir import template_from_dict

    t = template_from_dict(_make_template_json())
    assert t.slug == "test_template"
    assert t.name == "Test Template"
    assert t.version == 1
    assert t.slots == []
    assert t.operations == []


def test_template_from_dict_with_slots() -> None:
    """Template with slots parses correctly."""
    from devforge.forge.template_ir import template_from_dict

    t = template_from_dict(
        _make_template_json(
            slots=[
                {"name": "speed", "type": "float", "default": 5.0, "description": "Walk speed"},
                {"name": "enabled", "type": "bool", "default": True, "description": "Enable system"},
            ]
        )
    )
    assert len(t.slots) == 2
    assert t.slots[0].name == "speed"
    assert t.slots[0].type == "float"
    assert t.slots[0].default == 5.0
    assert t.slots[1].type == "bool"
    assert t.slots[1].default is True


# ── resolve_slot_values ─────────────────────────────────────────


def test_resolve_defaults_when_none_provided() -> None:
    """All slots use defaults when no values provided."""
    from devforge.forge.template_ir import TemplateSlot, resolve_slot_values

    slots = [
        TemplateSlot("speed", "float", 5.0, "Walk speed"),
        TemplateSlot("label", "str", "Player", "Node name"),
    ]
    resolved = resolve_slot_values(slots, None)
    assert resolved == {"speed": 5.0, "label": "Player"}


def test_resolve_overrides_defaults() -> None:
    """Provided values override defaults."""
    from devforge.forge.template_ir import TemplateSlot, resolve_slot_values

    slots = [TemplateSlot("speed", "float", 5.0, "Walk speed")]
    resolved = resolve_slot_values(slots, {"speed": 8.0})
    assert resolved == {"speed": 8.0}


def test_resolve_rejects_unknown_slot() -> None:
    """Unknown slot name raises ValueError."""
    from devforge.forge.template_ir import TemplateSlot, resolve_slot_values

    slots = [TemplateSlot("speed", "float", 5.0, "Speed")]
    try:
        resolve_slot_values(slots, {"unknown": 1})
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "unknown" in str(e)


def test_resolve_rejects_wrong_type() -> None:
    """Wrong slot value type raises ValueError."""
    from devforge.forge.template_ir import TemplateSlot, resolve_slot_values

    slots = [TemplateSlot("speed", "float", 5.0, "Speed")]
    try:
        resolve_slot_values(slots, {"speed": "fast"})
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "speed" in str(e)


# ── substitute_slots ────────────────────────────────────────────


def test_substitute_slots_replaces_placeholders() -> None:
    """{{var}} placeholders are replaced with values."""
    from devforge.forge.template_ir import substitute_slots

    text = "speed = {{speed}}\nenabled = {{enabled}}"
    result = substitute_slots(text, {"speed": 5.0, "enabled": True})
    assert result == "speed = 5.0\nenabled = true"


def test_substitute_unknown_slot_left_as_is() -> None:
    """Unknown {{var}} is left unchanged."""
    from devforge.forge.template_ir import substitute_slots

    result = substitute_slots("Hello {{name}}", {})
    assert result == "Hello {{name}}"


# ── substitute_operations ───────────────────────────────────────


def test_substitute_operations_deep() -> None:
    """Slot values are substituted in nested operation dicts."""
    from devforge.forge.template_ir import substitute_operations

    ops = [
        {"type": "set_property", "node": "{{player_path}}", "property": "speed", "value": "{{walk_speed}}"},
    ]
    result = substitute_operations(
        ops,
        {"player_path": "/root/Main/Player", "walk_speed": 5.0},
    )
    assert result[0]["node"] == "/root/Main/Player"
    assert result[0]["value"] == "5.0"


# ── template engine: list / load ────────────────────────────────


def test_list_templates_scans_directory() -> None:
    """list_templates scans for .template.json files."""
    from devforge.forge.template_engine import list_templates

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write two template files
        t1 = _make_template_json("fps", name="FPS Controller")
        t2 = _make_template_json("save", name="Save System")
        with open(os.path.join(tmpdir, "fps.template.json"), "w") as f:
            json.dump(t1, f)
        with open(os.path.join(tmpdir, "save.template.json"), "w") as f:
            json.dump(t2, f)

        results = list_templates(directory=tmpdir)
        assert len(results) == 2
        slugs = {r["slug"] for r in results}
        assert slugs == {"fps", "save"}


def test_load_template_returns_none_for_missing() -> None:
    """load_template returns None for a non-existent slug."""
    from devforge.forge.template_engine import load_template

    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_template("nonexistent", directory=tmpdir)
        assert result is None


def test_preview_template_shows_operations() -> None:
    """preview_template resolves slots and shows ops."""
    from devforge.forge.template_engine import preview_template
    from devforge.forge.template_ir import template_from_dict

    t = template_from_dict(
        _make_template_json(
            slug="fps",
            name="FPS",
            slots=[
                {"name": "height", "type": "float", "default": 1.7, "description": "Camera height"},
            ],
            operations=[
                {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "Camera"},
                {
                    "type": "set_property",
                    "node": "/root/Main/Camera",
                    "property": "position",
                    "value": {"x": 0, "y": "{{height}}", "z": 0},
                },
            ],
        )
    )
    preview = preview_template(t, {"height": 2.0})
    assert preview["slug"] == "fps"
    assert preview["operation_count"] == 2
    assert preview["parent_path"] == "/root/Main"
    assert preview["slot_values"]["height"] == 2.0


# ── Real templates (WO-006) ─────────────────────────────────────

_template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forge", "templates")


def test_fps_controller_template_loads() -> None:
    """The real fps_controller template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return  # skip if template dir doesn't exist
    t = load_template("fps_controller", directory=_template_dir)
    assert t is not None
    assert t.slug == "fps_controller"
    assert t.name == "FPS Controller"
    assert len(t.slots) == 9  # parent + 8 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) >= 5
    assert "/root/Main/Player" in t.collision_check


def test_save_system_template_loads() -> None:
    """The real save_system template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("save_system", directory=_template_dir)
    assert t is not None
    assert t.slug == "save_system"
    assert len(t.slots) == 3
    assert len(t.scripts) == 1
    assert len(t.operations) == 2


def test_interaction_system_template_loads() -> None:
    """The real interaction_system template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("interaction_system", directory=_template_dir)
    assert t is not None
    assert t.slug == "interaction_system"
    assert len(t.slots) == 3  # parent + 2 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) >= 5


def test_list_templates_finds_all_real() -> None:
    """list_templates finds all 10 real template files."""
    from devforge.forge.template_engine import list_templates

    if not os.path.isdir(_template_dir):
        return
    results = list_templates(directory=_template_dir)
    slugs = {r["slug"] for r in results}
    expected = {
        "fps_controller",
        "save_system",
        "interaction_system",
        "inventory_system",
        "quest_system",
        "dialogue_ui",
        "day_night_cycle",
        "world_streaming_cell",
        "npc_schedule",
        "lootable_container",
    }
    assert slugs >= expected, f"Missing: {expected - slugs}"
    assert all(r["slot_count"] > 0 for r in results)


def test_fps_controller_slot_substitution() -> None:
    """FPS controller slot substitution resolves in operations."""
    from devforge.forge.template_engine import load_template
    from devforge.forge.template_ir import resolve_slot_values, substitute_operations

    if not os.path.isdir(_template_dir):
        return
    t = load_template("fps_controller", directory=_template_dir)
    assert t is not None

    slot_values = resolve_slot_values(t.slots, {"walk_speed": 7.0})
    assert slot_values["walk_speed"] == 7.0
    assert slot_values["camera_height"] == 1.7  # default

    ops = substitute_operations(t.operations, slot_values)
    # Check that the camera position has {{camera_height}} resolved.
    # substitute_slots converts all values to strings (for godot-ai transport).
    cam_op = next(o for o in ops if o.get("type") == "set_property" and "Camera3D" in o.get("node", ""))
    assert cam_op["value"]["y"] == "1.7"


def test_fps_controller_rejects_wrong_type() -> None:
    """FPS controller slot validation rejects wrong types."""
    from devforge.forge.template_engine import load_template
    from devforge.forge.template_ir import resolve_slot_values

    if not os.path.isdir(_template_dir):
        return
    t = load_template("fps_controller", directory=_template_dir)
    assert t is not None

    try:
        resolve_slot_values(t.slots, {"walk_speed": "fast"})
        assert False, "Expected ValueError for string instead of float"
    except ValueError:
        pass  # expected


# ── WO-006 expansion: 7 new templates ───────────────────────────


def test_inventory_system_template_loads() -> None:
    """The real inventory_system template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("inventory_system", directory=_template_dir)
    assert t is not None
    assert t.slug == "inventory_system"
    assert t.name == "Inventory System"
    assert len(t.slots) == 5  # parent + 4 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) == 2
    # Check slot types
    slot_names = {s.name: s.type for s in t.slots}
    assert slot_names["inventory_capacity"] == "int"
    assert slot_names["max_weight"] == "float"
    assert slot_names["enable_weight_system"] == "bool"


def test_quest_system_template_loads() -> None:
    """The real quest_system template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("quest_system", directory=_template_dir)
    assert t is not None
    assert t.slug == "quest_system"
    assert len(t.slots) == 4  # parent + 3 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) == 2
    # Script should contain quest state machine
    script = t.scripts[0].content
    assert "QuestState" in script
    assert "quest_accepted" in script
    assert "serialize" in script


def test_dialogue_ui_template_loads() -> None:
    """The real dialogue_ui template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("dialogue_ui", directory=_template_dir)
    assert t is not None
    assert t.slug == "dialogue_ui"
    assert len(t.slots) == 4  # parent + 3 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) >= 15  # complex UI tree
    script = t.scripts[0].content
    assert "typewriter" in script.lower() or "_is_typing" in script
    assert "skip_typewriter" in script
    assert "show_choices" in script


def test_day_night_cycle_template_loads() -> None:
    """The real day_night_cycle template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("day_night_cycle", directory=_template_dir)
    assert t is not None
    assert t.slug == "day_night_cycle"
    assert len(t.slots) == 7  # parent + 6 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) == 6
    script = t.scripts[0].content
    assert "time_of_day" in script
    assert "weather_changed" in script
    assert "period_changed" in script
    # Check vec3 slot
    vec3_slots = [s for s in t.slots if s.type == "vec3"]
    assert len(vec3_slots) == 2  # night_color, day_color


def test_world_streaming_cell_template_loads() -> None:
    """The real world_streaming_cell template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("world_streaming_cell", directory=_template_dir)
    assert t is not None
    assert t.slug == "world_streaming_cell"
    assert len(t.slots) == 5  # parent + 4 gameplay slots
    assert len(t.scripts) == 1
    script = t.scripts[0].content
    assert "cell_loaded" in script
    assert "cell_unloaded" in script
    assert "ResourceLoader" in script


def test_npc_schedule_template_loads() -> None:
    """The real npc_schedule template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("npc_schedule", directory=_template_dir)
    assert t is not None
    assert t.slug == "npc_schedule"
    assert len(t.slots) == 6  # parent + 5 gameplay slots
    assert len(t.scripts) == 1
    script = t.scripts[0].content
    assert "NPCState" in script
    assert "register_npc" in script
    assert "npc_state_changed" in script


def test_lootable_container_template_loads() -> None:
    """The real lootable_container template loads from disk."""
    from devforge.forge.template_engine import load_template

    if not os.path.isdir(_template_dir):
        return
    t = load_template("lootable_container", directory=_template_dir)
    assert t is not None
    assert t.slug == "lootable_container"
    assert len(t.slots) == 5  # parent + 4 gameplay slots
    assert len(t.scripts) == 1
    assert len(t.operations) >= 10  # StaticBody3D + children
    script = t.scripts[0].content
    assert "class_name LootableContainer" in script
    assert "LootTable" in script
    assert "interact" in script
    assert "add_to_group" in script


def test_all_templates_valid_json() -> None:
    """All template files parse as valid JSON."""
    import glob as glob_mod

    if not os.path.isdir(_template_dir):
        return
    for path in glob_mod.glob(os.path.join(_template_dir, "*.template.json")):
        with open(path) as f:
            data = json.load(f)
        assert "slug" in data, f"{path}: missing slug"
        assert "slots" in data, f"{path}: missing slots"
        assert "scripts" in data, f"{path}: missing scripts"
        assert "operations" in data, f"{path}: missing operations"


def test_all_templates_resolve_defaults() -> None:
    """All templates can resolve with only default slot values."""
    from devforge.forge.template_engine import load_template
    from devforge.forge.template_ir import resolve_slot_values

    if not os.path.isdir(_template_dir):
        return
    slugs = [
        "inventory_system",
        "quest_system",
        "dialogue_ui",
        "day_night_cycle",
        "world_streaming_cell",
        "npc_schedule",
        "lootable_container",
    ]
    for slug in slugs:
        t = load_template(slug, directory=_template_dir)
        assert t is not None, f"Could not load {slug}"
        resolved = resolve_slot_values(t.slots, None)
        assert len(resolved) == len(t.slots), f"{slug}: slot count mismatch"


def _overwrite_fixture():
    """Minimal template + mock executor for overwrite-protection tests."""
    from unittest.mock import MagicMock

    from devforge.execution.interface import ExecutionResult
    from devforge.forge.template_ir import Template, TemplateScript

    template = Template(
        slug="t",
        name="T",
        description="d",
        scripts=[TemplateScript(path="scripts/health.gd", content="extends Node")],
        operations=[{"type": "add_node", "parent": "Sys", "node_type": "Node", "name": "H"}],
    )
    executor = MagicMock()
    executor.execute.return_value = ExecutionResult(
        success=True,
        results=[{"success": True}],
    )
    return template, executor


def test_required_input_actions_detected() -> None:
    """Scripts using custom input actions surface them; ui_* are excluded."""
    from devforge.forge.template_engine import required_input_actions
    from devforge.forge.template_ir import Template, TemplateScript

    t = Template(
        slug="t",
        name="T",
        description="d",
        scripts=[
            TemplateScript(
                path="a.gd",
                content=(
                    'if Input.is_action_pressed("sprint"): pass\n'
                    'if Input.is_action_just_pressed("ui_accept"): pass\n'
                    'var v = Input.get_vector("move_left", "move_right", "move_forward", "move_back")\n'
                ),
            )
        ],
    )
    actions = required_input_actions(t)
    assert actions == ["move_back", "move_forward", "move_left", "move_right", "sprint"]


def test_fps_controller_surfaces_input_actions() -> None:
    """The real fps_controller template declares its custom actions."""
    from devforge.forge.template_engine import load_template, required_input_actions

    if not os.path.isdir(_template_dir):
        return
    t = load_template("fps_controller", directory=_template_dir)
    actions = required_input_actions(t)
    assert "sprint" in actions
    assert not any(a.startswith("ui_") for a in actions)


def test_apply_refuses_overwriting_existing_script() -> None:
    """An existing script file blocks execution unless overwrite_files."""
    from devforge.forge.template_engine import instantiate_template

    template, executor = _overwrite_fixture()
    result = instantiate_template(
        template,
        None,
        "/root/Main",
        executor,
        file_exists=lambda p: True,
    )
    assert result["success"] is False
    assert "overwrite" in result["errors"][0].lower()
    assert not executor.execute.called, "must refuse BEFORE executing"


def test_apply_refuses_when_existence_unverifiable() -> None:
    """If existence can't be checked, refuse rather than risk clobbering."""
    from devforge.forge.template_engine import instantiate_template

    template, executor = _overwrite_fixture()
    result = instantiate_template(
        template,
        None,
        "/root/Main",
        executor,
        file_exists=lambda p: None,
    )
    assert result["success"] is False
    assert "verify" in result["errors"][0].lower()
    assert not executor.execute.called


def test_apply_proceeds_when_files_absent() -> None:
    from devforge.forge.template_engine import instantiate_template

    template, executor = _overwrite_fixture()
    result = instantiate_template(
        template,
        None,
        "/root/Main",
        executor,
        file_exists=lambda p: False,
    )
    assert result["success"] is True
    assert executor.execute.called


def test_apply_overwrite_flag_bypasses_check() -> None:
    """overwrite_files=True is the explicit consent path."""
    from devforge.forge.template_engine import instantiate_template

    template, executor = _overwrite_fixture()
    result = instantiate_template(
        template,
        None,
        "/root/Main",
        executor,
        file_exists=lambda p: True,
        overwrite_files=True,
    )
    assert result["success"] is True
    assert executor.execute.called


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_template_from_dict_minimal,
        test_template_from_dict_with_slots,
        test_resolve_defaults_when_none_provided,
        test_resolve_overrides_defaults,
        test_resolve_rejects_unknown_slot,
        test_resolve_rejects_wrong_type,
        test_substitute_slots_replaces_placeholders,
        test_substitute_unknown_slot_left_as_is,
        test_substitute_operations_deep,
        test_list_templates_scans_directory,
        test_load_template_returns_none_for_missing,
        test_preview_template_shows_operations,
        test_fps_controller_template_loads,
        test_save_system_template_loads,
        test_interaction_system_template_loads,
        test_list_templates_finds_all_real,
        test_fps_controller_slot_substitution,
        test_fps_controller_rejects_wrong_type,
        test_inventory_system_template_loads,
        test_quest_system_template_loads,
        test_dialogue_ui_template_loads,
        test_day_night_cycle_template_loads,
        test_world_streaming_cell_template_loads,
        test_npc_schedule_template_loads,
        test_lootable_container_template_loads,
        test_all_templates_valid_json,
        test_all_templates_resolve_defaults,
        test_required_input_actions_detected,
        test_fps_controller_surfaces_input_actions,
        test_apply_refuses_overwriting_existing_script,
        test_apply_refuses_when_existence_unverifiable,
        test_apply_proceeds_when_files_absent,
        test_apply_overwrite_flag_bypasses_check,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
