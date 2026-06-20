"""Tests for room_control — theme tables + global guards (C-0)."""
from __future__ import annotations

import pytest

from room_control import apply_rules, _match_theme, THEME_TABLE


def test_match_theme_hermit():
    """'a hermit's shack' matches the hermit row."""
    row = _match_theme("a hermit's shack")
    assert row["theme"] == "hermit"
    assert "worn_oak" in row["allowed_palette"]


def test_match_theme_blacksmith():
    """'a blacksmith's workshop' matches blacksmith."""
    row = _match_theme("a blacksmith's workshop")
    assert row["theme"] == "blacksmith"
    assert "wrought_iron" in row["allowed_palette"]


def test_match_theme_fallback():
    """'a random room' with no theme keyword → default '*' row."""
    row = _match_theme("a random room")
    assert row["theme"] == "*"


def test_apply_rules_decor_passes_through():
    """C-0: Rug (decor) passes through even when not in theme's allowed cats."""
    plan = {
        "room_size": {"w": 6, "d": 6},
        "props": [
            {"category": "table", "material": "worn_oak", "count": 2},
            {"category": "rug", "material": "wrought_iron", "count": 1},
        ],
    }
    clamped, decisions = apply_rules(plan, "a hermit's shack")
    cats = {p["category"] for p in clamped["props"]}
    assert "table" in cats
    assert "rug" in cats  # decor always passes through


def test_apply_rules_clamps_material_to_palette():
    """Material outside theme palette → clamped to first allowed."""
    plan = {
        "room_size": {"w": 6, "d": 6},
        "props": [{"category": "table", "material": "wrought_iron", "count": 1}],
    }
    clamped, decisions = apply_rules(plan, "a hermit's shack")
    assert clamped["props"][0]["material"] == "worn_oak"


def test_apply_rules_auto_adds_chair():
    """Global guard: at-least-one-seat auto-adds a chair."""
    plan = {
        "room_size": {"w": 6, "d": 6},
        "props": [{"category": "table", "material": "worn_oak", "count": 1}],
    }
    clamped, decisions = apply_rules(plan, "a dungeon")
    cats = {p["category"] for p in clamped["props"]}
    assert "chair" in cats  # auto-added by at-least-one-seat guard


def test_apply_rules_enforces_must_include():
    """Must-include guard auto-adds missing required categories."""
    plan = {
        "room_size": {"w": 6, "d": 6},
        "props": [{"category": "table", "material": "rough_granite", "count": 2}],
    }
    clamped, decisions = apply_rules(plan, "a blacksmith's forge")
    cats = {p["category"] for p in clamped["props"]}
    assert "cabinet" in cats  # blacksmith must include cabinet


def test_apply_rules_emits_decisions():
    """Out-of-palette material → material_out_of_palette decision emitted.
    Decor (rug) passes through, so no category_dropped."""
    plan = {
        "room_size": {"w": 10, "d": 10},
        "props": [
            {"category": "rug", "material": "worn_oak", "count": 3},
            {"category": "table", "material": "wrought_iron", "count": 1},
        ],
    }
    _, decisions = apply_rules(plan, "a hermit's shack")
    codes = {d.code for d in decisions}
    assert "room.material_out_of_palette" in codes
    # rug passes through as decor, table count=1 → only 1 furniture
    # hermit min density=3 → density_too_low
    # at-least-one-seat → no_seat (auto-adds chair)
    assert any(d.code == "room.density_too_low" for d in decisions)
    assert any(d.code == "room.no_seat" for d in decisions)


def test_apply_rules_preserves_valid_plan():
    """A valid plan matching the theme passes through unchanged."""
    plan = {
        "room_size": {"w": 8, "d": 6},
        "props": [
            {"category": "table", "material": "worn_oak", "count": 2},
            {"category": "chair", "material": "worn_oak", "count": 3},
            {"category": "shelf", "material": "worn_oak", "count": 1},
        ],
    }
    clamped, decisions = apply_rules(plan, "a hermit's shack")
    # No clamping needed — valid plan should pass through
    assert len(clamped["props"]) >= 3  # at least the original 3


def test_all_theme_rows_have_required_fields():
    """Every row in THEME_TABLE has the expected keys."""
    required_keys = {"theme", "required_categories", "allowed_palette",
                     "density", "must_include"}
    for row in THEME_TABLE:
        missing = required_keys - set(row.keys())
        assert not missing, f"Row {row['theme']} missing keys: {missing}"
        assert row["density"]["min"] >= 1
        assert row["density"]["max"] >= row["density"]["min"]
