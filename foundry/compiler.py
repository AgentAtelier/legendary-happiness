"""AssetCompiler: validate an asset-spec against the known generators and the
closed material/param vocabulary. Slice 1 has one generator (table). This is the
deterministic gate between LLM/hand intent and the Blender build — it does the
relative reasoning (range checks) the LLM must never do."""

from __future__ import annotations

import json

from materials import MATERIAL_PALETTE

GENERATORS = {"table"}
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
    }
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
        "params": {k: float(params[k]) for k in ranges},
    }
