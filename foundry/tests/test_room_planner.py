"""Tests for the prompt-driven RoomPlanner (stub LLM — no llama)."""
from __future__ import annotations

import json

from room_planner import RoomPlanner


def _stub(plan: dict):
    """Return an llm-shaped callable (prompt, grammar) -> JSON text."""
    return lambda prompt, grammar=None: json.dumps(plan)


def test_valid_plan_passes_through():
    plan = {"room_size": {"w": 6.0, "d": 5.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 2},
                      {"category": "rug", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan("a hermit's shack", _stub(plan))
    assert out["room_size"] == {"w": 6.0, "d": 5.0}
    assert out["props"][0] == {"category": "table", "material": "worn_oak", "count": 2}
    assert decisions == []


def test_room_size_out_of_range_is_clamped_with_decision():
    plan = {"room_size": {"w": 99.0, "d": 1.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["room_size"] == {"w": 12.0, "d": 4.0}
    assert any(d.code == "room.size_clamped" for d in decisions)


def test_count_clamped_and_unknown_material_defaulted():
    plan = {"room_size": {"w": 5.0, "d": 5.0},
            "props": [{"category": "table", "material": "plutonium", "count": 50}]}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["props"][0]["count"] == 8
    assert out["props"][0]["material"] == "worn_oak"
    assert any(d.code == "room.prop_clamped" for d in decisions)


def test_empty_props_emits_decision():
    plan = {"room_size": {"w": 5.0, "d": 5.0}, "props": []}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["props"] == []
    assert any(d.code == "room.empty" for d in decisions)


def test_planner_accepts_new_props_and_carryables_without_remap():
    """P-E/P-F: carryables and extended props must NOT be remapped to 'table'
    by the RoomPlanner validator (they're valid grammar categories)."""
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [{"category": "crate", "material": "worn_oak", "count": 2},
                      {"category": "key", "material": "wrought_iron", "count": 1}]}
    out, decisions = RoomPlanner().plan("a storeroom", _stub(plan))
    cats = [p["category"] for p in out["props"]]
    assert "crate" in cats, "new prop was remapped"
    assert "key" in cats, "carryable was remapped"
    assert not any(d.code == "room.prop_clamped" for d in decisions)
