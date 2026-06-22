"""TDD tests for foundry.material_resolver — deterministic material pre-pass.

This is the first real emitter of Decision Points (slice 1 of explainable
failure). It also fixes the headline bug: 'wrought-iron cabinet' must NOT
resolve to worn_oak — that's the bug we're correcting.

The pipeline never blocks; lexical material matching is a regex's task.
These tests assert (material_id, list_of_decisions) for representative
requests.
"""

from __future__ import annotations

from materials import MATERIAL_PALETTE


# ── Confident matches (specific OR single-member family) → no decision ──


def test_oak_table_resolves_to_worn_oak_no_decision():
    from material_resolver import resolve_material

    m, decisions = resolve_material("a sturdy oak dining table")
    assert m == "worn_oak"
    assert decisions == []  # confident match


def test_wrought_iron_cabinet_headline_bug():
    """The headline bug: 'wrought-iron cabinet' must be wrought_iron, not oak."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a tall wrought-iron storage cabinet")
    assert m == "wrought_iron", (
        f"expected wrought_iron, got {m!r} — the pre-pass bug regressed"
    )
    assert decisions == []


def test_granite_shelf_resolves_to_rough_granite_no_decision():
    from material_resolver import resolve_material

    m, decisions = resolve_material("a rough granite shelf")
    assert m == "rough_granite"
    assert decisions == []


def test_marble_resolves_to_rough_granite_no_decision():
    """Marble is not in the palette; the design spec maps it to rough_granite."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a polished marble table")
    assert m == "rough_granite"
    assert decisions == []


def test_iron_keyword_resolves_to_wrought_iron():
    from material_resolver import resolve_material

    m, decisions = resolve_material("an iron table")
    assert m == "wrought_iron"
    assert decisions == []


def test_steel_keyword_resolves_to_wrought_iron():
    from material_resolver import resolve_material

    m, decisions = resolve_material("a steel-framed table")
    assert m == "wrought_iron"
    assert decisions == []


def test_stone_keyword_resolves_single_member_family_no_decision():
    """Stone family has exactly one member → confident (no Decision Point)."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a small stone side table")
    assert m == "rough_granite"
    # WS-3.1: stone family now has multiple members (rough_granite, ceramic, glazed)
    assert len(decisions) >= 1
    assert any(d.code == "material.family_defaulted" for d in decisions)


def test_metal_keyword_resolves_single_member_family_no_decision():
    from material_resolver import resolve_material

    m, decisions = resolve_material("a small metal side table")
    assert m == "wrought_iron"
    # WS-3.1: metal family now has multiple members (wrought_iron, bronze)
    assert len(decisions) >= 1
    assert any(d.code == "material.family_defaulted" for d in decisions)


# ── Family with >1 member → family_defaulted decision ─────────────


def test_wooden_table_emits_family_defaulted_decision():
    """Wood family has 3 members (worn_oak, dark_walnut, weathered_pine).
    Default is worn_oak (first declared); the other two are choices.
    """
    from material_resolver import resolve_material

    m, decisions = resolve_material("a wooden table")
    assert m == "worn_oak"
    assert len(decisions) == 1
    dp = decisions[0]
    assert dp.code == "material.family_defaulted"
    assert dp.stage == "planner"
    assert dp.severity == "assumption"
    assert dp.context["family"] == "wood"
    assert dp.context["resolved"] == "worn_oak"

    # Choices cover the OTHER (non-resolved) wood members
    choice_values = {c.apply["value"] for c in dp.choices}
    assert "dark_walnut" in choice_values
    assert "weathered_pine" in choice_values
    assert "worn_oak" not in choice_values
    assert len(choice_values) == 3  # WS-3.1: dark_walnut, weathered_pine, painted_wood


def test_timber_keyword_also_emits_family_defaulted():
    from material_resolver import resolve_material

    m, decisions = resolve_material("a timber plank")
    assert m == "worn_oak"
    assert len(decisions) == 1
    assert decisions[0].code == "material.family_defaulted"


def test_family_defaulted_choice_apply_is_material_field():
    """Every choice.apply must be {"field": "material", "value": <id>}."""
    from material_resolver import resolve_material

    _, decisions = resolve_material("a wooden table")
    assert len(decisions) == 1
    for c in decisions[0].choices:
        assert c.apply.get("field") == "material"
        assert "value" in c.apply
        assert c.apply["value"] in MATERIAL_PALETTE


# ── No match → unspecified_defaulted decision ────────────────────


def test_no_material_word_emits_unspecified_defaulted():
    """A request that names no material defaults to worn_oak and offers
    ALL palette materials as choices."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a small side table")
    assert m == "worn_oak"
    assert len(decisions) == 1
    dp = decisions[0]
    assert dp.code == "material.unspecified_defaulted"
    assert dp.stage == "planner"
    assert dp.severity == "assumption"
    assert dp.context["resolved"] == "worn_oak"

    # Choices cover ALL palette materials
    choice_values = {c.apply["value"] for c in dp.choices}
    assert choice_values == set(MATERIAL_PALETTE.keys()), (
        f"unspecified_defaulted choices miss materials: "
        f"{set(MATERIAL_PALETTE.keys()) - choice_values}"
    )
    assert len(choice_values) == len(MATERIAL_PALETTE)


def test_unspecified_defaulted_messages_match_templates():
    """The plain and technical lines come from the templates registered in
    decisions.py for the unspecified code.
    """
    from material_resolver import resolve_material

    _, decisions = resolve_material("a thing")
    dp = decisions[0]
    assert dp.plain == "You didn't name a material, so I used worn_oak."
    assert dp.technical == "no material keyword matched; defaulted to worn_oak."


def test_family_defaulted_messages_match_templates():
    from material_resolver import resolve_material

    _, decisions = resolve_material("a wooden table")
    dp = decisions[0]
    assert dp.plain == (
        "You asked for wood, so I used worn_oak. You can switch to another wood."
    )
    assert dp.technical == (
        "material family=wood has multiple members; defaulted to worn_oak."
    )


# ── Determinism / data-driven ────────────────────────────────────


def test_resolver_reads_MATERIAL_PALETTE_not_hard_coded():
    """If a material is added to MATERIAL_PALETTE, the resolver picks it up
    automatically — no hard-coded list maintained in two places.
    """
    from material_resolver import _family_members

    # Each family in the palette has at least one material.
    seen_families: set[str] = set()
    for info in MATERIAL_PALETTE.values():
        seen_families.add(info["family"])
    for fam in seen_families:
        assert len(_family_members(fam)) >= 1


def test_resolver_returns_a_decision_point_type():
    """The list items must be DecisionPoint instances, not raw dicts."""
    from decisions import DecisionPoint
    from material_resolver import resolve_material

    _, decisions = resolve_material("a wooden table")
    assert len(decisions) == 1
    assert isinstance(decisions[0], DecisionPoint)


# ── material_cues (slice 2) ────────────────────────────────────────
# material_cues is the multi-match counterpart to resolve_material: it
# returns ALL matched cues as (keyword, family), single-sourced from
# _SPECIFIC_KW / _FAMILY_KW.  Same whole-word match as resolve_material.


def test_material_cues_stone_look_wooden_cabinet_spans_two_families():
    from material_resolver import material_cues

    cues = material_cues("a stone-look wooden cabinet")
    families = {fam for _, fam in cues}
    assert families == {"stone", "wood"}, (
        f"expected both stone + wood families; got families={families}, cues={cues}"
    )


def test_material_cues_oak_walnut_same_family_wood():
    """Two specific cues (oak, walnut) both map to family=wood → one family."""
    from material_resolver import material_cues

    cues = material_cues("an oak walnut table")
    families = {fam for _, fam in cues}
    assert families == {"wood"}, f"expected only wood family; got {families}"
    # And both keywords are present:
    keywords = {kw for kw, _ in cues}
    assert {"oak", "walnut"}.issubset(keywords)


def test_material_cues_wooden_table_single_family():
    """A single family keyword → only one family in cues."""
    from material_resolver import material_cues

    cues = material_cues("a wooden table")
    families = {fam for _, fam in cues}
    assert families == {"wood"}
    keywords = {kw for kw, _ in cues}
    assert "wooden" in keywords


def test_material_cues_no_match_returns_empty_list():
    """A request with no material keywords → empty cues list."""
    from material_resolver import material_cues

    cues = material_cues("a plain cabinet")
    assert cues == []


def test_material_cues_oak_keyword_resolves_to_wood_family():
    """Specific keyword 'oak' → family via MATERIAL_PALETTE, not the
    material id."""
    from material_resolver import material_cues

    cues = material_cues("an oak table")
    # 'oak' is a _SPECIFIC_KW → MATERIAL_PALETTE["worn_oak"]["family"] = "wood"
    assert ("oak", "wood") in cues


def test_material_cues_family_keyword_maps_to_its_own_family():
    """Family keyword 'stone' → family 'stone' (no MATERIAL_PALETTE roundtrip)."""
    from material_resolver import material_cues

    cues = material_cues("a stone table")
    assert ("stone", "stone") in cues


def test_material_cues_returns_list_of_tuples():
    """Return type contract: list[tuple[str, str]]."""
    from material_resolver import material_cues

    cues = material_cues("an iron table")
    assert isinstance(cues, list)
    for c in cues:
        assert isinstance(c, tuple)
        assert len(c) == 2
        assert isinstance(c[0], str)
        assert isinstance(c[1], str)


# ── material.conflict (Prompt 2) ──────────────────────────────────
# When material cues span more than one family, resolve_material emits
# a material.conflict DecisionPoint so users get recoverable choices.


def test_stone_look_wooden_cabinet_emits_material_conflict():
    """'stone-look wooden cabinet' → stone + wood families → conflict.
    'wooden' matches first (declaration order) → wood → worn_oak."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a stone-look wooden cabinet")
    assert m == "worn_oak"
    # Should have family_defaulted (wood has >1 member) AND material.conflict
    assert any(d.code == "material.family_defaulted" for d in decisions)
    assert any(d.code == "material.conflict" for d in decisions)
    conflict_dp = next(d for d in decisions if d.code == "material.conflict")
    assert conflict_dp.severity == "ambiguous"
    assert conflict_dp.stage == "planner"
    assert "stone" in conflict_dp.context["families"]
    assert "wood" in conflict_dp.context["families"]
    assert conflict_dp.context["resolved"] == "worn_oak"
    # Choices: one per competing family (stone → rough_granite)
    choice_values = {c.apply["value"] for c in conflict_dp.choices}
    assert "rough_granite" in choice_values
    assert "worn_oak" not in choice_values


def test_oak_walnut_same_family_no_conflict():
    """'oak walnut table' → both wood → no material.conflict."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("an oak walnut table")
    assert m == "worn_oak"
    assert not any(d.code == "material.conflict" for d in decisions)


def test_single_cue_no_conflict():
    """A single material keyword → no material.conflict."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a wooden table")
    assert m == "worn_oak"
    assert not any(d.code == "material.conflict" for d in decisions)


def test_oak_iron_conflict_two_specific_keywords():
    """'oak iron table' → oak (wood) + iron (metal) → conflict.
    'oak' wins (specific keyword, first in order) → worn_oak."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("an oak iron table")
    assert m == "worn_oak"
    assert any(d.code == "material.conflict" for d in decisions)
    conflict_dp = next(d for d in decisions if d.code == "material.conflict")
    choice_values = {c.apply["value"] for c in conflict_dp.choices}
    assert "wrought_iron" in choice_values


def test_specific_keyword_wins_tie_despite_conflict():
    """'granite wooden cabinet' → granite is specific (stone), wooden
    is family (wood).  Granite → rough_granite wins; conflict emitted
    with wood-family alternative."""
    from material_resolver import resolve_material

    m, decisions = resolve_material("a granite wooden cabinet")
    assert m == "rough_granite"
    assert any(d.code == "material.conflict" for d in decisions)
    conflict_dp = next(d for d in decisions if d.code == "material.conflict")
    assert conflict_dp.context["resolved"] == "rough_granite"
    choice_values = {c.apply["value"] for c in conflict_dp.choices}
    assert "worn_oak" in choice_values


def test_conflict_template_fills_correctly():
    """The material.conflict template fills both registers."""
    from material_resolver import resolve_material

    _, decisions = resolve_material("a stone wooden table")
    conflict_dp = next(d for d in decisions if d.code == "material.conflict")
    assert "stone" in conflict_dp.plain
    assert "wood" in conflict_dp.plain
    assert "worn_oak" in conflict_dp.plain
    assert "families" in conflict_dp.technical
    assert "cues" in conflict_dp.technical
