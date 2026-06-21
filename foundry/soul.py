"""Soul — per-NPC Substrate + emotional-axes model (spine slice 3).

The first Anvil port (G1 Layered Soul).  Every NPC gets a Soul — a
Substrate (3 stable traits) + 4 emotional axes — the Interpreter
infers from the prompt, stored in Brief.characters[i].soul, baked
into quest_data, and used to bias dialogue tone.

``python-builds-godot-lives``: the soul is decided in Python at build
time and baked into quest_data; Godot reads it.  No runtime mutation
this slice (axes are stored as initial state only).
"""

from __future__ import annotations

from typing import List, Tuple

from decisions import Choice, DecisionPoint, make_decision

# ── Constants ─────────────────────────────────────────────────────

SUBSTRATE_TRAITS: Tuple[str, ...] = ("courage", "generosity", "stability")
AXES: Tuple[str, ...] = ("security", "belonging", "agency", "satiation")

# Threshold for tone adjective assignment: |value| >= this → tagged
_TONE_THRESHOLD: float = 0.33

# Tone mappings per trait: (low_label, high_label)
_TONE_MAP: dict[str, Tuple[str, str]] = {
    "courage":    ("timid",  "bold"),
    "generosity": ("guarded", "warm"),
    "stability":  ("anxious", "steady"),
}


# ── Public API ────────────────────────────────────────────────────

def default_soul() -> dict:
    """Return a full-shape soul dict with all values at 0.0."""
    return {
        "substrate": {t: 0.0 for t in SUBSTRATE_TRAITS},
        "axes":      {a: 0.0 for a in AXES},
    }


def validate_soul(raw: dict) -> Tuple[dict, List[DecisionPoint]]:
    """Validate and normalise a raw soul dict.

    Coerces values to float, clamps each to [-1.0, 1.0], defaults
    missing/non-numeric fields to 0.0.  Always returns the full shape
    regardless of input quality.

    Returns ``(soul_dict, decisions)``.
    """
    decisions: List[DecisionPoint] = []
    soul: dict = {"substrate": {}, "axes": {}}

    # ── Substrate traits ──
    raw_sub = raw.get("substrate", {}) if isinstance(raw, dict) else {}
    if not isinstance(raw_sub, dict):
        raw_sub = {}

    for trait in SUBSTRATE_TRAITS:
        raw_val = raw_sub.get(trait)
        if raw_val is None:
            # Explicit None → default to 0.0
            soul["substrate"][trait] = 0.0
            decisions.append(
                make_decision(
                    "soul.defaulted",
                    stage="interpreter",
                    severity="assumption",
                    context={"field": f"substrate.{trait}"},
                    choices=(
                        Choice(
                            label="Accept",
                            plain=f"Use default {trait} (0.0)",
                            apply={"field": f"substrate.{trait}", "value": 0.0},
                        ),
                    ),
                )
            )
        elif isinstance(raw_val, (int, float)):
            val = float(raw_val)
            if val < -1.0 or val > 1.0:
                clamped = max(-1.0, min(1.0, val))
                decisions.append(
                    make_decision(
                        "soul.clamped",
                        stage="interpreter",
                        severity="assumption",
                        context={
                            "field": f"substrate.{trait}",
                            "raw": val,
                            "clamped": clamped,
                        },
                        choices=(
                            Choice(
                                label="Accept",
                                plain=f"Clamp {trait} from {val} to {clamped}",
                                apply={"field": f"substrate.{trait}", "value": clamped},
                            ),
                        ),
                    )
                )
                soul["substrate"][trait] = clamped
            else:
                soul["substrate"][trait] = val
        else:
            # Non-numeric → default to 0.0
            soul["substrate"][trait] = 0.0
            decisions.append(
                make_decision(
                    "soul.defaulted",
                    stage="interpreter",
                    severity="assumption",
                    context={"field": f"substrate.{trait}"},
                    choices=(
                        Choice(
                            label="Accept",
                            plain=f"Use default {trait} (0.0)",
                            apply={"field": f"substrate.{trait}", "value": 0.0},
                        ),
                    ),
                )
            )

    # ── Axes ──
    raw_axes = raw.get("axes", {}) if isinstance(raw, dict) else {}
    if not isinstance(raw_axes, dict):
        raw_axes = {}

    for axis in AXES:
        raw_val = raw_axes.get(axis)
        if raw_val is None:
            soul["axes"][axis] = 0.0
            decisions.append(
                make_decision(
                    "soul.defaulted",
                    stage="interpreter",
                    severity="assumption",
                    context={"field": f"axes.{axis}"},
                    choices=(
                        Choice(
                            label="Accept",
                            plain=f"Use default {axis} (0.0)",
                            apply={"field": f"axes.{axis}", "value": 0.0},
                        ),
                    ),
                )
            )
        elif isinstance(raw_val, (int, float)):
            val = float(raw_val)
            if val < -1.0 or val > 1.0:
                clamped = max(-1.0, min(1.0, val))
                decisions.append(
                    make_decision(
                        "soul.clamped",
                        stage="interpreter",
                        severity="assumption",
                        context={
                            "field": f"axes.{axis}",
                            "raw": val,
                            "clamped": clamped,
                        },
                        choices=(
                            Choice(
                                label="Accept",
                                plain=f"Clamp {axis} from {val} to {clamped}",
                                apply={"field": f"axes.{axis}", "value": clamped},
                            ),
                        ),
                    )
                )
                soul["axes"][axis] = clamped
            else:
                soul["axes"][axis] = val
        else:
            soul["axes"][axis] = 0.0
            decisions.append(
                make_decision(
                    "soul.defaulted",
                    stage="interpreter",
                    severity="assumption",
                    context={"field": f"axes.{axis}"},
                    choices=(
                        Choice(
                            label="Accept",
                            plain=f"Use default {axis} (0.0)",
                            apply={"field": f"axes.{axis}", "value": 0.0},
                        ),
                    ),
                )
            )

    return soul, decisions


def tone_descriptor(soul: dict) -> str:
    """Return a deterministic adjective phrase from the soul's substrate.

    Thresholds at ±0.33:
      - courage ≤ -0.33 → "timid"; ≥ 0.33 → "bold"
      - generosity ≤ -0.33 → "guarded"; ≥ 0.33 → "warm"
      - stability ≤ -0.33 → "anxious"; ≥ 0.33 → "steady"

    Join present adjectives with ", "; if none cross threshold → "even-tempered".
    """
    substrate = soul.get("substrate", {}) if isinstance(soul, dict) else {}
    if not isinstance(substrate, dict):
        substrate = {}

    adjectives: list[str] = []
    for trait in SUBSTRATE_TRAITS:
        val = substrate.get(trait, 0.0)
        if not isinstance(val, (int, float)):
            continue
        low_label, high_label = _TONE_MAP[trait]
        if val <= -_TONE_THRESHOLD:
            adjectives.append(low_label)
        elif val >= _TONE_THRESHOLD:
            adjectives.append(high_label)

    if not adjectives:
        return "even-tempered"
    return ", ".join(adjectives)
