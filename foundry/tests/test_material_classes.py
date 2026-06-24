"""Tests for foundry.material_classes — class taxonomy + class_for bridge."""
from __future__ import annotations

from material_classes import CLASSES, class_for


def test_classes_have_required_fields():
    for name, c in CLASSES.items():
        assert {"role", "roughness", "metallic", "texture"} <= set(c)


def test_family_mapping():
    assert class_for("wood") == "wood"
    assert class_for("stone") == "stone"
    assert class_for("metal") == "metal"


def test_material_id_mapping():
    assert class_for("worn_oak") == "wood"      # via MATERIAL_PALETTE family
    assert class_for("rough_granite") == "stone"


def test_unknown_defaults_to_stone():
    assert class_for("nonsense_qux") == "stone"


# Phase 3.1: triplanar flag

def test_triplanar_flag_on_classes():
    """3.1: Stone, wood, rock, soil have triplanar=True; metal, fabric, foliage have False."""
    for cls in ("stone", "wood", "rock", "soil"):
        assert CLASSES[cls].get("triplanar") is True, f"{cls} should be triplanar=True"
    for cls in ("metal", "fabric", "foliage"):
        assert CLASSES[cls].get("triplanar") is False, f"{cls} should be triplanar=False"
