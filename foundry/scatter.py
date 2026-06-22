"""foundry.scatter — deterministic flora placement on the terrain.

Distributes flora instances across the bounded terrain by per-category density,
rejecting positions inside an exclusion zone (the building footprint + door
corridor) or on slopes steeper than ``slope_max``. Each instance sits on the
terrain (Y from the shared ``terrain_field``).

Determinism: seeded ``random.Random`` keyed by (seed, category index) — NEVER
Python's ``hash()`` (string hashing is salted per-process). Same inputs →
identical placements; coordinates are rounded so the output is byte-stable.

A FloraPlacement is ``{category, x, y, z, yaw, scale}``.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence, Tuple

from terrain_field import Field, height_at, slope_at

# Exclusion zones are circles (cx, cz, radius) — a rectangular building
# footprint is passed as its bounding circle (conservative, keeps the
# entrance clear without rect math).
Exclusion = Tuple[float, float, float]


def scatter(
    field: Field,
    biome: dict,
    seed: int,
    *,
    extent: Optional[float] = None,
    exclusions: Optional[Sequence[Exclusion]] = None,
    slope_max: float = 1.2,
    scale_range: Tuple[float, float] = (0.8, 1.3),
) -> List[dict]:
    """Return deterministic flora placements for *biome* on *field*."""
    exclusions = list(exclusions or [])
    ext = float(extent) if extent is not None else field.extent
    half = ext / 2.0
    smin, smax = scale_range

    placements: List[dict] = []
    for i, fl in enumerate(biome.get("flora_set", ())):
        density = float(fl.get("density", 0.0))
        weight = float(fl.get("weight", 1.0))
        if density <= 0.0 or weight <= 0.0:
            continue
        target = int(round(density * ext * ext))
        if target <= 0:
            continue

        rng = random.Random((int(seed) * 1000003 + i * 9176) & 0x7FFFFFFF)
        category = fl["category"]
        kept = 0
        # Oversample so masks/exclusions don't starve the target count.
        for _ in range(target * 4):
            if kept >= target:
                break
            x = rng.uniform(-half, half)
            z = rng.uniform(-half, half)
            if _in_any_exclusion(x, z, exclusions):
                continue
            if slope_at(field, x, z) > slope_max:
                continue
            yaw = rng.uniform(0.0, 2.0 * math.pi)
            scale = rng.uniform(smin, smax)
            placements.append({
                "category": category,
                "x": round(x, 3),
                "y": round(height_at(field, x, z), 3),
                "z": round(z, 3),
                "yaw": round(yaw, 4),
                "scale": round(scale, 3),
            })
            kept += 1

    return placements


def _in_any_exclusion(x: float, z: float, exclusions: Sequence[Exclusion]) -> bool:
    for cx, cz, r in exclusions:
        if (x - cx) ** 2 + (z - cz) ** 2 <= r * r:
            return True
    return False
