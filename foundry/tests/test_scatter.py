"""Unit tests for foundry.scatter — deterministic flora placement.

Contract: identical (field, biome, seed, exclusions) → identical placements;
nothing inside an exclusion circle or on a slope steeper than slope_max; every
instance sits on the terrain; categories come only from the biome.
"""

from __future__ import annotations

import pytest

from biome_table import resolve_biome
from scatter import scatter
from terrain_field import height_at, make_field, slope_at


def _biome():
    return resolve_biome("temperate_forest")


def test_deterministic():
    f = make_field(seed=4, extent=12.0)
    a = scatter(f, _biome(), seed=9, extent=12.0)
    b = scatter(f, _biome(), seed=9, extent=12.0)
    assert a == b
    assert len(a) > 0


def test_varies_with_seed():
    f = make_field(seed=4, extent=12.0)
    a = scatter(f, _biome(), seed=1, extent=12.0)
    b = scatter(f, _biome(), seed=2, extent=12.0)
    assert a != b


def test_respects_exclusion_circle():
    f = make_field(seed=4, extent=14.0)
    excl = [(0.0, 0.0, 4.0)]  # keep a 4 m radius around origin clear
    pts = scatter(f, _biome(), seed=3, extent=14.0, exclusions=excl)
    assert pts
    for p in pts:
        assert (p["x"] ** 2 + p["z"] ** 2) > 4.0 ** 2 - 1e-6


def test_respects_slope_mask():
    f = make_field(seed=8, extent=14.0, amplitude=4.0)  # hilly
    slope_max = 0.6
    pts = scatter(f, _biome(), seed=3, extent=14.0, slope_max=slope_max)
    for p in pts:
        assert slope_at(f, p["x"], p["z"]) <= slope_max + 1e-6


def test_instances_sit_on_terrain():
    f = make_field(seed=8, extent=12.0, amplitude=2.0)
    pts = scatter(f, _biome(), seed=3, extent=12.0)
    for p in pts:
        assert p["y"] == pytest.approx(round(height_at(f, p["x"], p["z"]), 3), abs=1e-3)


def test_zero_density_no_placements():
    f = make_field(seed=8, extent=12.0)
    biome = {"biome": "x", "flora_set": (
        {"category": "tree", "weight": 1.0, "density": 0.0},
    )}
    assert scatter(f, biome, seed=3, extent=12.0) == []


def test_categories_only_from_biome():
    f = make_field(seed=8, extent=12.0)
    biome = _biome()
    cats = {fl["category"] for fl in biome["flora_set"]}
    for p in scatter(f, biome, seed=3, extent=12.0):
        assert p["category"] in cats


def test_scale_in_range():
    f = make_field(seed=8, extent=12.0)
    for p in scatter(f, _biome(), seed=3, extent=12.0):
        assert 0.8 <= p["scale"] <= 1.3
