"""Unit tests for materials.py — WS-3.1 new materials + seeded variation."""

from materials import MATERIAL_PALETTE, material_variation, material_ids


def test_new_materials_exist():
    """WS-3.1: leather, ceramic, glazed, bronze, painted_wood are registered."""
    for name in ("leather", "ceramic", "glazed", "bronze", "painted_wood"):
        assert name in MATERIAL_PALETTE, f"{name} missing from MATERIAL_PALETTE"


def test_leather_is_fabric():
    assert MATERIAL_PALETTE["leather"]["family"] == "fabric"
    assert "base_rgb" in MATERIAL_PALETTE["leather"]
    assert "thread_rgb" in MATERIAL_PALETTE["leather"]


def test_ceramic_is_stone():
    assert MATERIAL_PALETTE["ceramic"]["family"] == "stone"
    assert MATERIAL_PALETTE["ceramic"]["metallic"] == 0.0


def test_glazed_is_stone_with_sheen():
    assert MATERIAL_PALETTE["glazed"]["family"] == "stone"
    assert MATERIAL_PALETTE["glazed"]["metallic"] > 0.0
    assert MATERIAL_PALETTE["glazed"]["roughness"] < 0.5


def test_bronze_is_metal():
    assert MATERIAL_PALETTE["bronze"]["family"] == "metal"
    assert MATERIAL_PALETTE["bronze"]["metallic"] == 1.0
    assert "tint_rgb" in MATERIAL_PALETTE["bronze"]


def test_painted_wood_is_wood():
    assert MATERIAL_PALETTE["painted_wood"]["family"] == "wood"
    assert "grain_light_rgb" in MATERIAL_PALETTE["painted_wood"]
    assert "grain_dark_rgb" in MATERIAL_PALETTE["painted_wood"]


def test_variation_is_deterministic():
    """Same seed always produces same variant."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v1 = material_variation(mat, seed=42)
    v2 = material_variation(mat, seed=42)
    assert v1 == v2


def test_variation_different_seeds_differ():
    """Different seeds produce different variants."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v1 = material_variation(mat, seed=1)
    v2 = material_variation(mat, seed=2)
    # At least one float value should be different
    any_diff = False
    for k in v1:
        if v1[k] != v2[k]:
            any_diff = True
            break
    assert any_diff, "variants should differ for different seeds"


def test_variation_preserves_family():
    """Variation does not change the material family."""
    for name in ("worn_oak", "rough_granite", "wrought_iron", "linen"):
        mat = MATERIAL_PALETTE[name]
        v = material_variation(mat, seed=7)
        assert v["family"] == mat["family"]


def test_variation_roughness_in_range():
    """Roughness stays in [0, 1] after jitter."""
    mat = {"family": "stone", "base_rgb": (0.5, 0.5, 0.5), "mottle_rgb": (0.3, 0.3, 0.3), "roughness": 0.5, "metallic": 0.0}
    for seed in range(100):
        v = material_variation(mat, seed=seed)
        assert 0.0 <= v["roughness"] <= 1.0, f"roughness out of range at seed {seed}"


def test_variation_metallic_in_range():
    """Metallic stays in [0, 1] after jitter."""
    mat = {"family": "metal", "tint_rgb": (0.1, 0.1, 0.1), "base_rgb": (0.2, 0.2, 0.2), "roughness": 0.4, "metallic": 0.5}
    for seed in range(100):
        v = material_variation(mat, seed=seed)
        assert 0.0 <= v["metallic"] <= 1.0, f"metallic out of range at seed {seed}"


def test_variation_returns_copy():
    """Variation returns a copy, not the original."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v = material_variation(mat, seed=99)
    assert v is not mat
    v["roughness"] = 0.123
    assert mat["roughness"] != 0.123


def test_ids_returns_all():
    ids = material_ids()
    assert "worn_oak" in ids
    assert "leather" in ids
    assert "bronze" in ids
    assert "painted_wood" in ids
    assert len(ids) >= 13  # 8 original + 5 new
