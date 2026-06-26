"""Tests for C4 dialogue-validator fix (Phase 0.1).

The validator used to return True if a line contained the category word OR
any of ~28 quest verbs. So "Find my treasure" passed for category="book"
(no 'book' word, but 'find' matched) — a winnable-but-unplayable quest.

After the fix:
- `_references_quest(line, category)` returns True only if the category word
  OR a known synonym of that category is present.
- The quest-verb list becomes a soft signal tracked separately (no longer
  a standalone pass).
- `validate_dialogue` emits a Decision Point
  ``quest.dialogue_target_mismatch`` (severity="error") when the
  `ask`+`thank` cue lines don't reference the target's category, instead of
  silently passing.
"""

from __future__ import annotations

import pytest
from category_registry import REGISTRY
from dialogue_validator import (
    _CATEGORY_SYNONYMS,
    _references_quest,
    validate_dialogue,
    validate_line,
)

# ── Core fix tests (the C4 bug) ────────────────────────────────

def test_find_verb_no_category_returns_false():
    """'Find my treasure' with category='book' must NOT pass.

    'find' is in the quest-verb list, but 'book' (and no synonym of 'book')
    is in the line → validator must return False.
    """
    assert _references_quest("Find my treasure.", "book") is False, (
        "verb-only match is not enough: 'find' alone must not satisfy "
        "_references_quest when the category ('book') is missing"
    )


def test_category_word_present_returns_true():
    """'Bring me the book' with category='book' must pass."""
    assert _references_quest("Bring me the book.", "book") is True


def test_category_synonym_returns_true():
    """A known synonym of the category must pass.

    'tome', 'manuscript', 'volume' are synonyms of 'book'; 'find my old tome'
    must satisfy category='book'.
    """
    assert _references_quest("Find my old tome in the cupboard.", "book") is True


def test_unknown_category_falls_back_to_word_only():
    """For an unknown category, _references_quest falls back to the
    category word itself. No KeyError on .get(default=[])."""
    # 'xyz' is not in _CATEGORY_SYNONYMS; synonym lookup must .get() it.
    assert _references_quest("Find me the xyz here.", "xyz") is True
    # Different word still matches as category word.
    assert _references_quest("Bring me the xyz please.", "xyz") is True


# ── Soft quest-verb signal (preserves diagnostic info) ─────────

def test_quest_verb_helper_returns_true_when_verb_present():
    """The quest-verb list is preserved as a soft signal helper.

    A separate helper detects quest-verb presence so callers can still
    flag 'category referenced but no quest verb' as a soft signal.
    """
    from dialogue_validator import _has_quest_verb
    assert _has_quest_verb("Find my treasure.") is True


def test_quest_verb_helper_returns_false_when_no_verb():
    """Lines that reference the category but contain no quest verb
    still satisfy _references_quest (verb is soft, not blocking)."""
    from dialogue_validator import _has_quest_verb
    assert _has_quest_verb("Looking at the table this morning.") is True  # has 'looking'
    assert _has_quest_verb("Hmm, the book is dusty.") is False


# ── Verb-only is NOT sufficient on its own ─────────────────────

def test_validate_line_rejects_verb_only():
    """validate_line('Find my treasure.', 'book') must reject the line
    even though 'find' matches a quest verb."""
    assert validate_line("Find my treasure.", "book") is False


def test_validate_line_accepts_category_word():
    """validate_line('Bring me the book.', 'book') must accept."""
    assert validate_line("Bring me the book.", "book") is True


def test_validate_line_accepts_synonym():
    """validate_line accepts a synonym of the category."""
    assert validate_line("Bring me the old tome.", "book") is True


# ── Decision Point emission for ask+thank cue mismatches ───────

def test_validate_dialogue_emits_target_mismatch_dp_for_ask():
    """When 'ask' lacks the category word, validate_dialogue emits a
    Decision Point with code='quest.dialogue_target_mismatch' and
    severity='error' for the ask field."""
    dialogue = {
        "greet": "Welcome, traveler!",
        "ask": "Find me treasure in the hills.",  # no 'book' / no synonym
        "wrong": "That is not it.",
        "thank": "Thank you, kind soul!",
    }
    _, decisions = validate_dialogue(dialogue, category="book")
    codes = [(d.code, d.severity, d.context.get("field")) for d in decisions]
    assert ("quest.dialogue_target_mismatch", "error", "ask") in codes, (
        f"expected an error DP for 'ask' category mismatch, got {codes}"
    )


def test_validate_dialogue_emits_target_mismatch_dp_for_thank():
    """When 'thank' lacks the category word, validate_dialogue emits an
    error DP for the thank field."""
    dialogue = {
        "greet": "Ah, a visitor.",
        "ask": "Bring me the book of ages.",
        "wrong": "No, that is not it.",
        "thank": "Thank you so much!",  # no 'book' / no synonym
    }
    _, decisions = validate_dialogue(dialogue, category="book")
    codes = [(d.code, d.severity, d.context.get("field")) for d in decisions]
    assert ("quest.dialogue_target_mismatch", "error", "thank") in codes, (
        f"expected an error DP for 'thank' category mismatch, got {codes}"
    )


def test_validate_dialogue_no_target_mismatch_dp_when_valid():
    """When ask + thank correctly reference the category, no target-mismatch
    DPs are emitted (severity=error)."""
    dialogue = {
        "greet": "Ah, a visitor.",
        "ask": "Bring me the book of ages.",
        "wrong": "No, that is not it.",
        "thank": "Thank you for finding my book!",
    }
    _, decisions = validate_dialogue(dialogue, category="book")
    target_mismatch = [
        d for d in decisions
        if d.code == "quest.dialogue_target_mismatch"
    ]
    assert target_mismatch == [], (
        f"expected no target-mismatch DPs, got {[(d.severity, d.context) for d in target_mismatch]}"
    )


def test_validate_dialogue_multiple_targets_synonyms_accepted():
    """Both category word and synonym should pass for ask/thank without
    emitting any target-mismatch DP."""
    dialogue = {
        "greet": "Welcome.",
        "ask": "Bring me the shelf's volume.",
        "wrong": "That is not the right manuscript.",
        "thank": "The tome is mine at last!",
    }
    # 'book' synonyms: tome, volume, manuscript
    for category in ("book",):
        _, decisions = validate_dialogue(dialogue, category=category)
        # Some of these may contain "book" through synonyms — for 'book',
        # 'tome', 'volume', 'manuscript' are known synonyms.
        target_mismatch = [
            d for d in decisions
            if d.code == "quest.dialogue_target_mismatch"
        ]
        assert target_mismatch == [], (
            f"synonym match should satisfy ask/thank, got {[(d.severity, d.context) for d in target_mismatch]}"
        )


# ── Category coverage: every registry category works without errors ──

def _make_valid_dialogue_for(category: str) -> dict:
    """Build a dialogue that contains the category word verbatim.

    Used to assert that the validator doesn't KeyError on any registry
    entry — it produces a non-empty validated line.
    """
    return {
        "greet": "Ah, a visitor.",
        "ask": f"Bring me the {category}.",
        "wrong": f"That is not the right {category}.",
        "thank": f"Thank you for the {category}!",
    }


def _iter_registry_categories():
    """Yield every category in category_registry.REGISTRY, sorted for determinism."""
    return sorted(REGISTRY.keys())


@pytest.mark.parametrize("category", _iter_registry_categories())
def test_every_registry_category_produces_validated_line_no_keyerror(category):
    """For every category in REGISTRY, the validator can produce a
    validated line with no KeyError (synonyms lookup must default)."""
    dialogue = _make_valid_dialogue_for(category)
    validated, decisions = validate_dialogue(dialogue, category=category)
    # Every field that referenced the category-word template must validate.
    for field in ("greet", "ask", "wrong", "thank"):
        assert field in validated, f"validated dict missing {field!r} for category={category!r}"
        assert validated[field], f"validated{field!r} is empty for category={category!r}"
    # The 'ask' line templates the category word directly, so the validator
    # must recognise it as a category reference and NOT emit a target-mismatch.
    target_mismatch = [
        d for d in decisions
        if d.code == "quest.dialogue_target_mismatch"
    ]
    assert target_mismatch == [], (
        f"category={category!r} ask line should reference the category word; "
        f"got target-mismatch DPs: {[(d.context) for d in target_mismatch]}"
    )


@pytest.mark.parametrize("category", _iter_registry_categories())
def test_every_registry_category_synonyms_lookup_does_not_keyerror(category):
    """Looking up synonyms for every REGISTRY category must NOT raise KeyError."""
    # _CATEGORY_SYNONYMS.get(category.lower(), []) is the safe path.
    # If the implementation uses REGISTRY[category] instead, it'd KeyError.
    val = _CATEGORY_SYNONYMS.get(category, None)
    # Either an empty list (no synonyms registered) or a list of str
    assert val is None or isinstance(val, list), (
        f"unexpected synonyms type for {category!r}: {type(val).__name__}"
    )
    if isinstance(val, list):
        for syn in val:
            assert isinstance(syn, str), (
                f"non-string synonym for {category!r}: {syn!r}"
            )


# ── Behaviour preservation: greet/wrong still use plain validate_line

def test_validate_dialogue_greet_uses_validate_line_semantics():
    """The greet field still uses validate_line semantics (category may be
    absent from a generic nod), so a clean greet must NOT emit target-mismatch
    DPs (which are scoped to ask+thank only).

    (A greet line without the category word but matching other validate_line
    criteria is fine; a category reference is not required for greeting.)"""
    dialogue = {
        "greet": "Ah, welcome, traveler.",
        "ask": "Bring me the book.",
        "wrong": "Not it.",
        "thank": "Yours is the right book!",
    }
    _, decisions = validate_dialogue(dialogue, category="book")
    # No target_mismatch at all (greet, ask, thank all satisfy category=book
    # or fall within the validation pass rules).
    target_mismatch = [d for d in decisions if d.code == "quest.dialogue_target_mismatch"]
    assert target_mismatch == [], (
        f"legit dialogue should produce zero target-mismatch DPs, got "
        f"{[(d.severity, d.context) for d in target_mismatch]}"
    )


def test_validate_dialogue_ask_thank_with_synonyms_does_not_emit_dp():
    """ask/thank with category synonyms must satisfy validation without
    target-mismatch."""
    dialogue = {
        "greet": "Hello!",
        "ask": "Bring me the old tome from the corner.",  # tome = book synonym
        "wrong": "This is not what I wanted.",
        "thank": "Man, that volume saved me!",  # volume = book synonym too
    }
    _, decisions = validate_dialogue(dialogue, category="book")
    target_mismatch = [d for d in decisions if d.code == "quest.dialogue_target_mismatch"]
    assert target_mismatch == [], (
        f"synonyms should satisfy ask/thank, got "
        f"{[(d.severity, d.context) for d in target_mismatch]}"
    )


# ── Phase C: substance-adjective mismatch (Dual Fix B) ──────────────
# When the LLM uses a substance adjective next to the target category
# word that disagrees with the manifest material's expected adjective,
# validate_dialogue must emit ``quest.dialogue_adjective_mismatch`` at
# severity='error' and substitute the fallback line (so the player
# still sees a clue, but the orchestrator flags the leak in the build
# report).
#
# The check is scoped to ask+thank cue lines: greeter/reject lines are
# allowed to be vague.  The extraction only fires on a substance
# adjective that DIRECTLY modifies the category word, so words like
# "stone" used as gem-synonyms must NOT be flagged as substance
# mismatches.

def test_validate_dialogue_substance_mismatch_emits_dp():
    """Phase C: ask line says "wooden key" but target material is worn_oak
    (expected adjective 'oak'). Must emit quest.dialogue_adjective_mismatch
    at severity='error' AND substitute the fallback ask line."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask": "I lost my wooden key somewhere. Can you find it?",
        "wrong": "That is not my key.",
        "thank": "Yes, that's the wooden key! Thank you.",
    }
    _, decisions = validate_dialogue(dialogue, category="key", adjective="oak")
    codes = [(d.code, d.severity, d.context.get("field")) for d in decisions]
    assert ("quest.dialogue_adjective_mismatch", "error", "ask") in codes, (
        f"Phase C: expected an error DP for the 'wooden key' substance "
        f"mismatch, got {codes}"
    )
    assert ("quest.dialogue_adjective_mismatch", "error", "thank") in codes, (
        f"Phase C: expected an error DP for the 'wooden key' substance "
        f"mismatch on thank, got {codes}"
    )


def test_validate_dialogue_substance_match_emits_no_dp():
    """Phase C: ask line says 'oak key' — descriptor matches expected
    'oak' for worn_oak. Must NOT emit quest.dialogue_adjective_mismatch."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask": "Find my oak key, would you?",
        "wrong": "That is not my key.",
        "thank": "Yes, that's the oak key!",
    }
    _, decisions = validate_dialogue(dialogue, category="key", adjective="oak")
    adj_dps = [
        d for d in decisions
        if d.code == "quest.dialogue_adjective_mismatch"
    ]
    assert adj_dps == [], (
        f"matching substance adjective should NOT emit adjective_mismatch, "
        f"got {[(d.context) for d in adj_dps]}"
    )


def test_validate_dialogue_stone_as_noun_not_flagged_as_substance():
    """Phase C: gem category has 'stone' as a category synonym.
    A line that uses 'stone' as the noun ('Find the missing stone') must
    NOT be flagged as a substance mismatch — 'stone' here is the
    synonym for gem, not a material descriptor."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask": "I lost a precious stone. Find it for me?",
        "wrong": "That is not what I lost.",
        "thank": "Yes, that's the right stone!",
    }
    _, decisions = validate_dialogue(dialogue, category="gem", adjective="emerald")
    adj_dps = [
        d for d in decisions
        if d.code == "quest.dialogue_adjective_mismatch"
    ]
    assert adj_dps == [], (
        f"stone-as-gem-synonym should NOT trigger substance mismatch, "
        f"got {[(d.context) for d in adj_dps]}"
    )


def test_validate_dialogue_compound_non_whitelist_adjective_passes():
    """Phase C: 'sharp-edged dagger' has a compound adjective that is
    NOT in the substance whitelist. Must pass without emitting
    adjective_mismatch (and not be confused for 'iron')."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask": "I seek my sharp-edged dagger.",
        "wrong": "That blade is wrong.",
        "thank": "Yes, that sharp-edged dagger is mine!",
    }
    _, decisions = validate_dialogue(dialogue, category="dagger", adjective="iron")
    adj_dps = [
        d for d in decisions
        if d.code == "quest.dialogue_adjective_mismatch"
    ]
    assert adj_dps == [], (
        f"non-substance adjective should NOT trigger mismatch, "
        f"got {[(d.context) for d in adj_dps]}"
    )


def test_validate_dialogue_substance_mismatch_falls_back():
    """Phase C: when substance mismatch fires on 'ask', the validated
    ask must be the fallback template (so the player still sees a valid
    line, but the build report loudly flags the leak)."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask": "I lost my wooden key somewhere. Can you find it?",
        "wrong": "That is not my key.",
        "thank": "Yes, that is my oak key!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="key", adjective="oak",
    )
    adj_dps = [
        d for d in decisions
        if d.code == "quest.dialogue_adjective_mismatch"
    ]
    assert adj_dps, "fixture sanity: expected at least one adjective_mismatch DP"
    # The failing ask line must be replaced with the fallback template
    # (which uses adjective='oak'). The fallback does NOT contain 'wooden'.
    assert "wooden" not in validated["ask"].lower(), (
        f"fallback should drop 'wooden' for 'oak'; got {validated['ask']!r}"
    )
    assert "oak" in validated["ask"].lower() and "key" in validated["ask"].lower(), (
        f"fallback should still describe the right item, got {validated['ask']!r}"
    )


# ── Phase C hygiene nits (code-reviewer follow-ups) ───────────────
#
# Direct unit tests for the positional extract helper.  These pin the
# helper's contract independently of the validator wire-up so future
# refactors can't silently regress the false-positive guards.

def test_extract_substance_descriptor_direct_match():
    """Nit (a): bare-category match returns the whitelist word that
    directly precedes it."""
    from dialogue_validator import _extract_substance_descriptor
    # "wooden" is in the whitelist; "key" is the bare category.
    assert _extract_substance_descriptor(
        "I lost my wooden key.", "key"
    ) == "wooden"


def test_extract_substance_descriptor_via_synonym():
    """Nit (a): extract fires through a known category synonym, not just
    the bare category word.  ``gem`` ⇒ ['jewel', 'stone', 'crystal'],
    so a whitelist word before "stone" should be picked up."""
    from dialogue_validator import _extract_substance_descriptor
    assert _extract_substance_descriptor(
        "I lost my oak stone.", "gem"
    ) == "oak"


def test_extract_substance_descriptor_filters_non_whitelist_compound():
    """Nit (a): compound adjectives like "sharp-edged" or "precious"
    are NOT in the whitelist, so the helper returns "" rather than
    introducing false positives."""
    from dialogue_validator import _extract_substance_descriptor
    # "edged" not in whitelist — returns ""
    assert _extract_substance_descriptor(
        "I seek my sharp-edged dagger.", "dagger"
    ) == ""
    # "precious" not in whitelist — returns "" (and "stone" here IS
    # the category noun, not a descriptor — the positional extract
    # correctly skips it because "precious" precedes it, not a
    # whitelist word).
    assert _extract_substance_descriptor(
        "I lost a precious stone.", "gem"
    ) == ""


def test_validate_dialogue_emits_both_adjective_mismatch_and_fallback():
    """Nit (c): a single cue-line substance mismatch emits TWO DPs:
    ``quest.dialogue_adjective_mismatch`` (severity=error, the
    substance violation) and ``quest.dialogue_fallback`` (severity=info,
    the substitution event).  This cumulative signal is intentional —
    the orchestrator surfaces both in build_report so the cause
    (substance) and the response (fallback line) are visible together.
    """
    dialogue = {
        "greet": "Hello there, traveler.",
        "ask":   "I am looking for my iron table. Can you bring it to me?",
        "wrong": "That is not what I am looking for.",
        "thank": "You found the iron table! Thank you so much.",
    }
    # category="table" + material="worn_oak" → adjective="oak" (Fix A).
    # LLM emitted "iron" → mismatch.
    validated, decisions = validate_dialogue(
        dialogue, category="table", adjective="oak",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"expected adjective_mismatch DP; got codes={codes}"
    )
    assert "quest.dialogue_fallback" in codes, (
        f"expected dialogue_fallback DP (the intentional double-DP "
        f"triggered by setting is_valid=False); got codes={codes}"
    )
    # Sanity: fallback line was actually substituted into the ask field.
    assert validated["ask"] != dialogue["ask"], (
        "fallback DP fired but the ask field was NOT replaced — "
        "that's a regression in the wire-up"
    )
    assert "oak" in validated["ask"].lower(), (
        f"fallback should use the correct adjective 'oak'; "
        f"got {validated['ask']!r}"
    )
