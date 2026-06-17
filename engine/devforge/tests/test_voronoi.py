"""Unit tests for the Voronoi district/town engine.

Mirrors test_wfc.py.  No LLM — the engine is fully deterministic
given a seed.  Covers: seed determinism, district tessellation, road
detection, building placement, district types, no district-plane overlap
(regression guard for the bug just fixed), in-bounds positions.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_voronoi.py -v
"""

from __future__ import annotations

import random

import pytest

from devforge.spatial.voronoi import (
    VoronoiEngine,
    TownSpec,
    _DISTRICT_COLORS,
    _BUILDING_DIMS,
    _BUILDINGS_PER_DISTRICT,
)


@pytest.fixture
def engine():
    return VoronoiEngine()


def _create_steps(plan):
    return [s for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]


def _prop(plan, suffix, prop):
    for s in plan.steps:
        if (getattr(s, "step_type", "") == "set_property"
                and getattr(s, "property", "") == prop
                and s.node.endswith(suffix)):
            return s.value
    return None


# ── Imports ──────────────────────────────────────────────────────

class TestVoronoiImports:
    def test_engine_importable(self):
        assert VoronoiEngine is not None

    def test_townspec_importable(self):
        assert TownSpec is not None

    def test_engine_constructs(self, engine):
        assert isinstance(engine, VoronoiEngine)


# ── TownSpec ─────────────────────────────────────────────────────

class TestTownSpec:
    def test_defaults(self):
        spec = TownSpec()
        assert spec.width == 80 and spec.depth == 80
        assert spec.districts == 5
        assert spec.tile_size == 4.0
        assert spec.seed == 42

    def test_override(self):
        spec = TownSpec(width=100, depth=60, districts=8, tile_size=2.0, seed=7)
        assert (spec.width, spec.depth, spec.districts, spec.tile_size, spec.seed) == (
            100, 60, 8, 2.0, 7,
        )


# ── Seed determinism ─────────────────────────────────────────────

class TestSeedDeterminism:
    def _names_positions(self, plan):
        out = []
        for s in plan.steps:
            if getattr(s, "step_type", "") == "set_property" and s.property == "position":
                out.append((s.node, s.value["x"], s.value["z"]))
        return out

    def test_same_seed_is_identical(self, engine):
        j = {"region": {"width": 60, "depth": 60}, "districts": 3, "seed": 123}
        a = engine.compile_town(dict(j))
        b = engine.compile_town(dict(j))
        assert self._names_positions(a) == self._names_positions(b)

    def test_different_seed_differs(self, engine):
        a = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 3, "seed": 1},
        )
        b = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 3, "seed": 999},
        )
        assert self._names_positions(a) != self._names_positions(b)


# ── District tessellation ────────────────────────────────────────

class TestDistrictTessellation:
    def test_place_seeds_count(self, engine):
        """The number of seeds equals the number of districts requested."""
        for n in (1, 2, 4, 7):
            seeds = engine._place_seeds(TownSpec(districts=n, seed=1), random.Random(1))
            assert len(seeds) == n

    def test_seeds_in_bounds(self, engine):
        """Every seed is within the region."""
        spec = TownSpec(width=80, depth=60, districts=9, seed=42)
        seeds = engine._place_seeds(spec, random.Random(42))
        for sx, sz in seeds:
            assert 0 < sx < spec.width
            assert 0 < sz < spec.depth

    def test_first_district_is_civic(self, engine):
        """The centre district (index 0) is always 'civic'."""
        types = engine._assign_types(5, random.Random(1))
        assert types[0] == "civic"


# ── Compile town ─────────────────────────────────────────────────

class TestCompileTown:
    def test_produces_nodes(self, engine):
        plan = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 3, "seed": 1},
        )
        assert len(_create_steps(plan)) > 0

    def test_single_ground_plane_present(self, engine):
        """Regression: the district-plane-overlap bug was fixed — there should
        be ONE shared TownGround, not N overlapping district planes."""
        plan = engine.compile_town(
            {"region": {"width": 40, "depth": 40}, "districts": 4, "seed": 5},
        )
        grounds = [s for s in _create_steps(plan) if s.name == "TownGround"]
        assert len(grounds) == 1

    def test_no_duplicate_district_planes(self, engine):
        """Further regression guard: no district_* PlaneMesh nodes."""
        plan = engine.compile_town(
            {"region": {"width": 40, "depth": 40}, "districts": 5, "seed": 2},
        )
        district_planes = [
            s.name for s in _create_steps(plan)
            if s.name.startswith("district_")
        ]
        assert len(district_planes) == 0

    def test_roads_exist(self, engine):
        """Road_* tiles are created at district boundaries."""
        plan = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 4, "seed": 3},
        )
        road_nodes = [
            s.name for s in _create_steps(plan) if s.name.startswith("road_")
        ]
        assert len(road_nodes) > 0

    def test_buildings_exist(self, engine):
        """bld_* nodes are created inside districts."""
        plan = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 4, "seed": 7},
        )
        bld_nodes = [
            s.name for s in _create_steps(plan) if s.name.startswith("bld_")
        ]
        assert len(bld_nodes) > 0

    def test_positions_within_bounds(self, engine):
        """All road and building positions are within the region."""
        w, d, ts = 60, 60, 3.0
        plan = engine.compile_town(
            {"region": {"width": w, "depth": d}, "tile_size": ts, "districts": 4, "seed": 6},
        )
        for s in plan.steps:
            if getattr(s, "step_type", "") == "set_property" and s.property == "position":
                name = s.node.split("/")[-1] if "/" in s.node else s.node
                if name.startswith("road_") or name.startswith("bld_"):
                    x, z = s.value.get("x", 0), s.value.get("z", 0)
                    assert -0.01 <= x <= w + 0.01, f"{name}: x={x} out of [0,{w}]"
                    assert -0.01 <= z <= d + 0.01, f"{name}: z={z} out of [0,{d}]"

    def test_all_nodes_are_meshinstance3d(self, engine):
        plan = engine.compile_town(
            {"region": {"width": 40, "depth": 40}, "districts": 3, "seed": 1},
        )
        for s in _create_steps(plan):
            assert s.node_type == "MeshInstance3D"

    def test_small_grid_does_not_crash(self, engine):
        for w, d, n in ((30, 30, 2), (40, 40, 3), (80, 80, 6)):
            engine.compile_town(
                {"region": {"width": w, "depth": d}, "districts": n, "seed": 1},
            )

    def test_goal_mentions_town(self, engine):
        plan = engine.compile_town(
            {"region": {"width": 60, "depth": 60}, "districts": 3, "seed": 1},
        )
        assert "Voronoi town" in plan.goal


# ── District type catalogue ──────────────────────────────────────

class TestDistrictTypes:
    def test_all_seven_types_present(self):
        expected = {"residential", "commercial", "industrial", "park", "civic",
                     "waterfront", "default"}
        assert set(_DISTRICT_COLORS.keys()) == expected

    def test_each_type_has_dims_and_counts(self):
        for t in expected_district_types():
            assert t in _BUILDING_DIMS
            assert t in _BUILDINGS_PER_DISTRICT


def expected_district_types():
    return {"residential", "commercial", "industrial", "park", "civic",
            "waterfront", "default"}
