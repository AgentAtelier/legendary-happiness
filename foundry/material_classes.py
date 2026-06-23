"""foundry.material_classes — material-class taxonomy + the bridge from the old
per-material world (MATERIAL_PALETTE families / prop categories) to classes.

A class is a coherence bucket: one neutral texture set + one palette role + fixed
surface params. The compiler emits one material per class per scene.
"""
from __future__ import annotations

from materials import MATERIAL_PALETTE

CLASSES: dict[str, dict] = {
    "stone":   {"role": "base",    "roughness": 0.9, "metallic": 0.0, "texture": "stone"},
    "wood":    {"role": "midtone", "roughness": 0.7, "metallic": 0.0, "texture": "wood"},
    "foliage": {"role": "foliage", "roughness": 0.8, "metallic": 0.0, "texture": "foliage"},
    "rock":    {"role": "shadow",  "roughness": 0.9, "metallic": 0.0, "texture": "rock"},
    "metal":   {"role": "accent",  "roughness": 0.35, "metallic": 1.0, "texture": "metal"},
    "fabric":  {"role": "accent",  "roughness": 0.85, "metallic": 0.0, "texture": "fabric"},
    "soil":    {"role": "shadow",  "roughness": 0.95, "metallic": 0.0, "texture": "soil"},
}

# family (from MATERIAL_PALETTE) → class
_FAMILY_CLASS = {"wood": "wood", "stone": "stone", "metal": "metal",
                 "fabric": "fabric", "ceramic": "stone", "foliage": "foliage",
                 "rock": "rock", "soil": "soil"}


def class_for(key: str) -> str:
    if key in CLASSES:
        return key
    if key in _FAMILY_CLASS:
        return _FAMILY_CLASS[key]
    fam = (MATERIAL_PALETTE.get(key) or {}).get("family")
    if fam and fam in _FAMILY_CLASS:
        return _FAMILY_CLASS[fam]
    return "stone"
