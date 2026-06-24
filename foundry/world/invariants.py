"""Invariant checks for the world model.

Tiered invariants:
  - HARD (severity=error): block the commit (reject).
    - referential integrity: a placement's material must be in the
      known material palette.
    - budget: max placements per zone.
  - SOFT (severity=info or assumption): emit a DecisionPoint but
    allow the commit.
    - style rule example: warn if all placements in a zone share the
      same material (material monoculture).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from decisions import DecisionPoint, make_decision
from world.model import World


def check_invariants(
    world: World,
    *,
    material_palette: Dict[str, Any] | None = None,
    max_per_zone: int = 100,
) -> List[DecisionPoint]:
    """Run all invariants against *world*.

    Returns a list of Decision Points.  HARD decisions have
    severity=error and should block the commit.  SOFT decisions have
    severity=info and are advisory only.
    """
    if material_palette is None:
        from materials import MATERIAL_PALETTE
        material_palette = MATERIAL_PALETTE

    decisions: List[DecisionPoint] = []

    # ── HARD: referential integrity ───────────────────────────────
    _check_referential_integrity(world, material_palette, decisions)

    # ── HARD: budget ──────────────────────────────────────────────
    _check_zone_budget(world, max_per_zone, decisions)

    # ── SOFT: style rule ──────────────────────────────────────────
    _check_material_monoculture(world, decisions)

    return decisions


# ── Individual checks ────────────────────────────────────────────────


def _check_referential_integrity(
    world: World,
    palette: Dict[str, Any],
    decisions: List[DecisionPoint],
):
    """HARD: every placement's material (if present in attrs) must be in
    the known material palette."""
    for p in world.placements:
        mat = p.attrs.get("material")
        if mat is not None and mat not in palette:
            decisions.append(
                make_decision(
                    code="world.referential_integrity",
                    stage="world-model",
                    severity="error",
                    context={
                        "placement_id": p.id,
                        "material": mat,
                    },
                    choices=(),
                )
            )


def _check_zone_budget(
    world: World,
    max_per_zone: int,
    decisions: List[DecisionPoint],
):
    """HARD: max placements per zone must not be exceeded."""
    zone_counts: Counter[str] = Counter()
    for p in world.placements:
        zone = p.attrs.get("zone", "default")
        zone_counts[zone] += 1

    for zone, count in zone_counts.items():
        if count > max_per_zone:
            decisions.append(
                make_decision(
                    code="world.zone_budget_exceeded",
                    stage="world-model",
                    severity="error",
                    context={
                        "zone": zone,
                        "count": count,
                        "max": max_per_zone,
                    },
                    choices=(),
                )
            )


def _check_material_monoculture(
    world: World,
    decisions: List[DecisionPoint],
):
    """SOFT: warn if all placements in a zone share the same material
    (material monoculture)."""
    zone_materials: Dict[str, Counter[str]] = {}
    for p in world.placements:
        zone = p.attrs.get("zone", "default")
        mat = p.attrs.get("material")
        if mat is None:
            continue
        if zone not in zone_materials:
            zone_materials[zone] = Counter()
        zone_materials[zone][mat] += 1

    for zone, mat_counter in zone_materials.items():
        total = sum(mat_counter.values())
        if total >= 2:
            top_mat = mat_counter.most_common(1)[0][0]
            if mat_counter[top_mat] == total:
                decisions.append(
                    make_decision(
                        code="world.material_monoculture",
                        stage="world-model",
                        severity="info",
                        context={
                            "zone": zone,
                            "material": top_mat,
                            "placement_count": total,
                        },
                        choices=(),
                    )
                )
