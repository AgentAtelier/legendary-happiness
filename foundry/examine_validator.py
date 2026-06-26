"""Examine flavour-text generator + validator — EB-6 examine action.

Generates one-line LLM flavour text for each prop in the room,
validates it deterministically, and falls back to canned text
when the LLM output fails validation.  All generation happens
at build time (stored in quest_data.json) so the runtime examine
action never calls the LLM.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from decisions import DecisionPoint, make_decision

# ── Validation constants ──────────────────────────────────────────

_MIN_LENGTH = 8
_MAX_LENGTH = 160

# Code/markup/JSON patterns — a line containing any of these fails.
_CODE_PATTERNS: list[str] = [
    r"```",
    r"`[^`]+`",
    r"\{[^}]*\}",
    r"<script",
    r"</",
    r"\{\{",
    r"\}\}",
    r"\\n",
    r"\\t",
    r"function\s*\(",
]


# ── Canned fallback flavour text per category ─────────────────────

_FLAVOUR_FALLBACKS: dict[str, str] = {
    "table": "A sturdy table, scarred by years of use.",
    "chair": "A simple wooden chair, well-worn but solid.",
    "shelf": "A shelf cluttered with the dust of forgotten things.",
    "cabinet": "A cabinet with a faint smell of old wood.",
    "key": "A small key, its metal cold to the touch.",
    "book": "A leather-bound book, its pages yellowed with age.",
    "cup": "A clay cup, still bearing the marks of the potter's wheel.",
    "gem": "A gem that catches the light with an inner fire.",
    "bottle": "A glass bottle, its contents long since evaporated.",
    "scroll": "A rolled parchment, sealed with faded wax.",
    "coin_pouch": "A small leather pouch that jingles faintly.",
    "coin-pouch": "A small leather pouch that jingles faintly.",
    "candle": "A candle, its wick blackened from many nights of use.",
    "dagger": "A dagger with a keen edge and a worn grip.",
    "ring": "A ring of tarnished silver, inscribed with a faded script.",
    "lantern": "A lantern, its glass smoky from countless hours of light.",
    "rug": "A woven rug, its patterns telling a forgotten story.",
    "painting": "A painting in a dusty frame, its subject barely visible.",
    "_default": "An unremarkable object, worn smooth by time.",
}


# ── Examine prompt ────────────────────────────────────────────────

_EXAMINE_PROMPT = """You are a flavour-text writer for a small RPG. Given a prop's category, material, and the room theme, write a single short line of atmospheric flavour text that a player would see when they examine the object.

Prop: {category} ({material_desc})
Room: {room_theme}

Write ONE line of flavour text (8-160 chars). Be evocative but brief.
No dialogue, no jokes, no meta-commentary — just atmospheric description.
Output ONLY the flavour text — no quotes, no prefix, no explanation.

Flavour text:"""  # noqa: E501  literal


def _validate_flavour_line(line: str) -> bool:
    """Return True if *line* is valid examine flavour text."""
    stripped = line.strip() if line else ""
    if len(stripped) < _MIN_LENGTH or len(stripped) > _MAX_LENGTH:
        return False
    for pat in _CODE_PATTERNS:
        if re.search(pat, stripped, re.IGNORECASE):
            return False
    # Must be a sentence-like string (start with capital, end with .!?)
    if not re.match(r"^[A-Z]", stripped):
        return False
    if not re.search(r"[.!?]$", stripped):
        return False
    return True


def _category_fallback(category: str) -> str:
    """Return the canned fallback flavour text for *category*."""
    return _FLAVOUR_FALLBACKS.get(category, _FLAVOUR_FALLBACKS["_default"])


def _material_adjective(material: str) -> str:
    """Map a material id to a short descriptive adjective for the prompt."""
    adj_map: dict[str, str] = {
        "worn_oak": "worn oak",
        "dark_walnut": "dark walnut",
        "weathered_pine": "weathered pine",
        "rough_granite": "rough granite",
        "wrought_iron": "wrought iron",
        "linen": "linen",
        "wool": "wool",
        "silk": "silk",
    }
    return adj_map.get(material, material.replace("_", " "))


def generate_examine(
    room_theme: str,
    manifest: list[dict],
    llm: Callable[[str, str | None], str],
) -> tuple[dict[str, str], list[DecisionPoint]]:
    """Generate examine flavour text for every prop in *manifest*.

    Returns ``({prop_id: flavour_text}, decisions)``.  Calls the LLM
    once per prop with a focused prompt.  Validates output; falls back
    to canned text on failure.

    Args:
        room_theme: Room theme description string.
        manifest: List of placed-entity dicts with id, category, material.
        llm: Callable (prompt, grammar) -> str.

    Returns:
        (flavour_map, decisions).
    """
    decisions: list[DecisionPoint] = []
    flavour_map: dict[str, str] = {}

    for entry in manifest:
        eid = entry.get("id", "?")
        cat = entry.get("category", "?")
        mat = entry.get("material", "default")
        mat_desc = _material_adjective(mat)

        prompt = _EXAMINE_PROMPT.format(
            category=cat,
            material_desc=mat_desc,
            room_theme=room_theme,
        )

        try:
            response = llm(prompt, None)
        except Exception:
            # LLM unavailable — use fallback without emitting a DP
            flavour_map[eid] = _category_fallback(cat)
            continue

        cleaned = response.strip()
        # Strip quotes if the LLM wrapped the text
        if (cleaned.startswith('"') and cleaned.endswith('"')) or \
           (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1]

        if _validate_flavour_line(cleaned):
            flavour_map[eid] = cleaned
        else:
            fallback = _category_fallback(cat)
            flavour_map[eid] = fallback
            decisions.append(
                make_decision(
                    code="examine.flavour_fallback",
                    stage="planner",
                    severity="info",
                    context={
                        "prop_id": eid,
                        "category": cat,
                        "original": response[:80],
                        "fallback": fallback,
                    },
                    choices=(),
                )
            )

    return flavour_map, decisions
