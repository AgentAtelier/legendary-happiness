"""foundry.material_classes — material-class taxonomy + the bridge from the old
per-material world (MATERIAL_PALETTE families / prop categories) to classes.

A class is a coherence bucket: one neutral texture set + one palette role + fixed
surface params. The compiler emits one material per class per scene.
"""
from __future__ import annotations

from materials import MATERIAL_PALETTE

CLASSES: dict[str, dict] = {
    # Phase 3.1: triplanar flag controls whether materials get world-space
    # triplanar UV mapping.  True for large-surface natural materials
    # (stone/wood/rock/soil); False for small/wrong-scale materials
    # (metal/fabric/foliage — triplanar on tiny props causes moire).
    "stone":   {"role": "base",    "roughness": 0.9, "metallic": 0.0, "texture": "stone",   "triplanar": True},
    "wood":    {"role": "midtone", "roughness": 0.7, "metallic": 0.0, "texture": "wood",    "triplanar": True},
    "foliage": {"role": "foliage", "roughness": 0.8, "metallic": 0.0, "texture": "foliage", "triplanar": False},
    "rock":    {"role": "shadow",  "roughness": 0.9, "metallic": 0.0, "texture": "rock",    "triplanar": True},
    "metal":   {"role": "accent",  "roughness": 0.35, "metallic": 1.0, "texture": "metal",   "triplanar": False},
    "fabric":  {"role": "accent",  "roughness": 0.85, "metallic": 0.0, "texture": "fabric",  "triplanar": False},
    "soil":    {"role": "shadow",  "roughness": 0.95, "metallic": 0.0, "texture": "soil",    "triplanar": True},
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
