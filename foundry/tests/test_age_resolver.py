"""TDD tests for foundry.age_resolver — deterministic age pre-pass.

Mirrors ``test_material_resolver.py``: wear-word matching is a regex's
job, not a model's.  The resolver returns ``(age_value, list_of_DecisionPoint)``
for representative requests.

Decision codes tested:
  - ``age.unspecified_defaulted`` — no wear word matched
  - ``age.conflict`` — both AGED and NEW words present
  - Confident single-class → no decision point
"""

from __future__ import annotations

# ── Confident matches (no decision point) ────────────────────────────

def test_old_chair_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an old chair")
    assert age == 0.8
    assert decisions == []


def test_aged_table_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a weathered aged table")
    assert age == 0.8
    assert decisions == []


def test_ancient_cabinet_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an ancient cabinet")
    assert age == 0.8
    assert decisions == []


def test_antique_shelf_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an antique shelf")
    assert age == 0.8
    assert decisions == []


def test_battered_table_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a battered workbench")
    assert age == 0.8
    assert decisions == []


def test_rustic_cabinet_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a rustic cabinet")
    assert age == 0.8
    assert decisions == []


def test_vintage_chair_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a vintage chair")
    assert age == 0.8
    assert decisions == []


def test_distressed_table_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a distressed table")
    assert age == 0.8
    assert decisions == []


def test_worn_shelf_resolves_to_0_8_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a worn shelf")
    assert age == 0.8
    assert decisions == []


def test_new_table_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a new table")
    assert age == 0.15
    assert decisions == []


def test_pristine_cabinet_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a pristine cabinet")
    assert age == 0.15
    assert decisions == []


def test_polished_chair_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a polished chair")
    assert age == 0.15
    assert decisions == []


def test_fresh_shelf_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a fresh shelf")
    assert age == 0.15
    assert decisions == []


def test_mint_table_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a mint condition table")
    assert age == 0.15
    assert decisions == []


def test_unused_cabinet_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an unused cabinet")
    assert age == 0.15
    assert decisions == []


def test_brand_new_hyphen_form_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a brand-new cabinet")
    assert age == 0.15
    assert decisions == []


def test_brand_new_space_form_resolves_to_0_15_no_decision():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a brand new cabinet")
    assert age == 0.15
    assert decisions == []


# ── No match → unspecified_defaulted decision ───────────────────────

def test_no_wear_word_emits_unspecified_defaulted():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a plain table")
    assert age == 0.15
    assert len(decisions) == 1
    dp = decisions[0]
    assert dp.code == "age.unspecified_defaulted"
    assert dp.stage == "planner"
    assert dp.severity == "assumption"
    assert dp.context["resolved"] == 0.15


def test_neutral_request_returns_floor_age():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a standard wooden chair")
    assert age == 0.15
    assert len(decisions) == 1
    assert decisions[0].code == "age.unspecified_defaulted"


def test_unspecified_defaulted_has_aged_alternative_choice():
    from age_resolver import resolve_age

    _, decisions = resolve_age("a table")
    assert len(decisions) == 1
    dp = decisions[0]
    assert len(dp.choices) == 1
    c = dp.choices[0]
    assert c.apply["field"] == "age"
    assert c.apply["value"] == "0.8"


# ── Conflict (both AGED and NEW) → age.conflict ────────────────────

def test_both_old_and_new_words_emit_conflict():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an old new thing")
    assert age == 0.8  # AGED wins tie
    assert len(decisions) == 1
    dp = decisions[0]
    assert dp.code == "age.conflict"
    assert dp.stage == "planner"
    assert dp.severity == "ambiguous"
    assert dp.context["resolved"] == 0.8


def test_aged_and_new_words_conflict_resolves_to_aged():
    from age_resolver import resolve_age

    age, decisions = resolve_age("a weathered pristine cabinet")
    assert age == 0.8
    assert len(decisions) == 1
    assert decisions[0].code == "age.conflict"


def test_conflict_choice_offers_new_alternative():
    from age_resolver import resolve_age

    _, decisions = resolve_age("an old brand-new chair")
    assert len(decisions) == 1
    c = decisions[0].choices[0]
    assert c.apply["field"] == "age"
    assert c.apply["value"] == "0.15"


# ── Determinism ─────────────────────────────────────────────────────

def test_same_request_same_age():
    """Determinism: same request → same age value."""
    from age_resolver import resolve_age

    age1, _ = resolve_age("an old weathered table")
    age2, _ = resolve_age("an old weathered table")
    assert age1 == age2 == 0.8


def test_same_neutral_request_same_age():
    from age_resolver import resolve_age

    age1, _ = resolve_age("a plain cabinet")
    age2, _ = resolve_age("a plain cabinet")
    assert age1 == age2 == 0.15


# ── Edge cases ──────────────────────────────────────────────────────

def test_empty_request_neutral():
    from age_resolver import resolve_age

    age, decisions = resolve_age("")
    assert age == 0.15
    assert len(decisions) == 1
    assert decisions[0].code == "age.unspecified_defaulted"


def test_case_insensitive_match():
    from age_resolver import resolve_age

    age, decisions = resolve_age("an OLD table")
    assert age == 0.8
    assert decisions == []


def test_wear_word_as_substring_does_not_match():
    """Whole-word only: 'golden' should not match 'old'."""
    from age_resolver import resolve_age

    age, decisions = resolve_age("a golden table")
    assert age == 0.15  # 'golden' is not an AGED word
    assert len(decisions) == 1
    assert decisions[0].code == "age.unspecified_defaulted"


def test_returns_decision_point_type():
    """The list items must be DecisionPoint instances, not raw dicts."""
    from age_resolver import resolve_age
    from decisions import DecisionPoint

    _, decisions = resolve_age("a table")
    assert len(decisions) == 1
    assert isinstance(decisions[0], DecisionPoint)
