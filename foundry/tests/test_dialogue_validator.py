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
    _extract_substance_descriptor,
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


# ── Phase D — 'ash' whitelist removal (code-reviewer deferred nit) ─────
#
# 'ash' was originally in _SUBSTANCE_ADJECTIVES, but:
#   - there is NO 'ash' / 'ash_wood' material in the foundry materials
#     palette, so the matcher can only ever fire if the LLM
#     hallucinates 'ash' as a descriptor — the validator can never
#     *correctly* match 'ash';
#   - 'ash' doubles as a colour adjective in non-substance English
#     ('ash blonde', 'ash grey', 'ash urn' as a funerary urn for
#     ashes, 'ash figurine' as incense residue), so any line
#     containing it before a category word tends to be a false
#     positive.
# Removing 'ash' from the set closes all those vectors at zero real
# coverage loss (the matcher could never legitimately match an 'ash'
# material).

def test_extract_substance_descriptor_ash_returns_empty():
    """Phase D: 'ash' is no longer in _SUBSTANCE_ADJECTIVES, so even
    when it precedes a category synonym ('urn' for 'pot'), the
    helper returns '' instead of 'ash'."""
    from dialogue_validator import _extract_substance_descriptor
    assert _extract_substance_descriptor(
        "I seek the ash urn.", "pot"
    ) == "", (
        "Phase D regression: 'ash' is still in _SUBSTANCE_ADJECTIVES "
        "and was captured via the 'urn' synonym for 'pot'"
    )


def test_validate_dialogue_ash_descriptor_does_not_emit_mismatch():
    """Phase D: a line with 'ash urn' + category='pot' + an unrelated
    manifest adjective ('ceramic') must NOT emit a
    quest.dialogue_adjective_mismatch DP.  Without the whitelist
    removal, the helper would capture 'ash' (via 'urn' synonym) and
    mismatch it against 'ceramic'."""
    dialogue = {
        "greet": "Hello there, traveler.",
        "ask":   "Bring me the ash urn. Please.",
        "wrong": "That is not what I am looking for.",
        "thank": "You found the ash urn! Thank you.",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="pot", adjective="ceramic",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase D regression: 'ash' was treated as a substance "
        f"descriptor; got codes={codes}"
    )
    # Sanity: under Phase-D, the validator accepts the line as-is
    # (the LLM line is generic — no substance descriptor, so the
    # validator no-ops; the line still references the category via
    # 'urn' synonym so _references_quest passes).  The equality
    # check below pins the no-op contract so any future fallback
    # template that happens to contain the word "ash" can't slip
    # through as a false-positive signal; the substring check
    # stays as a redundant intent-assert so future readers
    # remember why the line passes through untouched.
    assert validated["ask"] == dialogue["ask"], (
        f"Phase D regression: validator should no-op on lines with no "
        f"substance descriptor (line preserved unchanged); got "
        f"{validated['ask']!r} vs original {dialogue['ask']!r}"
    )
    assert "ash" in validated["ask"].lower()  # intent assertion


# ── Phase E — gold/silver containers (a) + parchment double-duty (b) ──────
#
# Two adjacent false-positive vectors surfaced after Phase D:
#   (a) "Find my gold pouch" / "Bring me the silver chest" — the
#       descriptor may name the *contents* (gold coins inside a
#       leather pouch) OR the *container's actual material* (an
#       ornate gold-adorned treasure chest).  Phase A1 mitigation:
#       per-category contents-allowlist.  A descriptor that's in the
#       contents-allowlist for the category is treated as
#       possibly-canonical-contents, NOT compared against the
#       manifest's material adjective.
#   (b) "parchment" is BOTH a scroll-category synonym AND a
#       _SUBSTANCE_ADJECTIVES entry.  Phase B1 mitigation: skip the
#       match entirely when the captured descriptor word IS a known
#       synonym of the category (synonym-role).  Combined with A1
#       (some categories like 'desk' / 'book' / 'table' have
#       parchment in their contents-allowlist), this protects common
#       doc-on-surface shapes from false-positive mismatch DPs.

def test_extract_substance_descriptor_gold_pouch_exempted():
    """Phase E (a): 'gold coin-pouch' returns '' post-mitigation.
    Pre-mitigation the helper captured 'gold' as a descriptor and
    fires a mismatch DP against a leather coin-pouch.  After A1
    exemption, 'gold' is in _CONTENTS_EXEMPTIONS['coin-pouch'] and
    is skipped."""
    from dialogue_validator import _extract_substance_descriptor
    assert _extract_substance_descriptor(
        "Find my gold coin-pouch.", "coin-pouch"
    ) == "", (
        "Phase E regression: 'gold' was treated as a substance "
        "descriptor on a coin-pouch; 'gold' should be in "
        "_CONTENTS_EXEMPTIONS['coin-pouch']"
    )


def test_extract_substance_descriptor_silver_chest_exempted():
    """Phase E (a): 'silver chest' returns '' post-mitigation."""
    from dialogue_validator import _extract_substance_descriptor
    assert _extract_substance_descriptor(
        "Bring me the silver chest.", "chest"
    ) == "", (
        "Phase E regression: 'silver' was treated as a substance "
        "descriptor on a chest; 'silver' should be in "
        "_CONTENTS_EXEMPTIONS['chest']"
    )


def test_validate_dialogue_parchment_scroll_synonym_bypass():
    """Phase E (b): B1 — 'parchment' IS a synonym of 'scroll', so
    when it precedes the bare category 'scroll' the helper returns
    '' instead of treating 'parchment' as a substance descriptor
    (which would mismatch against the typical 'paper' material)."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Read the old parchment scroll.",
        "wrong": "That is not the right scroll.",
        "thank": "Yes, the parchment scroll is mine!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="scroll", adjective="paper",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase E regression: parchment is a scroll-synonym but was "
        f"treated as a substance descriptor; got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"Phase E regression: parchment-as-synonym should leave the "
        f"line preserved unchanged; got {validated['ask']!r} vs "
        f"{dialogue['ask']!r}"
    )


def test_extract_substance_descriptor_parchment_desk_exempted():
    """Phase E (b): A1 — 'parchment desk' returns '' because
    'parchment' is in _CONTENTS_EXEMPTIONS['desk'].  Without the
    mitigation, parchment would match a wooden desk manifest and
    fire a false-positive mismatch DP."""
    from dialogue_validator import _extract_substance_descriptor
    assert _extract_substance_descriptor(
        "An old parchment desk stands there.", "desk"
    ) == "", (
        "Phase E regression: 'parchment' before 'desk' should be "
        "exempted by _CONTENTS_EXEMPTIONS['desk']"
    )


def test_validate_dialogue_parchment_via_volume_synonym_exempted():
    """Phase E (b): A1 for book — a manifest material of 'leather'
    must NOT fire mismatch when the LLM says 'My parchment volume'
    (volume is a book-synonym; parchment is in
    _CONTENTS_EXEMPTIONS['book'])."""
    dialogue = {
        "greet": "Hello, scholar.",
        "ask":   "My parchment volume, please.",
        "wrong": "That is not the volume.",
        "thank": "Yes, the parchment volume is mine!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="book", adjective="leather",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase E regression: parchment-as-book-material via volume "
        f"synonym should be exempted by _CONTENTS_EXEMPTIONS['book']; "
        f"got codes={codes}"
    )


# └── Phase E *negative* tests — over-fire guards ────────────────
#
# The mitigations MUST NOT over-fire.  Three sanity-check shapes
# that must STILL fire mismatch DPs after Phase E (so we don't
# silently skip genuine structural-material mismatches):

def test_validate_dialogue_gold_key_still_fires_mismatch():
    """Phase E (a) negative: 'key' has no contents-exemption, so a
    gold key vs iron manifest IS a real structural mismatch and
    must still fire."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my gold key.",
        "wrong": "That is not my key.",
        "thank": "Yes, the gold key is mine.",
    }
    _, decisions = validate_dialogue(dialogue, category="key", adjective="iron")
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase E regression: gold-on-key should still fire mismatch "
        f"DP (key not in any contents-exemption); got codes={codes}"
    )


def test_validate_dialogue_iron_chest_still_fires_mismatch():
    """Phase E (a) negative: 'iron' is in _SUBSTANCE_ADJECTIVES but
    NOT in _CONTENTS_EXEMPTIONS['chest'] (only gold/silver/bronze/
    copper are), so an 'iron chest' (manifest oak) is still a real
    structural-material mismatch and must fire."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find me an iron chest.",
        "wrong": "That is not the chest.",
        "thank": "Yes, the iron chest will do.",
    }
    _, decisions = validate_dialogue(dialogue, category="chest", adjective="oak")
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase E regression: iron-on-chest should still fire mismatch "
        f"DP (iron not in chest contents-exemptions); got codes={codes}"
    )


def test_validate_dialogue_parchment_chest_still_fires_mismatch():
    """Phase E (b) negative: parchment IS in the substance whitelist
    but NOT in _CONTENTS_EXEMPTIONS['chest'] (chest gets gold/silver/
    bronze/copper only — chests are made of wood/metal, not paper),
    so 'an old parchment chest' (manifest oak) is a real structural
    mismatch and must still fire."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my old parchment chest.",
        "wrong": "That chest is wrong.",
        "thank": "Yes, that's my parchment chest.",
    }
    _, decisions = validate_dialogue(dialogue, category="chest", adjective="oak")
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase E regression: parchment-on-chest should still fire "
        f"mismatch DP (parchment not in chest contents-exemptions); "
        f"got codes={codes}"
    )


# └── Phase E follow-up exemptions (pot urn, bottle flask) ───────────
#
# After the code-reviewer flagged missed container-adjacent
# exemptions, _CONTENTS_EXEMPTIONS was extended to include:
#   - "pot" (synonym "urn" -- a gold urn / silver urn describes the
#     ornament/contents, not the pot's own material).
#   - "bottle" (synonyms flask/vial/phial/jug -- those shapes are
#     typically glass or crystal shells).

def test_validate_dialogue_gold_urn_passes_through_pot():
    """Phase E follow-up: 'gold urn' (urn is pot's synonym) is in
    _CONTENTS_EXEMPTIONS['pot'] (gold/silver/bronze/copper).  Must
    NOT fire mismatch DP even when the manifest material is
    unrelated (e.g. clay)."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my gold urn, please.",
        "wrong": "That is not the right urn.",
        "thank": "Yes, the gold urn is mine!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="pot", adjective="clay",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase E follow-up regression: gold urn via pot-synonym "
        f"should be exempted by _CONTENTS_EXEMPTIONS['pot']; "
        f"got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"gold urn on pot should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


def test_validate_dialogue_glass_bottle_passes_through_bottle():
    """Phase E follow-up: 'glass bottle' is in _CONTENTS_EXEMPTIONS
    ['bottle'] (glass/crystal).  Must NOT fire mismatch DP even when
    the manifest material is unrelated (e.g. iron).  Without the
    exemption, an 'iron bottle' manifest + 'glass bottle' LLM line
    would falsely fire a structural-material mismatch."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the glass bottle.",
        "wrong": "That is not the right bottle.",
        "thank": "Yes, the glass bottle is what I needed!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="bottle", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase E follow-up regression: glass bottle should be "
        f"exempted by _CONTENTS_EXEMPTIONS['bottle']; got "
        f"codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"glass bottle should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


# └── Phase F follow-up: lantern / lamp / light vector ───────────
#
# Phase E code-reviewer deferred this.  lantern's synonyms are
# ["lamp", "light"].  Without exemption, decorative descriptors
# like "gold lamp" / "silver lamp" / "crystal lamp" / "glass
# lantern" / "golden lantern" fire a false-positive adjective
# mismatch DP when the manifest material is unrelated (e.g. iron,
# oak, brass -- all plausible lantern FRAMES in the foundry).
#
# Mitigation: extend _CONTENTS_EXEMPTIONS with "lantern":
# {gold, golden, silver, bronze, copper, glass, crystal}.  The
# existing A1 loop in _extract_substance_descriptor auto-applies
# the exemption to all synonyms (lamp, light) via the term loop,
# so no caller-side or _extract_substance_descriptor-side change
# is needed -- only the dict entry.


# ─── Exemption-pass tests (TDD-red pre-fix, green post-fix) ─────

def test_extract_substance_descriptor_gold_lamp_exempted():
    """Phase F helper-level: '_extract_substance_descriptor("Find
    my gold lamp", "lantern")' returns empty string because "gold"
    is in _CONTENTS_EXEMPTIONS['lantern'] (decoration/shade allow-
    list) and "lamp" is in lantern's synonym set, so the term-loop
    A1 check catches it before the descriptor is returned."""
    out = _extract_substance_descriptor("Find my gold lamp.", "lantern")
    assert out == "", (
        f"Phase F regression: gold lamp on lantern-category should "
        f"be exempted by _CONTENTS_EXEMPTIONS['lantern']; got {out!r}"
    )


def test_extract_substance_descriptor_silver_light_exempted():
    """Phase F helper-level: '_extract_substance_descriptor("Find
    my silver light", "lantern")' returns empty string.  light is
    lantern's lesser-known synonym; the term-loop auto-applies the
    exemption to all synonyms."""
    out = _extract_substance_descriptor("Find my silver light.", "lantern")
    assert out == "", (
        f"Phase F regression: silver light on lantern-category "
        f"should be exempted; got {out!r}"
    )


def test_validate_dialogue_crystal_lamp_passes_through_lantern():
    """Phase F wire-up: 'crystal lamp' (lamp is lantern's synonym)
    with cat=lantern and a non-crystal manifest (brass frame) must
    NOT fire mismatch DP -- the descriptor is in the new exemption
    set because crystal lamp shades are a real shape."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the crystal lamp.",
        "wrong": "That is not the right lamp.",
        "thank": "Yes, the crystal lamp works!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="brass",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase F regression: crystal lamp on lantern should be "
        f"exempted by _CONTENTS_EXEMPTIONS['lantern']; "
        f"got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"crystal lamp should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


def test_validate_dialogue_glass_lantern_passes_through_lantern():
    """Phase F wire-up: 'glass lantern' (the bare category word
    preceded by 'glass') with cat=lantern and a non-glass manifest
    (iron, a plausible frame material) must NOT fire mismatch DP."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my glass lantern, please.",
        "wrong": "That is not the right lantern.",
        "thank": "Yes, that glass lantern is mine!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase F regression: glass lantern should be exempted; "
        f"got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"glass lantern should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


def test_validate_dialogue_golden_lantern_passes_through_lantern():
    """Phase F wire-up: 'golden lantern' with iron manifest.  Both
    'gold' and 'golden' are in _SUBSTANCE_ADJECTIVES; both must be
    in _CONTENTS_EXEMPTIONS['lantern'] so 'golden lantern' does not
    sporadically regress while 'gold lantern' passes."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the golden lantern.",
        "wrong": "That is not the golden lantern.",
        "thank": "Yes, the golden lantern is perfect!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase F regression: golden lantern should be exempted "
        f"alongside gold lantern; got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"golden lantern should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


# ─── Over-fire guards (pass both pre- and post-fix) ────────────
#
# These pin that the lantern exemption isn't a blanket "accept
# any descriptor on a lantern" -- structural-material mismatches
# must STILL fire mismatch DPs (iron / brass / wood are real
# lantern FRAMES; a manifest disagreement should be flagged).

def test_validate_dialogue_iron_lamp_still_fires_mismatch():
    """Phase F over-fire guard: 'iron lamp' (cat=lantern) with a
    wooden manifest is a genuine structural-mismatch (iron is a
    frame material, not decoration).  Must STILL fire mismatch DP
    -- iron is NOT in _CONTENTS_EXEMPTIONS['lantern']."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my iron lamp, please.",
        "wrong": "That is not the iron lamp.",
        "thank": "Yes, the iron lamp is what I needed!",
    }
    _, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="oak",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase F over-fire regression: iron lamp on lantern with "
        f"oak manifest should still fire mismatch DP; "
        f"got codes={codes}"
    )


def test_validate_dialogue_brass_lantern_still_fires_mismatch():
    """Phase F over-fire guard: 'brass lantern' (cat=lantern) with
    a wooden manifest is a genuine structural-mismatch (brass is a
    common frame alloy, not decoration).  Must STILL fire mismatch
    DP -- brass is NOT in _CONTENTS_EXEMPTIONS['lantern']."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the brass lantern.",
        "wrong": "That is not the brass lantern.",
        "thank": "Yes, the brass lantern is what I wanted!",
    }
    _, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="wood",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase F over-fire regression: brass lantern on lantern "
        f"with wood manifest should still fire mismatch DP; "
        f"got codes={codes}"
    )


def test_validate_dialogue_wooden_lantern_still_fires_mismatch():
    """Phase F over-fire guard: 'wooden lantern' (cat=lantern) with
    an iron manifest is a genuine structural-mismatch (wooden is a
    common frame material, not decoration).  Must STILL fire
    mismatch DP -- wooden is NOT in _CONTENTS_EXEMPTIONS['lantern']."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Find my wooden lantern, please.",
        "wrong": "That is not the wooden lantern.",
        "thank": "Yes, the wooden lantern is perfect!",
    }
    _, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase F over-fire regression: wooden lantern on lantern "
        f"with iron manifest should still fire mismatch DP; "
        f"got codes={codes}"
    )


# ─── Phase F follow-up (reviewer-recommended fold-in) ───────────
#
# The Phase F reviewer flagged that paper lanterns (Chinese / Japanese
# chōchin shape) are a real historical lantern family, and that
# 'paper' is in _SUBSTANCE_ADJECTIVES so a 'paper lantern' line with
# a non-paper manifest (iron / oak / brass frame) would fire a
# false-positive mismatch DP.  Folded into the lantern exemption
# here + a 4th over-fire guard pins that 'stone lantern' (stone is
# a real Japanese garden-lantern shape but the foundry palette
# doesn't list stone-lantern, so firing mismatch is correct).


def test_validate_dialogue_paper_lantern_passes_through_lantern():
    """Phase F fold-in: 'paper lantern' (cat=lantern) with an
    unrelated frame manifest (iron) must NOT fire mismatch DP --
    paper-lantern is a real historical shape and 'paper' is now in
    _CONTENTS_EXEMPTIONS['lantern']."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the paper lantern.",
        "wrong": "That is not the paper lantern.",
        "thank": "Yes, the paper lantern is what I needed!",
    }
    validated, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" not in codes, (
        f"Phase F fold-in regression: paper lantern should be "
        f"exempted by _CONTENTS_EXEMPTIONS['lantern']; "
        f"got codes={codes}"
    )
    assert validated["ask"] == dialogue["ask"], (
        f"paper lantern should pass through unchanged; got "
        f"{validated['ask']!r} vs {dialogue['ask']!r}"
    )


def test_validate_dialogue_stone_lantern_still_fires_mismatch():
    """Phase F fold-in over-fire guard: 'stone lantern' (cat=
    lantern) with an iron manifest.  Stone IS in _SUBSTANCE_ADJECTIVES
    but is NOT in _CONTENTS_EXEMPTIONS['lantern'] regardless of
    palette state; pins that stone lantern still fires mismatch as
    long as stone is not in the lantern exemption)."""
    dialogue = {
        "greet": "Hello, traveler.",
        "ask":   "Bring me the stone lantern.",
        "wrong": "That is not the stone lantern.",
        "thank": "Yes, the stone lantern is what I wanted!",
    }
    _, decisions = validate_dialogue(
        dialogue, category="lantern", adjective="iron",
    )
    codes = [d.code for d in decisions]
    assert "quest.dialogue_adjective_mismatch" in codes, (
        f"Phase F fold-in over-fire regression: stone lantern on "
        f"lantern with iron manifest should still fire mismatch "
        f"DP; got codes={codes}"
    )
