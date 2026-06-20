"""Material palette for the Forge foundry — five materials across three
families (wood, stone, metal), each with family-specific colour and
roughness parameters.

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
    "silk": {
        "family": "fabric",
        "base_rgb": (0.65, 0.15, 0.15),
        "thread_rgb": (0.55, 0.10, 0.10),
        "roughness": 0.35,
        "metallic": 0.08,
    },
}
