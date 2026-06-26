"""Unit tests for foundry.biome_table — the exterior biome data + resolver.

Mirrors the shape/role of room_control.THEME_TABLE: static, pure data + a
resolver. The LLM picks a base_biome tag (an enum); resolve_biome maps it to a
row, falling back to the generic '*' biome for anything unknown.
"""

from __future__ import annotations

from biome_table import BIOME_TABLE, BIOMES, resolve_biome
from terrain_field import make_field

_FLORA_CATEGORIES = {"tree", "shrub", "rock"}


def test_biomes_nonempty_and_include_generic():
    assert len(BIOME_TABLE) >= 4
    assert "*" in BIOMES


def test_resolve_exact_match():
    row = resolve_biome("snow_forest")
    assert row["biome"] == "snow_forest"


def test_resolve_unknown_falls_back_to_generic():
    row = resolve_biome("bioluminescent_void")
    assert row["biome"] == "*"


def test_resolve_empty_falls_back_to_generic():
    assert resolve_biome("")["biome"] == "*"


def test_every_biome_has_required_fields():
    for row in BIOME_TABLE:
        assert isinstance(row["biome"], str)
        terr = row["terrain"]
        for k in ("amplitude", "base_frequency", "octaves", "lacunarity", "persistence"):
            assert k in terr
        assert isinstance(row["ground_materials"], tuple) and row["ground_materials"]
        assert isinstance(row["flora_set"], tuple)
        atm = row["atmosphere"]
        for k in ("fog_color", "fog_density", "sun_energy", "sky_tint"):
            assert k in atm


def test_flora_set_entries_well_formed():
    for row in BIOME_TABLE:
        for fl in row["flora_set"]:
            assert fl["category"] in _FLORA_CATEGORIES
            assert 0.0 <= fl["weight"]
            assert fl["density"] >= 0.0


def test_terrain_params_feed_make_field():
    row = resolve_biome("snow_forest")
    t = row["terrain"]
    f = make_field(
        amplitude=t["amplitude"], base_frequency=t["base_frequency"],
        octaves=t["octaves"], lacunarity=t["lacunarity"],
        persistence=t["persistence"], seed=1,
    )
    # smoke: it produces a finite height
    h = f and __import__("terrain_field").height_at(f, 0.0, 0.0)
    assert isinstance(h, float)


def test_biomes_tuple_matches_table():
    assert set(BIOMES) == {r["biome"] for r in BIOME_TABLE}
