"""foundry.exterior_planner — assemble the ExteriorPlan (Approach A).

Runs beside RoomPlanner. Given a Brief with an enabled ``exterior`` block, it:
  1. resolves + clamps the biome recipe (``biome_recipe``),
  2. builds the shared terrain ``Field`` from the biome's terrain params,
  3. seats the building (= the interior room's footprint) at the origin on a
     flattened pad (pad height = max terrain over the footprint → never floats),
  4. excludes the footprint + door corridor and scatters flora,
  5. spawns the player outside, on the door side, facing the door.

Pure + deterministic: identical (brief, seed) → identical plan, fully captured
in the seeded spec.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from biome_recipe import validate_biome_recipe
from scatter import scatter
from terrain_field import Field, height_at, make_field

# Room footprint estimate per scale band (interior dims the building wraps).
# Midpoint of brief.SCALE_BANDS; half-extent = mid / 2.
_SCALE_FOOTPRINT = {"small": 5.0, "medium": 7.5, "large": 10.5}
_SPAWN_DIST = 3.0          # metres the player stands out from the door
_FOOTPRINT_MARGIN = 0.5    # exclusion padding around the shell
_DEFAULT_EXTENT = 40.0


@dataclass
class ExteriorPlan:
    field: Field
    biome: dict
    building: dict          # center, half_w, half_d, pad_height, door_side, door_center, structure
    spawn: dict             # x, z, yaw
    scatter_placements: List[dict]
    names: dict
    decisions: list
    extent: float


def plan_exterior(
    brief: dict,
    seed: int,
    *,
    extent: float = _DEFAULT_EXTENT,
    room_dims: Tuple[float, float] | None = None,
    slope_max: float = 1.2,
) -> ExteriorPlan | None:
    """Return an :class:`ExteriorPlan`, or ``None`` if exterior is disabled."""
    ext_brief = (brief or {}).get("exterior") or {}
    if not ext_brief.get("enabled"):
        return None

    biome, decisions = validate_biome_recipe(ext_brief.get("biome_recipe"))

    t = biome["terrain"]
    field = make_field(
        extent=extent, amplitude=t["amplitude"], base_frequency=t["base_frequency"],
        octaves=t["octaves"], lacunarity=t["lacunarity"], persistence=t["persistence"],
        seed=int(seed),
    )

    # Footprint (the interior room the building wraps).
    if room_dims is not None:
        half_w, half_d = room_dims[0] / 2.0, room_dims[1] / 2.0
    else:
        f = _SCALE_FOOTPRINT.get(str(brief.get("scale", "medium")), 7.5)
        half_w = half_d = f / 2.0

    # Pad height = max terrain over the footprint (corners + center) → the
    # building floor sits at/above terrain everywhere (never floats/clips).
    samples = [height_at(field, sx * half_w, sz * half_d)
               for sx in (-1, 0, 1) for sz in (-1, 0, 1)]
    pad_height = round(max(samples), 3)

    door_center = (0.0, round(half_d, 3))          # +Z wall midpoint
    spawn = {
        "x": 0.0,
        "z": round(half_d + _SPAWN_DIST, 3),
        "yaw": round(math.pi, 4),                  # face -Z, toward the door
    }
    building = {
        "center": (0.0, 0.0),
        "half_w": round(half_w, 3),
        "half_d": round(half_d, 3),
        "pad_height": pad_height,
        "door_side": "+z",
        "door_center": door_center,
        "structure": ext_brief.get("structure", "cabin"),
    }

    # Exclusions: building bounding circle + a door-corridor circle.
    r_building = math.hypot(half_w, half_d) + _FOOTPRINT_MARGIN
    corridor_c = (0.0, half_d + _SPAWN_DIST / 2.0)
    corridor_r = _SPAWN_DIST / 2.0 + 1.0
    exclusions = [(0.0, 0.0, r_building), (corridor_c[0], corridor_c[1], corridor_r)]

    placements = scatter(field, biome, int(seed), extent=extent,
                         exclusions=exclusions, slope_max=slope_max)

    names = _normalize_names(brief.get("place_names"))

    return ExteriorPlan(
        field=field, biome=biome, building=building, spawn=spawn,
        scatter_placements=placements, names=names, decisions=list(decisions),
        extent=float(extent),
    )


def _normalize_names(raw: dict | None) -> dict:
    raw = raw or {}
    scene_name = raw.get("scene_name")
    lore = raw.get("landmark_lore")
    out_lore: List[dict] = []
    if isinstance(lore, list):
        for item in lore:
            if isinstance(item, dict) and "landmark_id" in item and "line" in item:
                out_lore.append({"landmark_id": str(item["landmark_id"]), "line": str(item["line"])})
    return {
        "scene_name": str(scene_name) if scene_name else "",
        "landmark_lore": out_lore,
    }
