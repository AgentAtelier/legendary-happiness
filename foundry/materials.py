"""Material palette for the Forge foundry — three wood-tone materials sharing a
single procedural wood shader but with different colour/roughness parameters.

This is a plain data module, standalone (no engine/devforge imports).
"""

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
}
