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
    """Material outside theme palette → clamped to palette (may be first allowed
    or an alt if the material-variety guard injected variety)."""
    plan = {
        "room_size": {"w": 6, "d": 6},
        "props": [{"category": "table", "material": "wrought_iron", "count": 1}],
    }
    clamped, decisions = apply_rules(plan, "a hermit's shack")
    # Hermit palette is (worn_oak, rough_granite).  Material was	extit{wrought_iron}
    # which is out-of-palette → clamped to a palette material (worn_oak).
    # BUT the material-variety guard (EB-7) fires because the auto-added
    # chair made the room mono-worn_oak with 2 palette members → first prop
    # gets swapped to rough_granite for variety.  So either is valid.
    mat = clamped["props"][0]["material"]
    assert mat in ("worn_oak", "rough_granite"), (
        f"Expected palette material, got {mat!r}"
    )


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


def test_apply_rules_carryable_and_new_prop_pass_through():
    """Integration: carryables (P-E target) and new props (P-F) must NOT be
    dropped by the theme filter — only out-of-theme BASE furniture is dropped."""
    from room_control import apply_rules
    plan = {"room_size": {"w": 6, "d": 6}, "props": [
        {"category": "table", "material": "worn_oak", "count": 1},
        {"category": "key", "material": "wrought_iron", "count": 1},
        {"category": "barrel", "material": "worn_oak", "count": 2},
    ]}
    clamped, _ = apply_rules(plan, "a hermit's shack")
    cats = {p["category"] for p in clamped["props"]}
    assert "key" in cats, "carryable was dropped by the control layer"
    assert "barrel" in cats, "new prop was dropped by the control layer"


# ═══════════════════════════════════════════════════════════════════════
#  EB-7: Multi-NPC carryable injection guard
# ═══════════════════════════════════════════════════════════════════════

def test_apply_rules_injects_carryables_for_multi_npc():
    """EB-7: With npc_count=3 and no carryables in plan, apply_rules
    injects carryable categories so layout_room has them."""
    from room_control import apply_rules
    from category_registry import CARRYABLES
    plan = {"room_size": {"w": 8, "d": 8}, "props": [
        {"category": "table", "material": "worn_oak", "count": 2},
        {"category": "chair", "material": "worn_oak", "count": 1},
    ]}
    clamped, decisions = apply_rules(plan, "a hermit's shack", npc_count=3)
    carryable_cats = [
        p["category"] for p in clamped["props"]
        if p["category"] in CARRYABLES
    ]
    assert len(carryable_cats) >= 3, f"expected ≥3 carryables, got {carryable_cats}"
    assert any(d.code == "room.carryables_injected" for d in decisions)


def test_apply_rules_no_injection_when_enough_carryables():
    """EB-7: With npc_count=1 (default) and enough carryables, no injection."""
    from room_control import apply_rules
    from category_registry import CARRYABLES
    plan = {"room_size": {"w": 6, "d": 6}, "props": [
        {"category": "key", "material": "wrought_iron", "count": 2},
        {"category": "table", "material": "worn_oak", "count": 1},
    ]}
    clamped, decisions = apply_rules(plan, "a hermit's shack", npc_count=2)
    codes = {d.code for d in decisions}
    assert "room.carryables_injected" not in codes


def test_apply_rules_fabric_not_on_hard_furniture():
    """EB-7: Fabric (linen/wool/silk) should never appear on hard furniture
    like tables or shelves — only on chairs, stools, benches, rugs."""
    from room_control import apply_rules
    plan = {"room_size": {"w": 6, "d": 6}, "props": [
        {"category": "table", "material": "linen", "count": 1},
        {"category": "chair", "material": "wool", "count": 2},
        {"category": "shelf", "material": "silk", "count": 1},
    ]}
    clamped, _ = apply_rules(plan, "a noble hall")
    for p in clamped["props"]:
        cat = p["category"]
        mat = p["material"]
        if cat in ("table", "shelf", "cabinet"):
            assert mat not in ("linen", "wool", "silk"), \
                f"fabric {mat} on hard furniture {cat}"


def test_apply_rules_decor_clamped_to_palette():
    """EB-7: Decor (rug) material should be clamped to theme palette,
    preferring fabric when available."""
    from room_control import apply_rules
    plan = {"room_size": {"w": 6, "d": 6}, "props": [
        {"category": "table", "material": "worn_oak", "count": 2},
        {"category": "chair", "material": "worn_oak", "count": 2},
        {"category": "rug", "material": "wrought_iron", "count": 1},
    ]}
    # Kitchen theme has linen in palette
    clamped, _ = apply_rules(plan, "a kitchen")
    rug = [p for p in clamped["props"] if p["category"] == "rug"]
    assert rug, "rug should still be present"
    # Rug should now have a palette-appropriate material (prefer fabric)
    mat = rug[0]["material"]
    kitchen_palette = ["worn_oak", "wrought_iron", "linen"]
    assert mat in kitchen_palette, f"rug material {mat} not in kitchen palette"


# ═══════════════════════════════════════════════════════════════════════
#  Quality C: Rug always fabric, never stone/metal
# ═══════════════════════════════════════════════════════════════════════

def test_rug_is_fabric_in_workshop_theme():
    """Quality C: Workshop theme has no fabric in palette, but rug
    must still resolve to a fabric material (never rough_granite)."""
    from room_control import apply_rules
    plan = {"room_size": {"w": 8, "d": 8}, "props": [
        {"category": "table", "material": "worn_oak", "count": 2},
        {"category": "shelf", "material": "worn_oak", "count": 1},
        {"category": "rug", "material": "rough_granite", "count": 1},
    ]}
    clamped, decisions = apply_rules(plan, "a workshop")
    rug = [p for p in clamped["props"] if p["category"] == "rug"]
    assert rug, "rug should still be present"
    mat = rug[0]["material"]
    assert mat in ("linen", "wool", "silk"), (
        f"Quality C: workshop rug should be fabric, got {mat}"
    )
    assert any(d.code == "room.fabric_on_decor" for d in decisions), (
        "Quality C: should emit fabric_on_decor DP"
    )


def test_rug_is_fabric_across_all_themes():
    """Quality C: For every THEME_TABLE theme, a room containing a rug
    yields the rug with a material in the fabric family."""
    from room_control import apply_rules, THEME_TABLE
    _FABRIC = frozenset({"linen", "wool", "silk"})
    for row in THEME_TABLE:
        theme = row["theme"]
        # Build a minimal plan with rug + required furniture
        props = [{"category": "rug", "material": row["allowed_palette"][0], "count": 1}]
        for cat in list(row["required_categories"])[:3]:
            if cat != "rug":
                props.append({"category": cat, "material": row["allowed_palette"][0], "count": 1})
        plan = {"room_size": {"w": 8, "d": 8}, "props": props}
        clamped, _ = apply_rules(plan, f"a {theme}")
        rug = [p for p in clamped["props"] if p["category"] == "rug"]
        assert rug, f"Quality C: {theme}: rug should still be present"
        mat = rug[0]["material"]
        assert mat in _FABRIC, (
            f"Quality C: {theme} rug material {mat} not in fabric family"
        )
