"""Material pre-pass — deterministic resolution of a request's material
BEFORE the LLM runs.

Lexical matching is a regex's job, not a model's.  This module reads
``materials.MATERIAL_PALETTE`` (no hard-coded material list) and returns
``(material_id, list_of_DecisionPoint)``.  Decision Points are emitted
when the resolver defaulted (family had >1 members, or no keyword hit).

This is the first real emitter of Decision Points and fixes the
headline bug: ``'wrought-iron cabinet'`` was being resolved to
``'worn_oak'`` by the LLM.  It now deterministically resolves to
``'wrought_iron'`` and, when ambiguous, tells the user exactly why and
what the alternatives are.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from decisions import Choice, DecisionPoint, make_decision
from materials import MATERIAL_PALETTE


# ── Keyword maps ──────────────────────────────────────────────────
# Specific keywords (most specific wins): a keyword → material_id.
# Declaration order is tiebreak if a request matches several specific
# keywords; we go with the first hit.
_SPECIFIC_KW: dict[str, str] = {
    "oak": "worn_oak",
    "walnut": "dark_walnut",
    "pine": "weathered_pine",
    "granite": "rough_granite",
    "marble": "rough_granite",
    "iron": "wrought_iron",
    "wrought": "wrought_iron",
    "steel": "wrought_iron",
}

# Family keywords: a keyword → family name in MAT PALETTE.
_FAMILY_KW: dict[str, str] = {
    "wood": "wood",
    "wooden": "wood",
    "timber": "wood",
    "stone": "stone",
    "rock": "stone",
    "metal": "metal",
    "metallic": "metal",
}

# Global fallback (used when no keyword matched at all).
_DEFAULT_MATERIAL = "worn_oak"

# Short, human-readable description per material. Hand-authored, derived
# from the planner prompt's palette hints. Kept here (not in materials.py)
# to keep this slice's scope tight to the named files.
_PLAIN_DESCRIPTION: dict[str, str] = {
    "worn_oak": "warm brown wood",
    "dark_walnut": "dark brown wood",
    "weathered_pine": "pale desaturated wood",
    "rough_granite": "mottled grey stone",
    "wrought_iron": "dark tinted metal",
}


# ── Helpers ────────────────────────────────────────────────────────


def _word_in(text: str, kw: str) -> bool:
    """Case-insensitive, word-boundary substring match.  Hyphenated
    tokens like ``wrought-iron`` still match the keyword ``wrought``
    because the hyphen is a non-word boundary."""
    return re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE) is not None


def _family_members(family: str) -> List[str]:
    """Return the materials in *family*, in MATERIAL_PALETTE declaration
    order.  Drives family-default + choices-listing deterministically."""
    return [m for m, info in MATERIAL_PALETTE.items() if info["family"] == family]


def _label(material_id: str) -> str:
    """Human-friendly label for a Choice: ``dark_walnut`` → ``Dark Walnut``."""
    return material_id.replace("_", " ").title()


def _plain(material_id: str) -> str:
    return _PLAIN_DESCRIPTION.get(material_id, material_id)


def _choice(material_id: str) -> Choice:
    return Choice(
        label=_label(material_id),
        plain=_plain(material_id),
        apply={"field": "material", "value": material_id},
    )


# ── Public entry point ─────────────────────────────────────────────


def material_cues(request: str) -> List[Tuple[str, str]]:
    """Return ALL matched material cues for *request* as
    ``(keyword, family)`` — the multi-match counterpart of
    ``resolve_material``.  Single-sourced from ``_SPECIFIC_KW`` and
    ``_FAMILY_KW``:

    - a specific keyword → ``MATERIAL_PALETTE[mat]["family"]``
    - a family keyword → its own family name

    Iteration order is specific-first then family (matches
    ``resolve_material``'s priority); within each map, declaration
    order.  Same whole-word matching as ``_word_in``.

    Returns ``[]`` when no material keyword matches.
    """
    cues: List[Tuple[str, str]] = []
    for kw, mat_id in _SPECIFIC_KW.items():
        if _word_in(request, kw):
            info = MATERIAL_PALETTE.get(mat_id, {})
            family = info.get("family", mat_id)
            cues.append((kw, family))
    for kw, family in _FAMILY_KW.items():
        if _word_in(request, kw):
            cues.append((kw, family))
    return cues


def resolve_material(request: str) -> Tuple[str, List[DecisionPoint]]:
    """Resolve the material for *request* deterministically.  Returns
    ``(material_id, decisions)``.

    Outcomes:
        - specific keyword matched → confident, no decision
        - family keyword matched a SINGLE-member family → confident,
          no decision
        - family keyword matched a MULTI-member family → emits
          ``material.family_defaulted`` (severity=assumption); resolved
          is the family default; choices are the OTHER members
        - no keyword matched → emits ``material.unspecified_defaulted``
          (severity=assumption); resolved is the global default;
          choices are ALL palette materials
    """
    # 1. Specific keywords win (most specific).
    for kw, mat_id in _SPECIFIC_KW.items():
        if _word_in(request, kw):
            return mat_id, []

    # 2. Family keywords.
    for kw, family in _FAMILY_KW.items():
        if _word_in(request, kw):
            members = _family_members(family)
            if not members:
                # Defensive: the family exists in the spec but somehow
                # has no members in the palette. Fall through to default
                # like an unmatched request.
                break
            default = members[0]
            if len(members) == 1:
                return default, []
            others = [m for m in members if m != default]
            choices = tuple(_choice(m) for m in others)
            return default, [
                make_decision(
                    code="material.family_defaulted",
                    stage="planner",
                    severity="assumption",
                    context={"family": family, "resolved": default},
                    choices=choices,
                )
            ]

    # 3. No match → global default + unspecified_defaulted.
    resolved = _DEFAULT_MATERIAL
    all_materials = list(MATERIAL_PALETTE.keys())
    choices = tuple(_choice(m) for m in all_materials)
    return resolved, [
        make_decision(
            code="material.unspecified_defaulted",
            stage="planner",
            severity="assumption",
            context={"resolved": resolved},
            choices=choices,
        )
    ]
