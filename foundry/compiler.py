"""AssetCompiler: validate an asset-spec against the known generators and the
closed material/param vocabulary. Slice 1 has one generator (table). This is the
deterministic gate between LLM/hand intent and the Blender build — it does the
relative reasoning (range checks) the LLM must never do."""

from __future__ import annotations

import json

from materials import MATERIAL_PALETTE

GENERATORS = {"table", "chair", "shelf", "cabinet", "humanoid", "rug", "painting",
               "key", "book", "cup", "gem", "bottle", "scroll", "coin-pouch",
               "candle", "dagger", "ring",
               "barrel", "crate", "chest", "stool", "bench",
               "wardrobe", "desk", "lantern", "pot", "weapon-rack",
               "pillar", "planter"}
MATERIALS = set(MATERIAL_PALETTE.keys())

# Per-generator parameter ranges (min, max). The narrow, known-good envelope —
# the guardrail against the "95% of the parameter space is garbage" failure.
PARAM_RANGES = {
    "table": {
        "top_width": (0.5, 3.0),
        "top_depth": (0.4, 2.0),
        "top_thickness": (0.03, 0.2),
        "leg_height": (0.3, 1.1),
        "leg_radius": (0.03, 0.12),
        "leg_inset": (0.0, 0.3),
    },
    "chair": {
        "seat_width": (0.3, 0.55),
        "seat_depth": (0.3, 0.55),
        "seat_thickness": (0.03, 0.08),
        "leg_height": (0.25, 0.55),
        "leg_radius": (0.02, 0.05),
        "leg_inset": (0.0, 0.1),
        "back_height": (0.15, 0.4),
    },
    "shelf": {
        "width": (0.5, 1.15),
        "depth": (0.2, 0.345),
        "height": (0.6, 1.38),
        "board_thickness": (0.02, 0.06),
        "n_shelves": (2, 5),
        "side_thickness": (0.02, 0.05),
    },
    "cabinet": {
        "width": (0.5, 0.92),
        "depth": (0.3, 0.575),
        "height": (0.8, 1.84),
        "panel_thickness": (0.02, 0.06),
        "base_height": (0.03, 0.12),
    },
    # P7: stylized low-poly humanoid from box primitives.
    # total_height controls overall scale; the builder derives
    # per-part dimensions from fixed ratios (head ~0.2×, torso ~0.35×,
    # arms ~0.35×, legs ~0.45× of total_height).
    "humanoid": {
        "total_height": (1.2, 2.2),
        "body_width": (0.3, 0.7),
        "limb_thickness": (0.08, 0.2),
        "head_size": (0.15, 0.35),
    },
    # #6: thin flat decor — a rug/mat lying on the floor.
    "rug": {
        "width": (0.8, 3.5),
        "depth": (0.6, 2.5),
        "thickness": (0.01, 0.04),
    },
    # #6: thin vertical decor — a framed painting hung on a wall.
    "painting": {
        "width": (0.3, 1.2),
        "height": (0.3, 1.2),
        "thickness": (0.03, 0.08),
    },
    # P-E: 10 small carryable generators (≤0.3 m).
    "key": {
        "head_w": (0.03, 0.08),
        "head_h": (0.02, 0.05),
        "shaft_l": (0.04, 0.1),
    },
    "book": {
        "width": (0.1, 0.25),
        "depth": (0.08, 0.2),
        "thickness": (0.01, 0.05),
    },
    "cup": {
        "radius": (0.03, 0.08),
        "height": (0.06, 0.15),
    },
    "gem": {
        "size": (0.03, 0.08),
    },
    "bottle": {
        "body_radius": (0.03, 0.07),
        "body_height": (0.06, 0.15),
        "neck_radius": (0.01, 0.03),
        "neck_height": (0.03, 0.08),
    },
    "scroll": {
        "radius": (0.02, 0.05),
        "length": (0.1, 0.25),
    },
    "coin-pouch": {
        "width": (0.06, 0.15),
        "depth": (0.05, 0.12),
        "height": (0.04, 0.1),
    },
    "candle": {
        "radius": (0.02, 0.05),
        "height": (0.06, 0.15),
    },
    "dagger": {
        "blade_l": (0.1, 0.2),
        "blade_w": (0.01, 0.03),
        "handle_l": (0.05, 0.1),
    },
    "ring": {
        "size": (0.03, 0.07),
    },
    # P-F batch 1: themed-useful stress-test generators
    "barrel": {
        "radius": (0.2, 0.5),
        "height": (0.4, 1.0),
    },
    "crate": {
        "width": (0.3, 0.8),
        "depth": (0.3, 0.8),
        "height": (0.3, 0.8),
    },
    "chest": {
        "width": (0.3, 0.7),
        "depth": (0.2, 0.5),
        "height": (0.2, 0.5),
    },
    "stool": {
        "radius": (0.15, 0.3),
        "height": (0.3, 0.6),
    },
    "bench": {
        "width": (0.8, 2.0),
        "depth": (0.2, 0.4),
        "height": (0.3, 0.55),
    },
    # P-F batch 2: themed-useful generators
    "wardrobe": {
        "width": (0.6, 1.2),
        "depth": (0.4, 0.7),
        "height": (1.5, 2.5),
    },
    "desk": {
        "width": (0.8, 2.0),
        "depth": (0.4, 0.8),
        "height": (0.5, 0.9),
    },
    "lantern": {
        "radius": (0.08, 0.2),
        "height": (0.3, 0.8),
    },
    "pot": {
        "body_radius": (0.15, 0.4),
        "body_height": (0.3, 0.8),
        "neck_radius": (0.08, 0.25),
        "neck_height": (0.1, 0.3),
    },
    "weapon-rack": {
        "width": (0.3, 0.8),
        "depth": (0.15, 0.3),
        "height": (1.0, 2.2),
    },
    "pillar": {
        "radius": (0.15, 0.4),
        "height": (1.0, 3.0),
    },
    "planter": {
        "width": (0.3, 0.8),
        "depth": (0.3, 0.8),
        "height": (0.3, 0.7),
    },
}


class SpecError(ValueError):
    """Raised when an asset-spec is invalid (unknown generator/material, or a
    parameter missing or out of its known-good range)."""


def load_spec(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compile_spec(spec: dict) -> dict:
    gen = spec.get("generator")
    if gen not in GENERATORS:
        raise SpecError(f"unknown generator: {gen!r} (known: {sorted(GENERATORS)})")

    material = spec.get("material")
    if material not in MATERIALS:
        raise SpecError(f"unknown material: {material!r} (known: {sorted(MATERIALS)})")

    age = spec.get("age", 0.15)
    if not isinstance(age, (int, float)):
        raise SpecError(f"age must be a number, got {type(age).__name__}")
    age = float(age)
    if not (0.15 <= age <= 1.0):
        raise SpecError(f"age={age} out of range [0.15, 1.0]")

    params = spec.get("params") or {}
    ranges = PARAM_RANGES[gen]
    for key, (lo, hi) in ranges.items():
        if key not in params:
            raise SpecError(f"missing param: {key!r}")
        val = params[key]
        if not isinstance(val, (int, float)):
            raise SpecError(f"param {key!r} must be a number, got {type(val).__name__}")
        if not (lo <= val <= hi):
            raise SpecError(f"param {key!r}={val} out of range [{lo}, {hi}]")

    return {
        "asset_id": spec.get("asset_id", gen),
        "generator": gen,
        "material": material,
        "age": age,
        "params": {k: float(params[k]) for k in ranges},
    }
