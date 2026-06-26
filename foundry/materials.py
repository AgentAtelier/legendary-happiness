#!/usr/bin/env python3
"""Material palette for the Forge foundry \u2014 seven materials across four
families (wood, stone, metal, fabric), each with family-specific colour and
roughness parameters.

This is a plain data module, standalone (no engine/devforge imports).
PROMPT 6-A: the per-instance HSV-jitter helpers `jitter_seed()` and
`jitter_for()` are added below the PALETTE dict, alongside the rewritten
`material_variation()` algorithm which now operates in HSV-space (was
per-channel RGB-shift).  `material_ids()` is unchanged.
"""

import colorsys
import hashlib
import random as _random
import struct


MATERIAL_PALETTE = {
    "worn_oak": {
        "family": "wood",
        "grain_light_rgb": (0.60, 0.40, 0.22),
        "grain_dark_rgb": (0.25, 0.14, 0.06),
        "roughness": 0.65,
    },
    "dark_walnut": {
        "family": "wood",
        "grain_light_rgb": (0.35, 0.18, 0.08),
        "grain_dark_rgb": (0.12, 0.06, 0.02),
        "roughness": 0.55,
    },
    "weathered_pine": {
        "family": "wood",
        "grain_light_rgb": (0.65, 0.58, 0.45),
        "grain_dark_rgb": (0.45, 0.38, 0.28),
        "roughness": 0.75,
    },
    "rough_granite": {
        "family": "stone",
        "base_rgb": (0.45, 0.45, 0.47),
        "mottle_rgb": (0.30, 0.30, 0.32),
        "roughness": 0.85,
        "metallic": 0.0,
    },
    "wrought_iron": {
        "family": "metal",
        "tint_rgb": (0.08, 0.08, 0.09),
        "base_rgb": (0.18, 0.18, 0.20),
        "roughness": 0.45,
        "metallic": 1.0,
    },
    # P-G: fabric family \u2014 for rugs and soft goods
    "linen": {
        "family": "fabric",
        "base_rgb": (0.82, 0.78, 0.68),
        "thread_rgb": (0.72, 0.68, 0.58),
        "roughness": 0.85,
        "metallic": 0.0,
    },
    "wool": {
        "family": "fabric",
        "base_rgb": (0.45, 0.35, 0.25),
        "thread_rgb": (0.35, 0.25, 0.18),
        "roughness": 0.92,
        "metallic": 0.0,
    },
    # WS-3.1: leather, ceramic, glazed, bronze, painted_wood
    "leather": {
        "family": "fabric",
        "base_rgb": (0.35, 0.22, 0.12),
        "thread_rgb": (0.28, 0.16, 0.08),
        "roughness": 0.70,
        "metallic": 0.0,
    },
    "ceramic": {
        "family": "stone",
        "base_rgb": (0.62, 0.42, 0.28),
        "mottle_rgb": (0.50, 0.34, 0.22),
        "roughness": 0.75,
        "metallic": 0.0,
    },
    "glazed": {
        "family": "stone",
        "base_rgb": (0.25, 0.45, 0.55),
        "mottle_rgb": (0.18, 0.35, 0.45),
        "roughness": 0.30,
        "metallic": 0.15,
    },
    "bronze": {
        "family": "metal",
        "tint_rgb": (0.60, 0.38, 0.10),
        "base_rgb": (0.72, 0.50, 0.18),
        "roughness": 0.40,
        "metallic": 1.0,
    },
    "painted_wood": {
        "family": "wood",
        "grain_light_rgb": (0.55, 0.30, 0.20),
        "grain_dark_rgb": (0.35, 0.15, 0.08),
        "roughness": 0.45,
    },
    "silk": {
        "family": "fabric",
        "base_rgb": (0.65, 0.15, 0.15),
        "thread_rgb": (0.55, 0.10, 0.10),
        "roughness": 0.35,
        "metallic": 0.08,
    },
}


# \u2500\u2500 PROMPT 6-A per-instance HSV jitter helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Queue binding (PROMPT 6-A): jitter seed = hash(entity_id + material_name).
# These helpers are the pure-Python contract every downstream caller uses:
#   - build_asset.py::apply_material pre-bake hook (commit 2)
#   - eval signal aggregator in foundry/eval/signals.py (commit 3)
# Both must produce IDENTICAL jitter for the same (entity_id, material_name)
# pair \u2014 the SHA-256 / 64-bit seed guarantees this, even across Python
# versions and processes.


def jitter_seed(entity_id: str, material_name: str) -> int:
    """Return a deterministic 64-bit unsigned seed derived from
    ``hash(entity_id + material_name)``.

    Same inputs \u2192 same seed; distinct (entity_id, material_name) pairs
    \u2192 distinct seeds (collision rate is astronomically low under SHA-256).

    Returns an ``int`` in ``[0, 2**64)``.
    """
    # NUL byte as field separator (BUGFIX for the "_-joined" join form
    # raised by code-reviewer: entity_id="ab", material_name="cd_ef" and
    # entity_id="ab_cd", material_name="ef" both produced the same SHA-256
    # digest under the old join.  A NUL separator makes field boundaries
    # unambiguous; manifest entities and palette names are user-supplied
    # identifiers that should never contain U+0000 in practice.).
    h = hashlib.sha256(f"{entity_id}\x00{material_name}".encode()).digest()
    return struct.unpack(">Q", h[:8])[0]  


def jitter_for(entity_id: str, material_name: str) -> tuple[float, float, float]:
    """Return the per-instance (dh_deg, ds_frac, dv_frac) HSV micro-jitter
    for ``(entity_id, material_name)``.  Pure function; same inputs \u2192
    identical tuple, distinct inputs \u2192 distinct tuples (within SHA-256
    collision tolerance \u2014 astronomically low for the test sizes we run).

    Bounds (queue scope):
      ``dh``        in [-5\u00b0, +5\u00b0]                 hue degrees
      ``ds``        in [-0.10, +0.10]                  saturation fraction
      ``dv``        in [-0.08, +0.08]                  value fraction
    """
    seed = jitter_seed(entity_id, material_name)
    rng = _random.Random(seed)
    return (
        rng.uniform(-5.0, 5.0),       # hue degrees (queue \u00b15\u00b0)
        rng.uniform(-0.10, 0.10),     # saturation fraction (queue \u00b110 %)
        rng.uniform(-0.08, 0.08),     # value fraction (queue \u00b18 %)
    )


def material_variation(mat: dict, seed: int = 0) -> dict:
    """Return a copy of *mat* with deterministic HSV-space hue/sat/val jitter.

    Produces a unique variant of a base material so every instance of e.g.
    ``worn_oak`` in a room is perceptibly distinct (no monochrome rooms).
    Jitter bounds (PROMPT 6-A queue scope):
        hue         \u00b15\u00b0   (small hue rotation)
        saturation  \u00b110 %  of the material's saturation
        value       \u00b18  %  of the material's value (lightness)
    Roughness keeps the prior \u00b10.06 jitter; metallic keeps \u00b10.08.

    Algorithm:
      1. Pull ONE triple (dh, ds, dv) from the seeded RNG stream -
         locked-step applies the same hue/sat/val envelope to ALL rgb
         triplets in the material so the family's grain-vs-base tone
         relationship is preserved (light + dark wood drift together, etc.).
         This is deliberate: per-key independent jitter would let, say,
         grain_light drift cool while grain_dark stays warm within one asset,
         which reads as "incoherent wood".  Per the queue's "look different
         but read the same family" intent, all rgb keys within ONE call move
         in lockstep so different calls diverge between assets.
      2. For each rgb triplet (base_rgb / grain_light_rgb / grain_dark_rgb
         / tint_rgb / thread_rgb / mottle_rgb): convert RGB->HSV, apply
         (dh, ds, dv), wrap H modulo 1.0, clamp S and V to [0, 1], convert
         back to RGB, clamp each channel to [0, 1] so the bake step never
         sees -ve or >1 floats that would corrupt the base-colour PNG.
      3. Apply scalar roughness and metallic jitter (kept from prior
         implementation so non-rgb signals still differ).

    Determinism: identical (mat, seed) -> byte-identical variant dict.
    """
    rng = _random.Random(str(mat.get("family", "")) + "_" + str(seed))
    out = dict(mat)

    # -- 1. Pull the ONE (dh, ds, dv) triple for colour jitter ------
    dh = rng.uniform(-5.0, 5.0) / 360.0   # hue in 0..1 (5deg == 1/72)
    ds = rng.uniform(-0.10, 0.10)         # saturation fraction
    dv = rng.uniform(-0.08, 0.08)         # value fraction

    # -- 2. HSV-space jitter for every rgb triplet in the material  --
    for key in (
        "base_rgb", "grain_light_rgb", "grain_dark_rgb",
        "tint_rgb", "thread_rgb", "mottle_rgb",
    ):
        if key not in out:
            continue
        r, g, b = out[key]
        # RGB -> HSV (colorsys uses 0..1 for s, v; h is in 0..1 too).
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        # Apply the jitter - wrap hue mod 1, clamp s/v to [0,1].
        h = (h + dh) % 1.0
        s = max(0.0, min(1.0, s + ds))
        v = max(0.0, min(1.0, v + dv))
        # HSV -> RGB and re-clamp each channel.
        nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
        out[key] = (
            max(0.0, min(1.0, float(nr))),
            max(0.0, min(1.0, float(ng))),
            max(0.0, min(1.0, float(nb))),
        )

    # -- 3. Roughness jitter: +/-0.06 (kept from prior implementation)
    if "roughness" in out:
        out["roughness"] = max(0.0, min(1.0,
            out["roughness"] + rng.uniform(-0.06, 0.06)))

    # -- 4. Metallic jitter: +/-0.08 (kept from prior implementation)
    if "metallic" in out:
        out["metallic"] = max(0.0, min(1.0,
            out["metallic"] + rng.uniform(-0.08, 0.08)))

    return out


def material_ids() -> list[str]:
    """Return all valid material ids in MATERIAL_PALETTE."""
    return sorted(MATERIAL_PALETTE.keys())
