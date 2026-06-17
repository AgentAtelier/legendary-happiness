"""Tests for Outdoor Scatter Engine — Poisson-disk + jittered grid.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_scatter.py -v
"""

from __future__ import annotations

import math
import pytest

from devforge.spatial.scatter import (
    ScatterEngine,
    KeepOutZone,
    SpeciesSpec,
    ScatterRegion,
)
from devforge.spatial.lexicon import AssetLexicon


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """ScatterEngine without lexicon — uses hardcoded fallback defaults."""
    return ScatterEngine(lexicon=None)


@pytest.fixture
def engine_with_lexicon():
    """ScatterEngine with real asset lexicon for plant footprints/meshes."""
    return ScatterEngine(lexicon=AssetLexicon())


# ── Poisson-disk basic tests ────────────────────────────────────

class TestPoissonDiskBasic:
    """Core Poisson-disk sampler: count, spacing, boundaries."""

    def test_places_requested_count(self, engine):
        """Sampler places exactly the requested count in a spacious region."""
        points = engine._poisson_disk_sample(
            width=50.0, depth=50.0,
            min_radius=2.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=10,
            seed=42,
        )
        assert len(points) == 10

    def test_all_points_within_bounds(self, engine):
        """Every point lies within [item_radius, width-item_radius] × [...depth...]."""
        points = engine._poisson_disk_sample(
            width=20.0, depth=15.0,
            min_radius=1.5,
            keep_out_zones=[],
            item_radius=0.3,
            count=15,
            seed=42,
        )
        for x, z in points:
            assert 0.3 <= x <= 19.7, f"x={x} out of bounds"
            assert 0.3 <= z <= 14.7, f"z={z} out of bounds"

    def test_minimum_spacing(self, engine):
        """No two points are closer than min_radius to each other."""
        points = engine._poisson_disk_sample(
            width=30.0, depth=30.0,
            min_radius=3.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=8,
            seed=99,
        )
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                x1, z1 = points[i]
                x2, z2 = points[j]
                dist = math.sqrt((x1 - x2) ** 2 + (z1 - z2) ** 2)
                assert dist >= 2.99, (  # tiny tolerance
                    f"points {i} and {j} too close: {dist:.3f}"
                )

    def test_zero_count_returns_empty(self, engine):
        """count=0 → empty list."""
        points = engine._poisson_disk_sample(
            width=10.0, depth=10.0,
            min_radius=1.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=0,
            seed=42,
        )
        assert points == []

    def test_negative_count_returns_empty(self, engine):
        """count<0 → empty list."""
        points = engine._poisson_disk_sample(
            width=10.0, depth=10.0,
            min_radius=1.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=-5,
            seed=42,
        )
        assert points == []

    def test_single_point(self, engine):
        """A single point is always placed (if region ≥ item_radius×2)."""
        points = engine._poisson_disk_sample(
            width=5.0, depth=5.0,
            min_radius=1.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=1,
            seed=42,
        )
        assert len(points) == 1


# ── Seed determinism ─────────────────────────────────────────────

class TestSeedDeterminism:
    """Same seed, same region → same positions every time."""

    def test_same_seed_same_positions(self, engine):
        """Identical inputs with same seed produce identical outputs."""
        kwargs = dict(
            width=20.0, depth=20.0,
            min_radius=2.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=5,
            seed=12345,
        )
        a = engine._poisson_disk_sample(**kwargs)
        b = engine._poisson_disk_sample(**kwargs)
        assert a == b

    def test_different_seed_different_positions(self, engine):
        """Different seeds produce different first positions."""
        kwargs_base = dict(
            width=20.0, depth=20.0,
            min_radius=2.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=5,
        )
        a = engine._poisson_disk_sample(**kwargs_base, seed=100)
        b = engine._poisson_disk_sample(**kwargs_base, seed=200)
        # The first seed point should be different (different RNG stream)
        assert a[0] != b[0], (
            f"Different seeds produced same first point: {a[0]}"
        )

    def test_compile_garden_seed_determinism(self, engine_with_lexicon):
        """Two compile_garden calls with same seed produce identical ops."""
        garden = {
            "region": {"width": 20.0, "depth": 20.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 3, "min_spacing": 4.0},
            ],
        }
        plan1 = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)
        plan2 = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        names1 = [s.name for s in plan1.steps if getattr(s, "step_type", "") == "create_entity"]
        names2 = [s.name for s in plan2.steps if getattr(s, "step_type", "") == "create_entity"]
        assert names1 == names2

        pos1 = [
            s.value for s in plan1.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        pos2 = [
            s.value for s in plan2.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        assert pos1 == pos2


# ── Keep-out zone tests ──────────────────────────────────────────

class TestKeepOutZones:
    """Items must not fall inside keep-out zones (with item_radius margin)."""

    def test_no_points_in_keep_out(self, engine):
        """A keep-out zone covering most of the region leaves only the edges."""
        ko = KeepOutZone(x=4.0, z=4.0, w=12.0, d=12.0)
        points = engine._poisson_disk_sample(
            width=20.0, depth=20.0,
            min_radius=1.0,
            keep_out_zones=[ko],
            item_radius=0.3,
            count=10,
            seed=42,
        )
        # Every point must be outside the keep-out (with margin)
        for x, z in points:
            ok_x = 4.0 - 0.3
            ok_z = 4.0 - 0.3
            ok_w = 12.0 + 0.6
            ok_d = 12.0 + 0.6
            in_ko = ok_x <= x <= ok_x + ok_w and ok_z <= z <= ok_z + ok_d
            assert not in_ko, f"Point ({x:.1f}, {z:.1f}) in keep-out zone"

    def test_full_keep_out_produces_zero_points(self, engine):
        """When keep-out zones cover the entire region → 0 points."""
        ko = KeepOutZone(x=0.0, z=0.0, w=10.0, d=10.0)
        points = engine._poisson_disk_sample(
            width=10.0, depth=10.0,
            min_radius=1.0,
            keep_out_zones=[ko],
            item_radius=0.5,
            count=5,
            seed=42,
        )
        # The keep-out with margin covers everything → no valid points
        assert len(points) == 0

    def test_multiple_keep_out_zones(self, engine):
        """Three disjoint keep-out zones are all respected."""
        zones = [
            KeepOutZone(x=1.0, z=1.0, w=3.0, d=3.0),
            KeepOutZone(x=7.0, z=1.0, w=3.0, d=3.0),
            KeepOutZone(x=4.0, z=7.0, w=3.0, d=3.0),
        ]
        points = engine._poisson_disk_sample(
            width=12.0, depth=12.0,
            min_radius=0.5,
            keep_out_zones=zones,
            item_radius=0.2,
            count=20,
            seed=42,
        )
        for x, z in points:
            for ko in zones:
                ok_x = ko.x - 0.2
                ok_z = ko.z - 0.2
                ok_w = ko.w + 0.4
                ok_d = ko.d + 0.4
                in_ko = ok_x <= x <= ok_x + ok_w and ok_z <= z <= ok_z + ok_d
                assert not in_ko, (
                    f"Point ({x:.1f}, {z:.1f}) in keep-out at "
                    f"({ko.x},{ko.z} {ko.w}×{ko.d})"
                )


# ── Jittered grid fallback tests ─────────────────────────────────

class TestJitteredGrid:
    """Jittered-grid sampler: direct call and fallback behaviour."""

    def test_direct_jittered_grid(self, engine):
        """Direct jittered-grid call produces the right count."""
        import random
        points = engine._jittered_grid_sample(
            width=20.0, depth=20.0,
            spacing=2.0,
            keep_out_zones=[],
            item_radius=0.5,
            count=10,
            rng=random.Random(42),
        )
        assert len(points) == 10

    def test_jittered_grid_points_in_bounds(self, engine):
        """All jittered grid points are within the region (minus margin)."""
        import random
        points = engine._jittered_grid_sample(
            width=15.0, depth=10.0,
            spacing=1.5,
            keep_out_zones=[],
            item_radius=0.4,
            count=20,
            rng=random.Random(99),
        )
        for x, z in points:
            assert 0.4 <= x <= 14.6, f"x={x} out of bounds"
            assert 0.4 <= z <= 9.6, f"z={z} out of bounds"

    def test_jittered_grid_respects_keep_out(self, engine):
        """Jittered grid skips cells inside keep-out zones."""
        import random
        ko = KeepOutZone(x=5.0, z=5.0, w=5.0, d=5.0)
        points = engine._jittered_grid_sample(
            width=15.0, depth=15.0,
            spacing=1.0,
            keep_out_zones=[ko],
            item_radius=0.3,
            count=30,
            rng=random.Random(42),
        )
        for x, z in points:
            ok_x = 5.0 - 0.3
            ok_z = 5.0 - 0.3
            ok_w = 5.0 + 0.6
            ok_d = 5.0 + 0.6
            in_ko = ok_x <= x <= ok_x + ok_w and ok_z <= z <= ok_z + ok_d
            assert not in_ko, f"Point ({x:.1f}, {z:.1f}) in keep-out"

    def test_jittered_grid_existing_positions_filter(self, engine):
        """Points too close to existing positions are rejected."""
        import random
        existing = {(5.0, 5.0), (5.5, 5.5)}
        points = engine._jittered_grid_sample(
            width=10.0, depth=10.0,
            spacing=2.0,
            keep_out_zones=[],
            item_radius=0.3,
            count=5,
            rng=random.Random(42),
            existing_positions=existing,
        )
        for x, z in points:
            for ex, ez in existing:
                dist = math.sqrt((x - ex) ** 2 + (z - ez) ** 2)
                assert dist >= 1.99, (
                    f"Point ({x:.1f},{z:.1f}) too close to existing ({ex},{ez}): {dist:.2f}"
                )

    def test_poisson_falls_back_to_jittered(self, engine):
        """When Poisson-disk can't fill a dense request, jittered grid fills in."""
        # Tight region + high count + very low attempts → Poisson retires fast
        points = engine._poisson_disk_sample(
            width=10.0, depth=10.0,
            min_radius=0.6,
            keep_out_zones=[],
            item_radius=0.1,
            count=30,
            max_attempts=2,    # extremely low → Poisson retires immediately
            seed=42,
        )
        # With max_attempts=2, Poisson will place only a handful of points
        # before all active points retire. Jittered grid fills the rest.
        assert len(points) == 30


# ── compile_garden tests ─────────────────────────────────────────

class TestCompileGarden:
    """Full pipeline: garden JSON → DevForgePlan with proper steps."""

    def test_compile_single_species(self, engine_with_lexicon):
        """5 trees → 5 create steps + position + mesh + material for each."""
        garden = {
            "region": {"width": 30.0, "depth": 30.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 5, "min_spacing": 4.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        create_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        assert len(create_steps) == 5
        for i, cs in enumerate(create_steps):
            assert cs.name == f"tree_{i+1}"
            assert cs.node_type == "MeshInstance3D"
            assert cs.parent == "/root/Main"

        # Each tree gets position, mesh, material = 3 set_property steps
        set_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
        ]
        assert len(set_steps) == 15  # 5 * 3

    def test_compile_multi_species(self, engine_with_lexicon):
        """Trees + bushes → correct node counts per species."""
        garden = {
            "region": {"width": 25.0, "depth": 25.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 3, "min_spacing": 5.0},
                {"id": "bush", "count": 6, "min_spacing": 2.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        create_names = [
            s.name for s in plan.steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        tree_count = sum(1 for n in create_names if n.startswith("tree_"))
        bush_count = sum(1 for n in create_names if n.startswith("bush_"))
        assert tree_count == 3
        assert bush_count == 6

    def test_compile_empty_species_list(self, engine):
        """No species → empty plan."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [],
        }
        plan = engine.compile_garden(garden, root_path="/root/Main")
        assert plan.steps == []

    def test_compile_tree_mesh_is_cylinder(self, engine_with_lexicon):
        """Trees should get CylinderMesh with correct dimensions."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 1, "min_spacing": 4.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        mesh_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "mesh"
        ]
        assert len(mesh_steps) == 1
        m = mesh_steps[0].value
        assert m["__class__"] == "CylinderMesh"
        assert "top_radius" in m
        assert "bottom_radius" in m
        assert "height" in m

    def test_compile_bush_mesh_is_sphere(self, engine_with_lexicon):
        """Bushes should get SphereMesh."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "bush", "count": 1, "min_spacing": 2.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        mesh_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "mesh"
        ]
        assert len(mesh_steps) == 1
        m = mesh_steps[0].value
        assert m["__class__"] == "SphereMesh"
        assert "radius" in m

    def test_compile_with_keep_out(self, engine_with_lexicon):
        """Keep-out zone in garden JSON is passed to sampler — trees avoid it."""
        garden = {
            "region": {"width": 20.0, "depth": 20.0},
            "keep_out": [
                {"x": 4.0, "z": 4.0, "w": 12.0, "d": 12.0},
            ],
            "species": [
                {"id": "tree", "count": 8, "min_spacing": 2.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        # Extract all tree positions
        positions = [
            s.value for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
            and "tree_" in getattr(s, "node", "")
        ]
        assert len(positions) == 8

        # Tree footprint radius from lexicon = max(1.2/2, 1.2/2) = 0.6
        for p in positions:
            x, z = p["x"], p["z"]
            ok_x = 4.0 - 0.6
            ok_z = 4.0 - 0.6
            ok_w = 12.0 + 1.2
            ok_d = 12.0 + 1.2
            in_ko = ok_x <= x <= ok_x + ok_w and ok_z <= z <= ok_z + ok_d
            assert not in_ko, (
                f"Tree at ({x:.1f}, {z:.1f}) in keep-out zone"
            )

    def test_compile_goal_string(self, engine):
        """Plan goal includes the total item count."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 2, "min_spacing": 3.0},
            ],
        }
        plan = engine.compile_garden(garden, root_path="/root/Main", seed=42)
        assert "2 items" in plan.goal

    def test_compile_y_position_is_half_height(self, engine_with_lexicon):
        """Tree y position = height/2 (tree sits on ground)."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 1, "min_spacing": 4.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        pos_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        p = pos_steps[0].value
        # tree height = 3.0, so y = 1.5
        assert p["y"] == pytest.approx(1.5, abs=0.01)

    def test_compile_material_has_color(self, engine_with_lexicon):
        """All placed items get a material_override with color."""
        garden = {
            "region": {"width": 10.0, "depth": 10.0},
            "keep_out": [],
            "species": [
                {"id": "tree", "count": 1, "min_spacing": 3.0},
            ],
        }
        plan = engine_with_lexicon.compile_garden(garden, root_path="/root/Main", seed=42)

        mat_steps = [
            s for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "material_override"
        ]
        assert len(mat_steps) == 1
        c = mat_steps[0].value["albedo_color"]
        # Tree color from lexicon: [0.15, 0.55, 0.15]
        assert c["r"] == pytest.approx(0.15)
        assert c["g"] == pytest.approx(0.55)
        assert c["b"] == pytest.approx(0.15)


# ── Dataclass tests ──────────────────────────────────────────────

class TestDataClasses:
    """Dataclass constructors and defaults."""

    def test_keep_out_zone_creation(self):
        ko = KeepOutZone(x=1.0, z=2.0, w=3.0, d=4.0)
        assert ko.x == 1.0
        assert ko.z == 2.0
        assert ko.w == 3.0
        assert ko.d == 4.0

    def test_species_spec_creation(self):
        sp = SpeciesSpec(asset_id="tree", count=5, min_spacing=3.0)
        assert sp.asset_id == "tree"
        assert sp.count == 5
        assert sp.min_spacing == 3.0

    def test_scatter_region_defaults(self):
        region = ScatterRegion(width=20.0, depth=15.0)
        assert region.width == 20.0
        assert region.depth == 15.0
        assert region.keep_out == []

    def test_scatter_region_with_keep_out(self):
        ko = KeepOutZone(1, 2, 3, 4)
        region = ScatterRegion(width=10.0, depth=10.0, keep_out=[ko])
        assert len(region.keep_out) == 1


# ── Import tests ─────────────────────────────────────────────────

class TestScatterImports:
    def test_imports_available(self):
        from devforge.spatial.scatter import (
            ScatterEngine, KeepOutZone, SpeciesSpec, ScatterRegion,
        )
        assert ScatterEngine is not None
        assert KeepOutZone is not None
        assert SpeciesSpec is not None
        assert ScatterRegion is not None

    def test_engine_creatable_without_lexicon(self):
        engine = ScatterEngine(lexicon=None)
        assert engine._lexicon is None
