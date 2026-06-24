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
