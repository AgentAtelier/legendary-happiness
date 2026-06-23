"""foundry.palette — deterministic scene palette from theme anchors + harmony.

build_palette() expands a theme's anchor colors + mood into a harmonized set of
ROLE colors (base/shadow/midtone/highlight/accent/foliage/sky). Engine-agnostic;
the compiler maps material-classes onto these roles. Deterministic.
"""
from __future__ import annotations

import colorsys

# anchors = primary (+optional) RGB; mood = temperature / saturation / value-key.
THEME_ANCHORS: dict[str, dict] = {
    "stone_keep":     {"anchors": [(0.46, 0.45, 0.43)], "mood": {"temp": "cool", "saturation": 0.5, "key": "mid"}},
    "dusk_crypt":     {"anchors": [(0.30, 0.30, 0.34)], "mood": {"temp": "cool", "saturation": 0.5, "key": "dark"}},
    "sunlit_market":  {"anchors": [(0.62, 0.50, 0.34)], "mood": {"temp": "warm", "saturation": 0.7, "key": "bright"}},
    "*":              {"anchors": [(0.50, 0.48, 0.45)], "mood": {"temp": "neutral", "saturation": 0.5, "key": "mid"}},
}

_KEY_VALUE = {"dark": 0.42, "mid": 0.62, "bright": 0.82}


def build_palette(theme: str, seed: int = 0, anchors: dict | None = None) -> dict:
    spec = anchors or THEME_ANCHORS.get(theme, THEME_ANCHORS["*"])
    base_rgb = spec["anchors"][0]
    mood = spec["mood"]
    h, s, v = colorsys.rgb_to_hsv(*base_rgb)

    # seed perturbs hue slightly within the mood (bounded ±0.04)
    h = (h + ((seed * 0.6180339887) % 1.0 - 0.5) * 0.08) % 1.0
    key_v = _KEY_VALUE[mood["key"]]
    s = max(0.0, min(1.0, mood["saturation"]))

    def rgb(hue, sat, val):
        return tuple(round(c, 4) for c in colorsys.hsv_to_rgb(hue % 1.0, max(0, min(1, sat)), max(0, min(1, val))))

    warm = mood["temp"] == "warm"
    roles = {
        "base":      rgb(h, s, key_v),
        "shadow":    rgb(h, s * 0.85, key_v * 0.6),
        "midtone":   rgb(h, s, key_v * 0.82),
        "highlight": rgb(h, s * 0.9, min(1.0, key_v * 1.35)),
        "accent":    rgb(h + 0.45, min(1.0, s + 0.2), key_v * 1.05),
        "foliage":   rgb(0.28, 0.45, key_v * (0.9 if mood["key"] != "dark" else 0.7)),
        "sky":       rgb(0.07 if warm else 0.6, 0.35, min(1.0, key_v * (1.2 if mood["key"] != "dark" else 0.9))),
    }
    return {"roles": roles, "theme": theme, "seed": int(seed)}
