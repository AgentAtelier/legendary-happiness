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
from typing import Dict, List, Tuple

from decisions import Choice, DecisionPoint, make_decision

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
    """Check the line references the quest: mentions the target's category
    OR a generic quest word (case-insensitive, word-boundary match)."""
    lower = line.lower()
    # Category match (word-boundary)
    if re.search(rf"\b{re.escape(category.lower())}\b", lower):
        return True
    # Quest-word match (each word on \b boundaries)
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
) -> Tuple[dict[str, str], List[DecisionPoint]]:
    """Validate all four dialogue lines against *category*.

    Returns ``(validated_dialogue, decisions)``.  For each line that fails
    validation, the fallback line is substituted and a ``quest.dialogue_fallback``
    Decision Point is emitted.
    """
    validated: dict[str, str] = {}
    decisions: list[DecisionPoint] = []
    fallback = fallback_dialogue(category, adjective=adjective)

    for field in ("greet", "ask", "wrong", "thank"):
        line = dialogue.get(field, "")
        if validate_line(line, category):
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
) -> Tuple[list[str], List[DecisionPoint]]:
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
