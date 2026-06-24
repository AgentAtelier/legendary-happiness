"""Age pre-pass — deterministic resolution of a request's wear intent
BEFORE the LLM runs.

Mirrors ``material_resolver.py``: lexical wear-word matching is a
regex's job, not a model's.  qwen's age output is provably unreliable
run-to-run; this module removes age from qwen entirely and resolves it
deterministically from ``foundry/wear_words.py``.

Returns ``(age_value, list_of_DecisionPoint)``.  Decision Points are
emitted when the resolver defaulted (no wear word) or when conflicting
aged+new words coexist.
"""

from __future__ import annotations

import re

from decisions import Choice, DecisionPoint, make_decision
from wear_words import AGED_WORDS, NEW_WORDS

# Resolved age values when wear intent is clear.
_AGED_AGE = 0.8
_NEW_AGE = 0.15
_FLOOR_AGE = 0.15  # fallback when nothing matched


def _has_word(text: str, kw: str) -> bool:
    """Whole-word case-insensitive match; hyphens are non-word boundaries
    so ``brand-new`` still matches the keyword ``brand``."""
    return re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE) is not None


def _make_age_choice(age_value: float) -> Choice:
    """Build a Choice that lets the user override to a different age."""
    label = f"age={age_value}"
    plain = "old/weathered" if age_value >= 0.4 else "fresh/new"
    return Choice(
        label=label,
        plain=plain,
        apply={"field": "age", "value": str(age_value)},
    )


def resolve_age(request: str) -> tuple[float, list[DecisionPoint]]:
    """Resolve the age for *request* deterministically.  Returns
    ``(age_value, decisions)``.

    Outcomes:
        - AGED word present, no NEW word → confident, no decision;
          resolves to 0.8.
        - NEW word present, no AGED word → confident, no decision;
          resolves to 0.15.
        - Both AGED and NEW words present → ``age.conflict``
          (severity=ambiguous); AGED wins (0.8).  Choices offer 0.15
          as the alternative.
        - No wear word → ``age.unspecified_defaulted``
          (severity=assumption); resolves to 0.15 (floor).  Choices
          offer 0.8 as the alternative.
    """
    # Check for conflict FIRST (before the single-class early returns).
    has_aged = any(_has_word(request or "", w) for w in AGED_WORDS)
    has_new = any(_has_word(request or "", w) for w in NEW_WORDS)

    if has_aged and has_new:
        return _AGED_AGE, [
            make_decision(
                code="age.conflict",
                stage="planner",
                severity="ambiguous",
                context={"resolved": _AGED_AGE, "alternative": _NEW_AGE},
                choices=(_make_age_choice(_NEW_AGE),),
            )
        ]

    if has_aged:
        return _AGED_AGE, []

    if has_new:
        return _NEW_AGE, []

    # Neither → unspecified_defaulted (assumption).
    return _FLOOR_AGE, [
        make_decision(
            code="age.unspecified_defaulted",
            stage="planner",
            severity="assumption",
            context={"resolved": _FLOOR_AGE},
            choices=(_make_age_choice(_AGED_AGE),),
        )
    ]
