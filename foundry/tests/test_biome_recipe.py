"""Unit tests for foundry.biome_recipe — validate/clamp the LLM biome recipe.

The table is the floor + fallback; the recipe only perturbs flora weights and
density WITHIN the base biome's envelope. Every clamp/fallback emits a Decision
Point (legibility). Pure + deterministic.
"""

from __future__ import annotations

import pytest
from biome_recipe import DENSITY_MULT, validate_biome_recipe
from biome_table import resolve_biome


def _codes(decisions):
    return [d.code for d in decisions]


def test_none_recipe_returns_generic_no_decision():
    biome, decisions = validate_biome_recipe(None)
    assert biome["biome"] == "*"
    assert decisions == []


def test_valid_base_resolves_without_decision():
    biome, decisions = validate_biome_recipe({"base_biome": "desert"})
    assert biome["biome"] == "desert"
    assert decisions == []


def test_unknown_base_fires_fallback():
    biome, decisions = validate_biome_recipe({"base_biome": "void"})
    assert biome["biome"] == "*"
    assert "exterior.biome_fallback" in _codes(decisions)


def test_density_high_scales_flora_up():
    base = resolve_biome("meadow")
    base_density = {f["category"]: f["density"] for f in base["flora_set"]}
    biome, _ = validate_biome_recipe({"base_biome": "meadow", "density": "high"})
    for f in biome["flora_set"]:
        assert f["density"] == pytest.approx(round(base_density[f["category"]] * DENSITY_MULT["high"], 5))


def test_density_low_scales_flora_down():
    base = resolve_biome("meadow")
    base_density = {f["category"]: f["density"] for f in base["flora_set"]}
    biome, _ = validate_biome_recipe({"base_biome": "meadow", "density": "low"})
    for f in biome["flora_set"]:
        assert f["density"] < base_density[f["category"]]


def test_invalid_density_clamped_with_decision():
    biome, decisions = validate_biome_recipe({"base_biome": "meadow", "density": "insane"})
    assert "exterior.recipe_clamped" in _codes(decisions)
    # mult falls back to 1.0 → densities equal base
    base = resolve_biome("meadow")
    base_density = {f["category"]: f["density"] for f in base["flora_set"]}
    for f in biome["flora_set"]:
        assert f["density"] == pytest.approx(base_density[f["category"]])


def test_flora_mix_reweights_within_base_categories():
    biome, _ = validate_biome_recipe({
        "base_biome": "temperate_forest",
        "flora_mix": [{"category": "shrub", "weight": 5.0}],
    })
    weights = {f["category"]: f["weight"] for f in biome["flora_set"]}
    assert weights["shrub"] > weights["tree"]  # shrub now dominant
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_flora_mix_unknown_category_dropped_with_decision():
    biome, decisions = validate_biome_recipe({
        "base_biome": "temperate_forest",
        "flora_mix": [{"category": "mushroom", "weight": 3.0}],
    })
    assert "exterior.recipe_clamped" in _codes(decisions)
    # base categories preserved, weights still sum to 1
    cats = {f["category"] for f in biome["flora_set"]}
    assert "mushroom" not in cats
    assert sum(f["weight"] for f in biome["flora_set"]) == pytest.approx(1.0, abs=1e-3)


def test_weights_always_renormalize_to_one():
    for tag in ("snow_forest", "desert", "swamp", "*"):
        biome, _ = validate_biome_recipe({"base_biome": tag})
        assert sum(f["weight"] for f in biome["flora_set"]) == pytest.approx(1.0, abs=1e-3)


def test_deterministic():
    raw = {"base_biome": "swamp", "density": "high", "flora_mix": [{"category": "tree", "weight": 2}]}
    a, _ = validate_biome_recipe(raw)
    b, _ = validate_biome_recipe(raw)
    assert a["flora_set"] == b["flora_set"]
