"""AssetCompiler: validate an asset-spec against the known generators and the
closed material/param vocabulary.  The deterministic gate between LLM/hand
intent and the Blender build — it does the relative reasoning (range checks)
the LLM must never do.

T-4: GENERATORS and PARAM_RANGES are now derived from the single source of
     truth in ``category_registry``."""

from __future__ import annotations

import json

from category_registry import GENERATORS, PARAM_RANGES
from materials import MATERIAL_PALETTE

MATERIALS = set(MATERIAL_PALETTE.keys())


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
