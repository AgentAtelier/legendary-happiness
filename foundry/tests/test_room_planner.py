"""Tests for the Brief-driven RoomPlanner — consumes Brief, injects
mapped key_features as required props (spine slice 1 task 3).

Stub LLM — no llama dependency.
"""
from __future__ import annotations

import json

from brief import minimal
from room_planner import RoomPlanner


def _stub(plan: dict):
    """Return an llm-shaped callable (prompt, grammar) -> JSON text."""
    return lambda prompt, grammar=None, json_schema=None, **kw: json.dumps(plan)


# ── Back-compat: string input still works (wrapped in Brief.minimal) ─


def test_valid_plan_passes_through():
    """Existing test, adapted to Brief.minimal input."""
    b = minimal("a hermit's shack")
    plan_data = {"room_size": {"w": 6.0, "d": 5.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 2},
                      {"category": "rug", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))
    assert out["room_size"] == {"w": 6.0, "d": 5.0}
    assert out["props"][0] == {"category": "table", "material": "worn_oak", "count": 2}
    assert decisions == []


def test_room_size_out_of_range_is_clamped_with_decision():
    b = minimal("a room")
    plan_data = {"room_size": {"w": 99.0, "d": 1.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))
    assert out["room_size"] == {"w": 12.0, "d": 4.0}
    assert any(d.code == "room.size_clamped" for d in decisions)


def test_count_clamped_and_unknown_material_defaulted():
    b = minimal("a room")
    plan_data = {"room_size": {"w": 5.0, "d": 5.0},
            "props": [{"category": "table", "material": "plutonium", "count": 50}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))
    assert out["props"][0]["count"] == 8
    assert out["props"][0]["material"] == "worn_oak"
    assert any(d.code == "room.prop_clamped" for d in decisions)


def test_empty_props_emits_decision():
    b = minimal("a room")
    plan_data = {"room_size": {"w": 5.0, "d": 5.0}, "props": []}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))
    assert out["props"] == []
    assert any(d.code == "room.empty" for d in decisions)


def test_planner_accepts_new_props_and_carryables_without_remap():
    """P-E/P-F: carryables and extended props must NOT be remapped to 'table'
    by the RoomPlanner validator (they're valid grammar categories)."""
    b = minimal("a storeroom")
    plan_data = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [{"category": "crate", "material": "worn_oak", "count": 2},
                      {"category": "key", "material": "wrought_iron", "count": 1}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))
    cats = [p["category"] for p in out["props"]]
    assert "crate" in cats, "new prop was remapped"
    assert "key" in cats, "carryable was remapped"
    assert not any(d.code == "room.prop_clamped" for d in decisions)


def test_string_input_still_works_back_compat():
    """plan() accepts a raw string and wraps it in Brief.minimal()."""
    plan_data = {"room_size": {"w": 7.0, "d": 7.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan("a blacksmith's forge", _stub(plan_data))
    assert out["room_size"] == {"w": 7.0, "d": 7.0}
    assert out["props"][0]["category"] == "table"
    assert decisions == []


# ── Spine: key_feature injection ──────────────────────────────────


def test_mapped_key_features_are_injected_as_props():
    """A mapped key_feature → prop injected if absent + room.key_feature_injected DP."""
    # Brief with a mapped anvil (table) feature
    b = {
        "schema_version": 1,
        "source_prompt": "a blacksmith's forge with an anvil",
        "setting": "a blacksmith's forge",
        "mood": [],
        "scale": "medium",
        "theme_tag": "blacksmith",
        "key_features": [
            {"text": "anvil", "status": "mapped", "category": "table"},
        ],
        "unmapped": [],
    }
    # LLM produces a plan WITHOUT the table
    plan_data = {"room_size": {"w": 6.0, "d": 6.0},
            "props": [{"category": "chair", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))

    # The table (anvil) should be injected
    categories = [p["category"] for p in out["props"]]
    assert "table" in categories, f"table (anvil) not injected; props={out['props']}"

    # room.key_feature_injected DP should be present
    dps = [d for d in decisions if d.code == "room.key_feature_injected"]
    assert len(dps) == 1
    assert dps[0].context["text"] == "anvil"
    assert dps[0].context["category"] == "table"


def test_already_present_feature_not_re_injected():
    """If the LLM already placed the feature, no injection or DP."""
    b = {
        "schema_version": 1,
        "source_prompt": "a hermit's shack with a shelf",
        "setting": "a hermit's shack",
        "mood": [],
        "scale": "small",
        "theme_tag": "hermit",
        "key_features": [
            {"text": "bookshelf", "status": "mapped", "category": "shelf"},
        ],
        "unmapped": [],
    }
    # LLM already produces a shelf
    plan_data = {"room_size": {"w": 5.0, "d": 5.0},
            "props": [{"category": "shelf", "material": "worn_oak", "count": 2}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))

    # Only one shelf entry (no duplicate)
    shelf_props = [p for p in out["props"] if p["category"] == "shelf"]
    assert len(shelf_props) == 1

    # No injection DP
    assert not any(d.code == "room.key_feature_injected" for d in decisions)


def test_multiple_mapped_features_injected():
    """Multiple absent features → each injected with its own DP."""
    b = {
        "schema_version": 1,
        "source_prompt": "a wizard study with a shelf and a cabinet",
        "setting": "a wizard study",
        "mood": [],
        "scale": "medium",
        "theme_tag": "wizard",
        "key_features": [
            {"text": "bookshelf", "status": "mapped", "category": "shelf"},
            {"text": "potion cabinet", "status": "mapped", "category": "cabinet"},
        ],
        "unmapped": [],
    }
    # LLM produces only a table
    plan_data = {"room_size": {"w": 7.0, "d": 7.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan(b, _stub(plan_data))

    categories = [p["category"] for p in out["props"]]
    assert "shelf" in categories
    assert "cabinet" in categories

    dps = [d for d in decisions if d.code == "room.key_feature_injected"]
    assert len(dps) == 2


def test_build_prompt_includes_mapped_features():
    """build_prompt formats mapped features into the prompt text."""
    b = {
        "schema_version": 1,
        "source_prompt": "test",
        "setting": "the grand forge",
        "mood": ["hot"],
        "scale": "large",
        "theme_tag": "blacksmith",
        "key_features": [
            {"text": "anvil", "status": "mapped", "category": "table"},
            {"text": "a lava river", "status": "unmapped", "category": None},
        ],
        "unmapped": ["a lava river"],
    }
    planner = RoomPlanner()
    prompt = planner.build_prompt(b)

    assert "the grand forge" in prompt
    assert "blacksmith" in prompt
    # Only mapped features should appear in the prompt
    assert "anvil (table)" in prompt
    assert "Named features to include" in prompt
    # Unmapped features should NOT appear
    assert "a lava river" not in prompt
    # Scale band info
    assert "9" in prompt  # large = 9-12
    assert "12" in prompt


def test_build_prompt_no_features_is_safe():
    """build_prompt with no key_features produces a clean prompt."""
    b = minimal("a tavern")
    planner = RoomPlanner()
    prompt = planner.build_prompt(b)

    assert "a tavern" in prompt
    assert "tavern" in prompt
    assert "Output JSON now" in prompt
    # No features text
    assert "Named features" not in prompt
