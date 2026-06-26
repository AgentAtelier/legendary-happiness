"""Dialogue validator + deterministic fallback for quest NPC dialogue.

Mirrors ``material_resolver.py`` / ``age_resolver.py`` style:
deterministic, pre-LLM / post-LLM validation of text quality.
Each dialogue line is checked for length, code-injection, and
quest relevance.  On failure, a deterministic canned line is
substituted, and a Decision Point is emitted.

The fallback firing IS itself an event (feeds P2).
"""

from __future__ import annotations

import re

from decisions import DecisionPoint, make_decision

# ── Validation constants ──────────────────────────────────────────

_MIN_LENGTH = 3
_MAX_LENGTH = 200

# Quest-reference words — a line must contain at least one of these
# OR the target's category word to pass relevance check.
_QUEST_WORDS: set[str] = {
    "find", "fetch", "bring", "get", "item", "looking for",
    "looking", "search", "need", "lost", "missing", "help",
    "please", "thank", "found", "here", "take", "give",
    "yes", "no", "that", "this", "want", "quest",
    "hello", "welcome", "greetings", "hi", "hey",
    "ah", "oh", "well",
    "visitor", "traveler", "stranger", "friend",
}

# ── C4: Category synonyms (Phase 0.1) ──────────────────────────
# A quest cue line (ask/thank) must reference the TARGET CATEGORY — its
# word OR a known synonym — so the player is told which physical thing
# to fetch.  Without this, "Find my treasure." passes for category="book"
# (verb-only match) and the resulting quest is winnable-by-manifest but
# unplayable-by-text.  Lookup uses ``.get(default=[])`` so unknown
# categories fall back to the bare-word check only — no KeyError.
_CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "book":         ["tome", "volume", "manuscript", "ledger", "scroll"],
    "chest":        ["trunk", "coffer", "footlocker"],
    "weapon-rack":  ["rack", "armory stand"],
    "coin-pouch":   ["pouch", "purse", "sack", "coinpurse"],
    "cup":          ["goblet", "chalice", "mug", "tankard"],
    "gem":          ["jewel", "stone", "crystal"],
    "bottle":       ["flask", "vial", "phial", "jug"],
    "scroll":       ["parchment", "document", "scroll"],
    "dagger":       ["knife", "blade", "dirk"],
    "candle":       ["taper", "candlestick"],
    "key":          ["skeleton key", "passkey"],
    "ring":         ["band", "signet", "circlet"],
    "barrel":       ["cask", "keg", "tun"],
    "crate":        ["box", "case", "carton"],
    "shelf":        ["bookshelf", "shelving", "mantel"],
    "chair":        ["seat"],
    "stool":        ["seat"],
    "bench":        ["seat", "pew"],
    "table":        ["desk", "counter"],
    "desk":         ["bureau", "table"],
    "cabinet":      ["cupboard", "dresser", "commode"],
    "wardrobe":     ["closet", "armoire"],
    "lantern":      ["lamp", "light"],
    "pot":          ["cauldron", "kettle", "urn", "jar", "bowl", "vase"],
    "planter":      ["pot", "flowerpot"],
    "pillar":       ["column", "post", "obelisk"],
    "partition":    ["screen", "divider"],
    "ladder":       ["stepladder", "stairs"],
    "rug":          ["carpet", "mat", "tapestry"],
    "painting":     ["portrait", "picture", "canvas"],
    "humanoid":     ["person", "man", "woman", "figure", "statue"],
    # Edge-case shapes — fall-through to bare category word on lookup miss.
}

# ── C4b (Phase C): Substance-adjective whitelist ───────────────
# Words the LLM might use as material descriptors next to the
# target category.  Validator compares the descriptor extracted from
# the dialogue to the manifest material's expected adjective — and
# flags a quest.dialogue_adjective_mismatch DP (severity='error')
# when they disagree.  Conservative set: only unambiguous substance
# nouns (no size/shape words), and includes "stone" / "glass" /
# "crystal" etc. even though they're also gem-synonyms — the
# positional extract (see _extract_substance_descriptor) only fires
# when the substance word PRECEDES the category, not when it IS the
# category word.
#
# Phase D (code-reviewer follow-up): "ash" is intentionally NOT in
# this set.  Reason: there is no "ash" / "ash_wood" / "ash-tree"
# material in the foundry manifest, so the matcher could only ever fire
# if the LLM hallucinated "ash" as a descriptor (zero legitimate
# matches); AND "ash" is heavily ambiguous in non-substance English
# ("ash blonde", "ash grey", "ash urn" as a funerary urn for ashes,
# "ash figurine" as incense residue).  Keeping it produced more
# false-positive DP emissions than real coverage.  Adding it back is
# fine if/when a real "ash" material lands in the palette — update the
# Phase D tests in foundry/tests/test_dialogue_validator.py then.
#
# Phase E (deferred): two adjacent false-positive vectors the same
# positional extract will hit once they surface in builds:
#   - "gold" / "silver" in container contexts — "Find my gold pouch"
#     / "Bring me the gold chest" — the descriptor MAY name the
#     contents (gold coins inside a leather pouch) OR the container's
#     actual material (an ornate gold-adorned treasure chest).  The
#     positional extract can't tell them apart, so the validator
#     fires adjective_mismatch for both shapes.  Mitigation TBD
#     pending a survey of LLM output shapes — likely a per-category
#     contents-class allowlist of some form, but specifics still open.
#   - "parchment" double-duty — it's both a scroll-category synonym
#     AND a substance; positional extract saves most cases but
#     "parchment <non-scroll>" (e.g. "old parchment desk" where the
#     manifest desk material is oak) still slips through and fires a
#     false-positive mismatch DP.
_SUBSTANCE_ADJECTIVES: set[str] = {
    # Wood
    "wooden", "oak", "walnut", "pine", "mahogany",  # ash removed — Phase D
    # Metal
    "iron", "steel", "brass", "bronze", "copper", "metal",
    "gold", "golden", "silver", "platinum",
    # Stone
    "stone", "granite", "marble", "obsidian", "slate",
    # Other rigid materials
    "glass", "crystal", "ceramic", "clay", "porcelain",
    # Soft materials
    "leather", "silk", "velvet", "cloth", "linen", "cotton",
    # Paper-ish
    "paper", "parchment", "vellum",
}


# ── Phase E A1: per-category contents-allowlist ──────────────────────
#
# When a descriptor in _SUBSTANCE_ADJECTIVES ambiguously names the
# *contents* of a container (gold coins in a leather pouch) or the
# *contents* of a surface (a parchment scroll on a desk), the
# validator should not fire a mismatch against the container's /
# surface's own manifest material.  The dict below lists, for each
# shape of container/surface, the descriptors whose presence in a
# line is a legitimate contents-context descriptor (not a
# structural-material mismatch).
#
#   - Containers (coin-pouch, chest, pot) accept gold/silver/bronze/copper
#     (the metals commonly held inside; note "pot" has "urn" in its
#     synonym list, so "gold urn" / "silver urn" are contents-shape
#     descriptors for the pot category).
#   - Containers (bottle) accept glass/crystal (since bottle's synonym
#     list includes flask/vial/phial/jug, which are typically glass
#     or crystal shells).
#   - Surfaces (book, desk, table, shelf) accept parchment/paper/
#     vellum (the document materials legitimately on the surface;
#     vellum extends to all four for symmetry with desk's prior
#     exemption and to cover illuminated-manuscript / vellum-bound
#     shapes).
#
# Adding a future contents-shape is a one-line change here + a
# regression test in foundry/tests/test_dialogue_validator.py (see
# the Phase E over-fire guards for the contract shape).  A1 reads
# this dict from _extract_substance_descriptor.
#
# Phase E B1 (synonym-role skip) lives in _extract_substance_descriptor
# itself: when the captured descriptor IS a known synonym of the
# category, the match is skipped -- a "parchment scroll" with a
# paper manifest will not fire because parchment is in scroll's
# synonym list (synonym-role, not descriptor-role).
_CONTENTS_EXEMPTIONS: dict[str, set[str]] = {
    # Containers whose descriptors name contents.
    "coin-pouch": {"gold", "silver", "bronze", "copper"},
    "chest":      {"gold", "silver", "bronze", "copper"},
    # Pot has "urn" in its synonym list -- a gold urn / silver urn
    # describes the ornament/contents, not the pot's own material.
    "pot":        {"gold", "silver", "bronze", "copper"},
    # Bottle has flask/vial/phial/jug in its synonyms -- those
    # shapes are typically glass or crystal shells.
    "bottle":     {"glass", "crystal"},
    # Surfaces covered in paper-like documents.  Vellum extends to
    # all four (symmetric with desk): illuminated manuscripts,
    # vellum-bound furnishings, etc.
    "desk":  {"parchment", "paper", "vellum"},
    "table": {"parchment", "paper", "vellum"},
    "shelf": {"parchment", "paper", "vellum"},
    # Books whose binding/page material is parchment, paper, or vellum.
    "book":  {"parchment", "paper", "vellum"},
}


def _extract_substance_descriptor(line: str, category: str) -> str:
    """Phase C Fix B: positional extract of the substance adjective
    that DIRECTLY modifies *category* (or one of its known synonyms)
    in *line*.

    Returns the descriptor word when it is in the substance-adjective
    whitelist, else "".  Empty return means "no substance descriptor
    found here" — caller treats this as no mismatch.

    Why positional + filter: words like ``"stone"`` and ``"crystal"``
    are gem category synonyms, so a free-text scan for substance words
    would yield false positives on legitimate lines like ``"I lost a
    precious stone."`` (where ``stone`` IS the noun, not a descriptor).
    We therefore extract ONLY the word(s) IMMEDIATELY preceding the
    category (or its synonym), and filter to the substance whitelist.

    Examples::

      line="I lost my wooden key",        category="key"     → "wooden"
      line="I lost a precious stone",     category="gem"     → ""
      line="I seek my sharp-edged dagger", category="dagger" → ""  ("edged" not in whitelist)
      line="Find my oak key",             category="key"     → "oak"
    """
    lower = line.lower()
    # Phase E A1 + B1: build the per-category exemption sets once
    # outside the finditer loop so we don't re-resolve them per match.
    cat_lower = category.lower()
    synonyms_set = set(_CATEGORY_SYNONYMS.get(cat_lower, []))
    contents_exempt = _CONTENTS_EXEMPTIONS.get(cat_lower, set())
    terms = [cat_lower] + list(synonyms_set)
    for term in terms:
        for m in re.finditer(rf"\b(\w+)\s+{re.escape(term)}\b", lower):
            word = m.group(1)
            if word not in _SUBSTANCE_ADJECTIVES:
                continue
            # Phase E B1: skip if the captured descriptor is acting as a
            # synonym of the category itself (e.g. "parchment scroll" --
            # "parchment" is in the scroll synonym list, so it is
            # playing a synonym-role, NOT a substance-descriptor role).
            # Without B1, a paper-manifest scroll would fire a false
            # mismatch DP on a perfectly legitimate line.
            if word in synonyms_set:
                continue
            # Phase E A1: skip if the descriptor is a known
            # contents-context descriptor for the category (e.g. "gold
            # coin-pouch" -- "gold" is in coin-pouch's
            # contents-exempt set, naming the contents (coins) rather
            # than the container-material (often leather)).
            # Without A1, a leather-manifest coin-pouch would fire a
            # false mismatch DP on a perfectly legitimate line.
            if word in contents_exempt:
                continue
            return word
    return ""

# EB-6: Idle-bark words — a line must contain at least one to pass
# relevance for a non-conversation idle line.
_IDLE_WORDS: set[str] = {
    "hello", "hi", "hey", "greetings", "welcome",
    "ah", "oh", "hm", "hmm", "well", "so",
    "traveler", "stranger", "visitor", "friend",
    "busy", "work", "never", "always", "day", "night",
    "cold", "warm", "dark", "light",
    "seen", "heard", "wonder", "hope", "suppose",
}

# Code/markup/JSON patterns — a line containing any of these fails.
_CODE_PATTERNS: list[str] = [
    r"```",           # markdown code fences
    r"`[^`]+`",       # inline code
    r"\{[^}]*\}",     # JSON-like braces in free text
    r"<script",       # HTML injection
    r"</",            # closing HTML tags
    r"\{\{",          # template syntax
    r"\}\}",          # template syntax
    r"\\n",           # literal newline escapes
    r"\\t",           # literal tab escapes
    r"function\s*\(", # JS function calls
]

# ── Fallback dialogue ─────────────────────────────────────────────

_FALLBACK_TEMPLATES: dict[str, str] = {
    "greet": "Hello there, traveler.",
    "ask": "I am looking for the {adj} {category}. Can you bring it to me?",
    "wrong": "That is not what I am looking for.",
    "thank": "You found the {adj} {category}! Thank you so much.",
}

# EB-6: Canned idle barks per theme (used when LLM fails or is unavailable)
_CANNED_IDLE_BARKS: dict[str, list[str]] = {
    "hermit": [
        "Hmm, the days grow long in this quiet place.",
        "A visitor? It has been many moons.",
        "The shelves need dusting again...",
    ],
    "blacksmith": [
        "The forge-fire never sleeps.",
        "Steel bends to the patient hand.",
        "Another day, another dent in the anvil.",
    ],
    "wizard": [
        "The stars whisper secrets tonight.",
        "A tome misplaced is a spell forgotten.",
        "Dust motes dance in the candlelight.",
    ],
    "kitchen": [
        "Something's simmering — I can smell it.",
        "A sharp knife is a cook's best friend.",
        "The hearth-fire keeps the chill away.",
    ],
    "noble": [
        "These tapestries tell tales of old glory.",
        "Silence is a luxury few can afford.",
        "The estate grows quieter each season.",
    ],
    "dungeon": [
        "Water drips somewhere in the dark.",
        "The stone walls remember older hands.",
        "A draft — or something breathing?",
    ],
    "attic": [
        "So many things forgotten up here.",
        "A mouse just scurried past the rafters.",
        "The dust tells its own history.",
    ],
    "ship": [
        "The deck groans like an old friend.",
        "Salt spray and splintered wood.",
        "Land is a story the sea tells poorly.",
    ],
    "crypt": [
        "The darkness holds its breath.",
        "Shadows dance on ancient stone.",
        "Whispers echo from the depths.",
    ],
    "armory": [
        "Every blade tells a story of battle.",
        "Steel stacked ready for the forge's call.",
        "The scent of oiled metal hangs heavy.",
    ],
    "workshop": [
        "A craftsman's work is never truly done.",
        "Wood shavings curl like ribbon on the floor.",
        "The tools remember every hand that held them.",
    ],
    "tavern": [
        "The fire crackles, telling its own tales.",
        "Mugs clink in distant memory of cheer.",
        "The common room waits for voices to fill it.",
    ],
    "_default": [
        "The air is still, as if holding its breath.",
        "A quiet moment in a busy world.",
        "Time passes slowly here.",
    ],
}


def _line_length_ok(line: str) -> bool:
    """Check line is within the length band (inclusive)."""
    return _MIN_LENGTH <= len(line.strip()) <= _MAX_LENGTH


def _no_code_patterns(line: str) -> bool:
    """Check the line contains no code, markup, or JSON patterns."""
    for pat in _CODE_PATTERNS:
        if re.search(pat, line, flags=re.IGNORECASE):
            return False
    return True


def _references_quest(line: str, category: str) -> bool:
    """Check the line references the quest's TARGET.

    C4 (Phase 0.1): the category word OR a known synonym of the
    category must be present.  The quest-verb list is no longer a
    standalone pass — it is exposed via ``_has_quest_verb`` as a soft
    signal for callers that want to flag 'category referenced but no
    quest verb' as a heuristic, never as a blocking check.

    Without this fix, "Find my treasure." passes for category="book"
    (verb-only match) and the resulting quest is winnable-by-manifest
    but unplayable-by-text.
    """
    lower = line.lower()
    # Category match (word-boundary)
    if re.search(rf"\b{re.escape(category.lower())}\b", lower):
        return True
    # Synonym match (word-boundary per synonym) — .get(empty) is safe:
    # unknown categories fall back to the bare-word check, no KeyError.
    for syn in _CATEGORY_SYNONYMS.get(category.lower(), []):
        if re.search(rf"\b{re.escape(syn)}\b", lower):
            return True
    return False


def _has_quest_verb(line: str) -> bool:
    """Soft signal: does the line contain a generic quest verb?

    The verb list is no longer a hard gate on its own — see
    ``_references_quest`` — but is exposed here so callers (e.g. the
    ``quest.dialogue_no_verb`` soft DP a future caller might emit)
    can still flag 'category referenced but no quest verb' as a
    heuristic diagnostic.
    """
    lower = line.lower()
    for w in _QUEST_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", lower):
            return True
    return False


def _references_idle(line: str) -> bool:
    """EB-6: Check the line is a valid idle bark (non-conversational)."""
    lower = line.lower()
    for w in _IDLE_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", lower):
            return True
    return False


def validate_idle_bark(line: str) -> bool:
    """EB-6: Return True if *line* is valid idle-bark dialogue."""
    stripped = line.strip() if line else ""
    if not _line_length_ok(stripped):
        return False
    if not _no_code_patterns(stripped):
        return False
    if not _references_idle(stripped):
        return False
    return True


def validate_line(line: str, category: str) -> bool:
    """Return True if *line* is valid dialogue for the given target *category*."""
    stripped = line.strip() if line else ""
    if not _line_length_ok(stripped):
        return False
    if not _no_code_patterns(stripped):
        return False
    if not _references_quest(stripped, category):
        return False
    return True


def fallback_dialogue(category: str, adjective: str = "") -> dict[str, str]:
    """Return the full canned dialogue for a target *category*."""
    adj = adjective + " " if adjective else ""
    return {k: v.format(category=category, adj=adj).rstrip()
            for k, v in _FALLBACK_TEMPLATES.items()}


def validate_dialogue(
    dialogue: dict[str, str],
    category: str,
    adjective: str = "",
) -> tuple[dict[str, str], list[DecisionPoint]]:
    """Validate all four dialogue lines against *category*.

    C4 (Phase 0.1): the ``ask``+``thank`` cue lines must reference the
    TARGET CATEGORY (word or synonym).  When they don't, a
    ``quest.dialogue_target_mismatch`` Decision Point is emitted at
    severity="error" — the previous code path silently passed these
    diffs, producing quests winnable-by-manifest but unplayable-by-text.

    The fallback line substitution still applies (so the player sees a
    line that DOES mention the category); the error DP is on top, so
    the orchestrator surfaces the
    noun-mismatch in the build report.

    Returns ``(validated_dialogue, decisions)``.  For each line that
    fails validation, the fallback line is substituted and a
    ``quest.dialogue_fallback`` Decision Point is emitted.
    """
    validated: dict[str, str] = {}
    decisions: list[DecisionPoint] = []
    fallback = fallback_dialogue(category, adjective=adjective)

    for field in ("greet", "ask", "wrong", "thank"):
        line = dialogue.get(field, "") or ""
        stripped = line.strip()

        if field in ("ask", "thank"):
            # Strict check: category word OR known synonym must be present.
            # Length / code-pattern failures don't trigger target_mismatch
            # — those surface the existing ``quest.dialogue_fallback`` DP.
            cat_ref = _references_quest(stripped, category)
            length_ok = _line_length_ok(stripped)
            code_ok = _no_code_patterns(stripped)
            if cat_ref is False and length_ok and code_ok:
                decisions.append(
                    make_decision(
                        code="quest.dialogue_target_mismatch",
                        stage="planner",
                        severity="error",
                        context={
                            "field": field,
                            "original": stripped[:80],
                            "category": category,
                        },
                        choices=(),
                    )
                )
            is_valid = cat_ref and length_ok and code_ok

            # Phase C Fix B: substance-adjective mismatch check.
            # When the dialogue uses a substance adjective that DIRECTLY
            # modifies *category* (or its synonyms) and disagrees with
            # the manifest material's expected adjective, emit
            # ``quest.dialogue_adjective_mismatch`` at severity='error'
            # AND fall back to the canned template so the player still
            # sees a valid line that names the correct substance.
            #
            # Skipped when ``adjective`` is empty (older callers that
            # don't know the material) — the check requires a known
            # material to compare against.  Skipped when there's no
            # substance descriptor in the line — vague lines like
            # ``"Find my key."`` are fine.
            if is_valid and adjective:
                descriptor = _extract_substance_descriptor(stripped, category)
                if descriptor and descriptor != adjective.lower():
                    decisions.append(
                        make_decision(
                            code="quest.dialogue_adjective_mismatch",
                            stage="planner",
                            severity="error",
                            context={
                                "field": field,
                                "original": stripped[:80],
                                "descriptor": descriptor,
                                "expected": adjective,
                                "category": category,
                            },
                            choices=(),
                        )
                    )
                    # Setting is_valid=False INTENTIONALLY triggers the
                    # quest.dialogue_fallback DP below (one cue-line
                    # error → two DPs; cumulative signal in build_report).
                    is_valid = False
        else:
            # Greeter/reject lines use the looser semantics: category ref
            # OR a quest-verb ref is enough (a friendly "Ah, welcome,
            # traveler." greets without mentioning the item).
            cat_ref = _references_quest(stripped, category)
            verb_ref = _has_quest_verb(stripped)
            is_valid = (
                _line_length_ok(stripped)
                and _no_code_patterns(stripped)
                and (cat_ref or verb_ref)
            )

        if is_valid:
            validated[field] = line
        else:
            validated[field] = fallback[field]
            decisions.append(
                make_decision(
                    code="quest.dialogue_fallback",
                    stage="planner",
                    severity="info",
                    context={
                        "field": field,
                        "original": line[:80],
                        "fallback": fallback[field],
                    },
                    choices=(),
                )
            )

    return validated, decisions


# ── EB-6: Idle bark validation + fallback ─────────────────────────

def get_canned_idle_barks(theme: str) -> list[str]:
    """Return a list of canned idle barks for *theme* (keyword match)."""
    theme_lower = theme.lower()
    for key, barks in _CANNED_IDLE_BARKS.items():
        if key == "_default":
            continue
        if key in theme_lower:
            return list(barks)
    return list(_CANNED_IDLE_BARKS["_default"])


def validate_idle_barks(
    barks: list[str],
    theme: str = "",
) -> tuple[list[str], list[DecisionPoint]]:
    """EB-6: Validate a list of idle bark lines, falling back to canned.

    Returns ``(validated_barks, decisions)``.  At least 3 lines are
    guaranteed — if the input has fewer than 3 valid lines, canned
    fallbacks are appended.
    """
    decisions: list[DecisionPoint] = []
    validated: list[str] = []

    for i, line in enumerate(barks):
        if validate_idle_bark(line):
            validated.append(line)
        else:
            decisions.append(
                make_decision(
                    code="quest.idle_bark_fallback",
                    stage="planner",
                    severity="info",
                    context={"index": i, "original": line[:80]},
                    choices=(),
                )
            )

    # Guarantee at least 3 idle barks
    canned = get_canned_idle_barks(theme)
    _fill_attempts = 0
    while len(validated) < 3 and _fill_attempts < 10:
        _fill_attempts += 1
        _added = False
        for c in canned:
            if c not in validated:
                validated.append(c)
                _added = True
                break
        if not _added:
            # All canned barks are duplicates; break to avoid infinite loop
            break

    return validated[:5], decisions  # cap at 5 to avoid bloat
