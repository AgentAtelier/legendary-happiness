"""foundry.biome_recipe — validate + clamp the LLM biome recipe (exterior).

The interpreter emits a free-form ``biome_recipe``; this clamps it to the base
biome's **safe envelope** (the BIOME_TABLE row is the floor + fallback) and
returns a resolved biome dict — same shape as a table row, with flora weights
reweighted and densities scaled — plus Decision Points for legibility.

Discipline: the recipe may only *perturb* flora weights (among the base biome's
existing categories) and *scale* density (low/medium/high). It can never add a
category the biome doesn't support or push values outside the envelope. Pure +
deterministic, so the resolved biome is fully captured in the seeded spec.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from biome_table import resolve_biome
from decisions import Choice, DecisionPoint, make_decision

# Density keyword → flora-density multiplier (medium = the table baseline).
DENSITY_MULT = {"low": 0.5, "medium": 1.0, "high": 1.7}


def validate_biome_recipe(raw: Optional[dict]) -> Tuple[dict, List[DecisionPoint]]:
    """Resolve + clamp an LLM ``biome_recipe`` to a safe biome dict.

    Returns ``(biome, decisions)`` where *biome* mirrors a BIOME_TABLE row
    (with adjusted ``flora_set``) and *decisions* lists any fallback/clamp.
    """
    decisions: List[DecisionPoint] = []
    raw = raw or {}

    base_tag = str(raw.get("base_biome", "")).strip().lower()
    row = resolve_biome(base_tag)
    if base_tag and base_tag != "*" and row["biome"] == "*":
        decisions.append(make_decision(
            code="exterior.biome_fallback",
            stage="exterior",
            severity="ambiguous",
            context={"requested": base_tag, "resolved": "*"},
            choices=[Choice("Name a known biome",
                            "Use one of the supported biomes.",
                            {"field": "exterior.base_biome", "value": ""})],
        ))

    flora = [dict(f) for f in row["flora_set"]]
    by_cat = {f["category"]: f for f in flora}
    changes: List[str] = []

    # Density keyword → multiplier (invalid → baseline + a clamp note).
    density = str(raw.get("density", "")).strip().lower()
    if density and density not in DENSITY_MULT:
        changes.append(f"density '{density}' invalid")
        density = ""
    mult = DENSITY_MULT.get(density, 1.0)

    # Flora-mix reweight: only categories the biome already supports.
    for m in (raw.get("flora_mix") or []):
        if not isinstance(m, dict):
            continue
        cat = m.get("category")
        w = m.get("weight")
        if cat in by_cat and isinstance(w, (int, float)) and not isinstance(w, bool) and w >= 0:
            by_cat[cat]["weight"] = float(w)
        else:
            changes.append(f"flora '{cat}' dropped")

    # Renormalize weights to sum 1.0; apply the density multiplier.
    total = sum(f["weight"] for f in flora) or 1.0
    for f in flora:
        f["weight"] = round(f["weight"] / total, 4)
        f["density"] = round(f["density"] * mult, 5)

    if changes:
        decisions.append(make_decision(
            code="exterior.recipe_clamped",
            stage="exterior",
            severity="ambiguous",
            context={"changes": "; ".join(changes)},
            choices=[Choice("Keep adjusted recipe",
                            "I tuned the landscape to stay coherent.",
                            {})],
        ))

    biome = {**row, "flora_set": tuple(flora)}
    return biome, decisions
