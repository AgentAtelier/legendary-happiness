"""Material palette for the Forge foundry — five materials across three
families (wood, stone, metal), each with family-specific colour and
roughness parameters.

This is a plain data module, standalone (no engine/devforge imports).
"""

import random as _random

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
    # P-G: fabric family — for rugs and soft goods
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

    # WS-3.1: leather, ceramic, glazed, bronze, painted-wood
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


def material_variation(mat: dict, seed: int = 0) -> dict:
    """Return a copy of *mat* with deterministic seeded hue/wear jitter.

    Produces a unique variant of a base material so every instance of e.g.
    ``worn_oak`` in a room is perceptibly distinct (no monochrome rooms).
    The jitter is small (\u00b15% hue, \u00b10.06 roughness, \u00b18% metal)
    and fully deterministic for the given (mat, seed) pair.
    """
    rng = _random.Random(str(mat.get("family", "")) + "_" + str(seed))
    out = dict(mat)

    # Hue shift: small rotation of base/grain/tint/thread colours
    for key in ("base_rgb", "grain_light_rgb", "grain_dark_rgb",
                "tint_rgb", "thread_rgb", "mottle_rgb"):
        if key in out:
            rgb = list(out[key])
            shift = rng.uniform(-0.05, 0.05)
            # Rotate hue in RGB by shifting channels
            for i in range(3):
                rgb[i] = max(0.0, min(1.0, rgb[i] + shift))
            out[key] = tuple(rgb)

    # Roughness jitter: \u00b10.06
    if "roughness" in out:
        out["roughness"] = max(0.0, min(1.0,
            out["roughness"] + rng.uniform(-0.06, 0.06)))

    # Metallic jitter: \u00b10.08
    if "metallic" in out:
        out["metallic"] = max(0.0, min(1.0,
            out["metallic"] + rng.uniform(-0.08, 0.08)))

    return out


def material_ids() -> list[str]:
    """Return all valid material ids in MATERIAL_PALETTE."""
    return sorted(MATERIAL_PALETTE.keys())
