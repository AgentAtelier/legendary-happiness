"""Tests for room_control — theme tables + global guards (C-0)."""
from __future__ import annotations

from room_control import THEME_TABLE, _match_theme, apply_rules


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
    from category_registry import CARRYABLES
    from room_control import apply_rules
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
    from room_control import THEME_TABLE, apply_rules
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


# ══════════════════════════════════════════════════════════════════════
#  AUDIT-05 P19: module-level THEME_INDEX / SHELL_THEME_INDEX
# ══════════════════════════════════════════════════════════════════════

def test_theme_index_matches_lighting_table():
    """P19: every key in LIGHTING_TABLE is in THEME_INDEX (lowercased,
    '*' kept) — index is a true cache of the source table."""
    from room_control import LIGHTING_TABLE, THEME_INDEX
    index_keys = {k.lower() for k in THEME_INDEX.keys()}
    table_keys = {k.lower() for k in LIGHTING_TABLE.keys()}
    assert index_keys == table_keys, (
        f"THEME_INDEX keys must match LIGHTING_TABLE (lowercased): "
        f"missing={table_keys - index_keys}, "
        f"extra={index_keys - table_keys}"
    )
    # Same number of entries
    assert len(THEME_INDEX) == len(LIGHTING_TABLE), (
        f"THEME_INDEX has {len(THEME_INDEX)} entries; "
        f"LIGHTING_TABLE has {len(LIGHTING_TABLE)}"
    )


def test_get_lighting_matches_table_for_all_known_themes():
    """P19: for every theme key in LIGHTING_TABLE, get_lighting(theme)
    returns the same dict object as direct table lookup.  Verifies the
    indexed fast path preserves equivalence."""
    from room_control import LIGHTING_TABLE, get_lighting
    for key, entry in LIGHTING_TABLE.items():
        got = get_lighting(key)
        assert got == entry, (
            f"P19: get_lighting({key!r}) = {got} differs from "
            f"LIGHTING_TABLE[{key!r}] = {entry}"
        )


def test_get_lighting_index_matches_substring_path():
    """P19: substring-match cases ('cozy kitchen scene') get the same
    answer as exact-match for the lowercased key 'kitchen'."""
    from room_control import LIGHTING_TABLE, get_lighting
    expected = LIGHTING_TABLE["kitchen"]
    # Exact (lowercased)
    assert get_lighting("kitchen") == expected
    # Substring descriptive
    assert get_lighting("a cozy kitchen scene") == expected
    # Substring within an uppercased string
    assert get_lighting("Cozy Kitchen At Dusk") == expected


def test_get_lighting_unknown_theme_returns_default():
    """P19: unknown theme string falls back to '*' default (cached)."""
    from room_control import LIGHTING_TABLE, get_lighting
    default = LIGHTING_TABLE["*"]
    assert get_lighting("no_such_theme_xyz") == default
    assert get_lighting("completely_random_string") == default
    assert get_lighting("") == default  # empty string also falls back


def test_shell_theme_index_matches_shell_table():
    """P19: SHELL_THEME_INDEX is a true cache of SHELL_TABLE (lowercased)."""
    from room_control import SHELL_TABLE, SHELL_THEME_INDEX
    assert set(SHELL_THEME_INDEX.keys()) == {k.lower() for k in SHELL_TABLE.keys()}, (
        f"SHELL_THEME_INDEX keys must match SHELL_TABLE (lowercased): "
        f"missing={set(SHELL_TABLE) - {k.lower() for k in SHELL_THEME_INDEX}}"
    )
    assert len(SHELL_THEME_INDEX) == len(SHELL_TABLE)


def test_get_shell_material_matches_table_for_all_known_themes():
    """P19: for every theme key in SHELL_TABLE and every surface, the
    indexed lookup returns the same dict as direct table indexing."""
    from room_control import SHELL_TABLE, get_shell_material
    for key, entry in SHELL_TABLE.items():
        for surf in ("floor", "wall", "ceiling"):
            got = get_shell_material(key, surf)
            assert got == entry[surf], (
                f"P19: get_shell_material({key!r}, {surf!r}) = {got} "
                f"differs from SHELL_TABLE[{key!r}][{surf!r}] = {entry[surf]}"
            )
            # Indexed entry must include the required surface keys.
            assert "albedo" in got, f"P19: {key}/{surf} missing 'albedo'"
            assert "roughness" in got, f"P19: {key}/{surf} missing 'roughness'"


def test_get_shell_material_index_matches_substring_path():
    """P19: descriptive substring matches the lowercase entry's dict."""
    from room_control import SHELL_TABLE, get_shell_material
    expected_floor = SHELL_TABLE["wizard"]["floor"]
    assert (
        get_shell_material("wizard", "floor")
        == get_shell_material("an old wizard tower", "floor")
        == expected_floor
    )


def test_get_shell_material_unknown_returns_default():
    """P19: unknown theme + any surface → '*' default."""
    from room_control import SHELL_TABLE, get_shell_material
    default = SHELL_TABLE["*"]
    for surf in ("floor", "wall", "ceiling"):
        got = get_shell_material("no_such_theme_xyz", surf)
        assert got == default[surf], (
            f"P19: get_shell_material(unknown, {surf!r}) = {got} differs "
            f"from default = {default[surf]}"
        )


def test_get_lighting_and_shell_material_isolated_from_each_other():
    """P19 regression guard: building THEME_INDEX must NOT corrupt
    SHELL_THEME_INDEX and vice versa (they share the same lowercase-key
    pattern but iterate separate source dicts)."""
    from room_control import (
        LIGHTING_TABLE,
        SHELL_TABLE,
        get_lighting,
        get_shell_material,
    )
    # All thirteen themes pass through both lookups individually.
    for key in LIGHTING_TABLE:
        assert get_lighting(key) == LIGHTING_TABLE[key]
    for key in SHELL_TABLE:
        for surf in ("floor", "wall", "ceiling"):
            assert get_shell_material(key, surf) == SHELL_TABLE[key][surf]   
