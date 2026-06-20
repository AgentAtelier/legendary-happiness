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
