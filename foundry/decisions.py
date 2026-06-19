"""Decision Points — the pipeline's explainable, recoverable-failure layer.

The foundry pipeline NEVER blocks. When it has to make an ambiguous or
assumption-laden choice (most commonly: which material to use for a
request that didn't specify one), it emits a structured Decision Point
the user can act on (now via CLI, later via a UI).

Two-register messages (plain + technical) come from HAND-AUTHORED
templates filled with the context dict — deterministic and local,
never LLM-generated prose (reliability + on-premise).

Data is separate from presentation: this module owns decisions as data;
only ``render_cli`` knows about presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


# SEVERITY string constants — the four known severities.
SEVERITY: Tuple[str, ...] = ("info", "assumption", "ambiguous", "error")


# ── Data classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Choice:
    """One concrete override the user can take instead of the default."""

    label: str           # short ("Wrought iron")
    plain: str           # one-line non-technical description
    apply: dict          # e.g. {"field": "material", "value": "wrought_iron"}


@dataclass(frozen=True)
class DecisionPoint:
    """One structured, emit-able event. Templates fill ``technical`` and
    ``plain`` deterministically from ``context``."""

    code: str            # "material.family_defaulted" | "material.unspecified_defaulted" | ...
    stage: str           # "planner" | "compiler" | "gate" | ...
    severity: str        # one of SEVERITY
    technical: str       # dev-facing message
    plain: str           # non-technical message
    context: dict        # {request, resolved, alternatives, ...}
    choices: Tuple[Choice, ...]


# ── Template registry ──────────────────────────────────────────────
# Authoring a NEW Decision Point type = one entry here + caller filling
# the right context keys.  Adding cases here is the only place prose
# lives.


_TEMPLATES: dict[str, tuple[str, str]] = {
    "material.family_defaulted": (
        # technical
        "material family={family} has multiple members; defaulted to {resolved}.",
        # plain
        "You asked for {family}, so I used {resolved}. You can switch to another {family}.",
    ),
    "material.unspecified_defaulted": (
        # technical
        "no material keyword matched; defaulted to {resolved}.",
        # plain
        "You didn't name a material, so I used {resolved}.",
    ),
}


# ── Factory + serialisation + presentation ─────────────────────────


def make_decision(
    code: str,
    stage: str,
    severity: str,
    context: dict,
    choices: Iterable[Choice],
) -> DecisionPoint:
    """Build a DecisionPoint, filling ``technical`` and ``plain`` from the
    template registry. Raises KeyError on unknown code — that's a
    programming error, not runtime data.
    """
    if code not in _TEMPLATES:
        raise KeyError(f"unknown decision code: {code!r} (known: {sorted(_TEMPLATES)})")
    technical_tmpl, plain_tmpl = _TEMPLATES[code]
    return DecisionPoint(
        code=code,
        stage=stage,
        severity=severity,
        technical=technical_tmpl.format(**context),
        plain=plain_tmpl.format(**context),
        context=dict(context),
        choices=tuple(choices),
    )


def to_dict(dp: DecisionPoint) -> dict:
    """JSON-serialisable dict view of a DecisionPoint. ``choices``
    become dicts in order."""
    return {
        "code": dp.code,
        "stage": dp.stage,
        "severity": dp.severity,
        "technical": dp.technical,
        "plain": dp.plain,
        "context": dp.context,
        "choices": [
            {"label": c.label, "plain": c.plain, "apply": c.apply}
            for c in dp.choices
        ],
    }


def render_cli(decisions: list[DecisionPoint]) -> str:
    """Human-readable dual-register block. ``info`` decisions are carried
    but not rendered. ONLY this function knows about presentation."""
    lines: list[str] = []
    for dp in decisions:
        if dp.severity == "info":
            continue
        lines.append(dp.plain)
        lines.append(f"  [technical: {dp.technical}]")
        for i, choice in enumerate(dp.choices, start=1):
            # apply is a dict like {"field": "material", "value": "wrought_iron"};
            # render the structured override as "field=value" (the spec example).
            # Fall back to all k=v pairs for non-structured overrides.
            if "field" in choice.apply and "value" in choice.apply:
                override = f"{choice.apply['field']}={choice.apply['value']}"
            else:
                override = ", ".join(f"{k}={v}" for k, v in choice.apply.items())
            lines.append(f"  {i}) {choice.label} — {choice.plain}  "
                         f"[set {override}]")
        lines.append("")  # blank line between decisions
    return "\n".join(lines)
