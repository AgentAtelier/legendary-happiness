#!/usr/bin/env python3
"""Material palette for the Forge foundry - seven materials across four
families (wood, stone, metal, fabric), each with family-specific colour and
roughness parameters.

This is a plain data module, standalone (no engine/devforge imports).
PROMPT 6-A: the per-instance HSV-jitter helpers `jitter_seed()` and
`jitter_for()` are added below the PALETTE dict, alongside the rewritten
`material_variation()` algorithm (locked-step HSV-shift via the shared
`_apply_hsv_jitter_to_rgbs` helper) and the build_asset pre-bake hook
`apply_instance_jitter()`.
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
    # P-G: fabric family - for rugs and soft goods
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


# ---- PROMPT 6-A per-instance HSV jitter helpers ----------------
# Queue binding (PROMPT 6-A): jitter seed = hash(asset_id + material_name).
# These helpers are the pure-Python contract every downstream caller uses:
#   - build_asset.py::apply_material pre-bake hook (commits 2)
#   - eval signal aggregator in foundry/eval/signals.py (commit 3)
# Both must produce IDENTICAL jitter for the same (asset_id, material_name)
# pair - the SHA-256 / 64-bit seed guarantees this across Python versions.


def jitter_seed(asset_id: str, material_name: str) -> int:
    """Return a deterministic 64-bit unsigned seed derived from
    ``hash(asset_id + material_name)``.

    Same inputs -> same seed; distinct (asset_id, material_name) pairs
    -> distinct seeds (collision rate is astronomically low under SHA-256).

    Returns an ``int`` in ``[0, 2**64)``.

    Uses a NUL byte (chr 0) as field separator so that, for example,
    ``("ab", "cd_ef")`` and ``("ab_cd", "ef")`` produce different seeds.
    Manifest ids and palette names are user-supplied identifiers that
    should never contain U+0000 in practice.
    """
    h = hashlib.sha256(f"{asset_id}\x00{material_name}".encode()).digest()
    return struct.unpack(">Q", h[:8])[0]


def jitter_for(asset_id: str, material_name: str) -> tuple[float, float, float]:
    """Return the per-instance (dh_deg, ds_frac, dv_frac) HSV micro-jitter
    for ``(asset_id, material_name)``.  Pure function; same inputs ->
    identical tuple, distinct inputs -> distinct tuples (within SHA-256
    collision tolerance - astronomically low for the test sizes we run).

    Bounds (queue scope):
        ``dh``        in [-5, +5]    hue degrees
        ``ds``        in [-0.10, +0.10]  saturation fraction
        ``dv``        in [-0.08, +0.08]  value fraction
    """
    seed = jitter_seed(asset_id, material_name)
    rng = _random.Random(seed)
    return (
        rng.uniform(-5.0, 5.0),
        rng.uniform(-0.10, 0.10),
        rng.uniform(-0.08, 0.08),
    )


def _apply_hsv_jitter_to_rgbs(
    mat: dict, dh_deg: float, ds_frac: float, dv_frac: float,
) -> dict:
    """Apply locked-step HSV jitter to a copy of ``mat``'s RGB triplets.

    INTERNAL helper shared by ``material_variation()`` (per-call seeded RNG
    path) and ``apply_instance_jitter()`` (per-asset-id seeded RNG path).
    Both call paths flow through this so the algorithm stays in lockstep
    if a future fix updates one but not the other.

    Locks-step applies the SAME (dh, ds, dv) triple to ALL rgb triplets
    in the material so the family's grain-vs-base tone relationship is
    preserved (light + dark wood drift together, base + mottle drift
    together).  Per-key independent jitter would let, say, grain_light
    drift cool while grain_dark stays warm within ONE asset, which reads
    as "incoherent wood" - the queue's "look different but read the same
    family" intent is preserved by the locked step across keys WITHIN
    one call.

    Across calls, distinct seeds land different triples so different
    asset_ids of the same material diverge perceptibly between assets.

    Hue is wrapped modulo 1.0; saturation and value are clamped to [0, 1];
    each round-trip RGB channel is re-clamped to [0, 1] so the bake step
    never sees -ve or >1 floats that would corrupt the base-colour PNG.

    Returns a NEW dict; the input is NOT mutated.
    """
    out = dict(mat)
    dh = dh_deg / 360.0  # hue degrees -> 0..1 colour-wheel fraction
    for key in (
        "base_rgb", "grain_light_rgb", "grain_dark_rgb",
        "tint_rgb", "thread_rgb", "mottle_rgb",
    ):
        if key not in out:
            continue
        r, g, b = out[key]
        # RGB -> HSV (colorsys uses 0..1 for s, v; h is in 0..1 too).
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        # Wrap hue mod 1, clamp s/v to [0, 1].
        h = (h + dh) % 1.0
        s = max(0.0, min(1.0, s + ds_frac))
        v = max(0.0, min(1.0, v + dv_frac))
        # HSV -> RGB and re-clamp each channel.
        nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
        out[key] = (
            max(0.0, min(1.0, float(nr))),
            max(0.0, min(1.0, float(ng))),
            max(0.0, min(1.0, float(nb))),
        )
    return out


def apply_instance_jitter(mat: dict, asset_id: str, material_name: str) -> dict:
    """Return a NEW copy of ``mat`` with per-instance HSV jitter applied.

    The build_asset pre-bake hook (commits 2).  Pulls ONE
    ``(dh_deg, ds_frac, dv_frac)`` triple from ``jitter_for(asset_id,
    material_name)`` (SHA-256 keyed under-the-hood), then forwards the
    triple to the shared ``_apply_hsv_jitter_to_rgbs`` helper so the
    per-asset-id and per-call (material_variation) paths share the same
    colour-shift algorithm.

    Bounds (queue scope, from ``jitter_for``):
        hue degrees       in [-5, +5]
        saturation frac   in [-0.10, +0.10]
        value frac        in [-0.08, +0.08]

    Determinism: identical ``(mat, asset_id, material_name)``
    -> byte-identical copy.  No mutation of input or of
    ``MATERIAL_PALETTE``; safe to call in the build hot path without
    side-effect surprises.  Two distinct ``asset_id`` values of the same
    ``material_name`` produce perceptibly different variances within
    the queue envelope (the locked-step design carries meaning across
    all RGB keys in the same family so grain light/dark drift together).
    """
    dh_deg, ds_frac, dv_frac = jitter_for(asset_id, material_name)
    return _apply_hsv_jitter_to_rgbs(mat, dh_deg, ds_frac, dv_frac)


def material_variation(mat: dict, seed: int = 0) -> dict:
    """Return a copy of *mat* with deterministic HSV-space hue/sat/val jitter.

    Produces a unique variant of a base material so every instance of e.g.
    ``worn_oak`` in a room is perceptibly distinct (no monochrome rooms).
    Jitter bounds (PROMPT 6-A queue scope):
        hue         +/-5 deg   (small hue rotation)
        saturation  +/-10 %  of the material's saturation
        value       +/-8  %  of the material's value (lightness)
    Roughness keeps the prior +/-0.06 jitter; metallic keeps +/-0.08.

    Algorithm:
      1. Pull ONE triple ``(dh_deg, ds_frac, dv_frac)`` from the seeded
         RNG stream (order preserved on purpose: ``dh`` then ``ds`` then
         ``dv`` then roughness then metallic - re-ordering would silently
         break determinism for callers holding a ``seed=42`` cache).
      2. Forward the triple to the shared
         ``_apply_hsv_jitter_to_rgbs`` helper (which applies it
         in lockstep to every rgb key in the family; see helper
         docstring for the "lockstep so the family signature survives"
         design rationale).
      3. Apply scalar roughness and metallic jitter (kept from prior
         implementation so non-rgb signals still differ).

    Determinism: identical ``(mat, seed)`` -> byte-identical variant dict.
    """
    rng = _random.Random(str(mat.get("family", "")) + "_" + str(seed))
    out = dict(mat)

    # 1. Pull the ONE (dh, ds, dv) triple for colour jitter
    dh_deg = rng.uniform(-5.0, 5.0)
    ds_frac = rng.uniform(-0.10, 0.10)
    dv_frac = rng.uniform(-0.08, 0.08)

    # 2. HSV-space jitter via the shared helper (lockstep across keys)
    out = _apply_hsv_jitter_to_rgbs(out, dh_deg, ds_frac, dv_frac)

    # 3. Roughness jitter: +/-0.06 (kept from prior implementation)
    if "roughness" in out:
        out["roughness"] = max(0.0, min(1.0,
            out["roughness"] + rng.uniform(-0.06, 0.06)))

    # 4. Metallic jitter: +/-0.08 (kept from prior implementation)
    if "metallic" in out:
        out["metallic"] = max(0.0, min(1.0,
            out["metallic"] + rng.uniform(-0.08, 0.08)))

    return out


def material_ids() -> list[str]:
    """Return all valid material ids in MATERIAL_PALETTE."""
    return sorted(MATERIAL_PALETTE.keys())
