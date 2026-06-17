"""Tests for BSP Multi-Room Building Partition Engine.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_bsp.py -v
"""

from __future__ import annotations

import pytest

from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.compiler import SpatialCompiler
from devforge.spatial.bsp import (
    BSPPartitioner,
    RoomRect,
    _WallSpec,
    _DOOR_GAP,
    _WALL_HEIGHT,
    _WALL_THICKNESS,
    _FLOOR_THICKNESS,
    _MIN_RATIO,
    _MAX_RATIO,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def lexicon():
    return AssetLexicon()


@pytest.fixture
def compiler(lexicon):
    return SpatialCompiler(lexicon)


@pytest.fixture
def bsp_no_compiler():
    """BSP partitioner without a room compiler — rooms are empty leaf rects."""
    return BSPPartitioner(room_compiler=None)


@pytest.fixture
def bsp_with_compiler(compiler):
    """Full BSP partitioner with SpatialCompiler for per-room furniture."""
    return BSPPartitioner(room_compiler=compiler)


# ── Partition math tests ─────────────────────────────────────────

class TestPartition:
    """Pure partition arithmetic — no compiler, no ops, just rects."""

    def test_two_room_x_split(self, bsp_no_compiler):
        """12×8 footprint split along X at 0.5 → two 6×8 rooms."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left":  {"room": "living", "pattern": "rectangle_room"},
            "right": {"room": "kitchen", "pattern": "rectangle_room"},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (12.0, 8.0))

        assert len(leaves) == 2
        assert leaves[0].room_name == "living"
        assert leaves[0].origin == (0.0, 0.0)
        assert leaves[0].size == (6.0, 8.0)

        assert leaves[1].room_name == "kitchen"
        assert leaves[1].origin == (6.0, 0.0)
        assert leaves[1].size == (6.0, 8.0)

    def test_z_split(self, bsp_no_compiler):
        """10×10 footprint split along Z at 0.4 → two rooms stacked front/back."""
        tree = {
            "axis": "z", "ratio": 0.4,
            "left":  {"room": "front", "pattern": "rectangle_room"},
            "right": {"room": "back", "pattern": "rectangle_room"},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0))

        assert len(leaves) == 2
        assert leaves[0].origin == (0.0, 0.0)
        assert leaves[0].size == (10.0, 4.0)
        assert leaves[1].origin == (0.0, 4.0)
        assert leaves[1].size == (10.0, 6.0)

    def test_four_room_grid(self, bsp_no_compiler):
        """10×10 X-split then Z-splits → 2×2 grid of 5×5 rooms."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "bedroom", "pattern": "rectangle_room"},
                "right": {"room": "bathroom", "pattern": "rectangle_room"},
            },
            "right": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "kitchen", "pattern": "rectangle_room"},
                "right": {"room": "living", "pattern": "rectangle_room"},
            },
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0))

        assert len(leaves) == 4
        # bedroom: origin (0, 0), size (5, 5)
        assert leaves[0].origin == (0.0, 0.0)
        assert leaves[0].size == (5.0, 5.0)
        # bathroom: origin (0, 5), size (5, 5)
        assert leaves[1].origin == (0.0, 5.0)
        assert leaves[1].size == (5.0, 5.0)
        # kitchen: origin (5, 0), size (5, 5)
        assert leaves[2].origin == (5.0, 0.0)
        assert leaves[2].size == (5.0, 5.0)
        # living: origin (5, 5), size (5, 5)
        assert leaves[3].origin == (5.0, 5.0)
        assert leaves[3].size == (5.0, 5.0)

    def test_single_leaf(self, bsp_no_compiler):
        """Tree with just a room → one leaf."""
        tree = {"room": "studio", "pattern": "rectangle_room"}
        leaves = bsp_no_compiler._partition(tree, (3.0, 4.0), (5.0, 6.0))
        assert len(leaves) == 1
        assert leaves[0].origin == (3.0, 4.0)
        assert leaves[0].size == (5.0, 6.0)

    def test_empty_tree(self, bsp_no_compiler):
        """Empty tree → 0 leaves."""
        assert bsp_no_compiler._partition({}, (0, 0), (10, 10)) == []
        assert bsp_no_compiler._partition(None, (0, 0), (10, 10)) == []

    def test_malformed_node_no_room_no_axis(self, bsp_no_compiler):
        """Node with neither 'room' nor 'axis' → 0 leaves, no crash."""
        leaves = bsp_no_compiler._partition({"foo": "bar"}, (0, 0), (10, 10))
        assert leaves == []

    def test_no_overlap(self, bsp_no_compiler):
        """All leaf rects in a 4-room grid must not AABB-overlap."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "A", "pattern": "r"},
                "right": {"room": "B", "pattern": "r"},
            },
            "right": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "C", "pattern": "r"},
                "right": {"room": "D", "pattern": "r"},
            },
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (6.0, 6.0))

        for i, a in enumerate(leaves):
            for j, b in enumerate(leaves):
                if i >= j:
                    continue
                ax1, az1 = a.origin[0], a.origin[1]
                ax2, az2 = ax1 + a.size[0], az1 + a.size[1]
                bx1, bz1 = b.origin[0], b.origin[1]
                bx2, bz2 = bx1 + b.size[0], bz1 + b.size[1]
                ox = ax1 < bx2 and ax2 > bx1
                oz = az1 < bz2 and az2 > bz1
                assert not (ox and oz), (
                    f"{a.room_name} overlaps {b.room_name}"
                )

    def test_deep_tree_eight_rooms(self, bsp_no_compiler):
        """Depth-3 tree → 8 leaf rooms (16×16 → 2×2 grid of 8×8 rooms)."""
        def leaf(name):
            return {"room": name, "pattern": "rectangle_room"}

        tree = {
            "axis": "x", "ratio": 0.5,
            "left": {
                "axis": "x", "ratio": 0.5,
                "left": {
                    "axis": "z", "ratio": 0.5,
                    "left": leaf("A"), "right": leaf("B"),
                },
                "right": {
                    "axis": "z", "ratio": 0.5,
                    "left": leaf("C"), "right": leaf("D"),
                },
            },
            "right": {
                "axis": "x", "ratio": 0.5,
                "left": {
                    "axis": "z", "ratio": 0.5,
                    "left": leaf("E"), "right": leaf("F"),
                },
                "right": {
                    "axis": "z", "ratio": 0.5,
                    "left": leaf("G"), "right": leaf("H"),
                },
            },
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (16.0, 16.0))
        assert len(leaves) == 8
        # All rooms are 4×8 (three splits: x→x→z on a 16×16)
        for leaf in leaves:
            assert leaf.size == (4.0, 8.0), (
                f"{leaf.room_name}: expected (4, 8), got {leaf.size}"
            )

    def test_slot_fills_preserved(self, bsp_no_compiler):
        """Leaf slot_fills dict is passed through unchanged."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left": {"room": "kitchen", "pattern": "rectangle_room",
                     "slot_fills": {"north_counter_center": "stove"}},
            "right": {"room": "living", "pattern": "rectangle_room",
                      "slot_fills": {"center_table": "table"}},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10, 10))
        assert leaves[0].slot_fills == {"north_counter_center": "stove"}
        assert leaves[1].slot_fills == {"center_table": "table"}


# ── Wall spec tests ───────────────────────────────────────────────

class TestWallSpecs:
    """Verifies wall specs generated during partition traversal."""

    def test_x_split_produces_z_wall(self, bsp_no_compiler):
        """An X-split at 6.0 on a 12×8 region → wall along Z at x=6."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left":  {"room": "left", "pattern": "r"},
            "right": {"room": "right", "pattern": "r"},
        }
        walls = []
        bsp_no_compiler._partition(tree, (0, 0), (12.0, 8.0), walls=walls)

        assert len(walls) == 1
        assert walls[0].axis == "z"
        assert walls[0].wall_x == 6.0
        assert walls[0].wall_z == 0.0
        assert walls[0].span_start == 0.0
        assert walls[0].span_end == 8.0

    def test_z_split_produces_x_wall(self, bsp_no_compiler):
        """A Z-split at 4.0 on a 10×10 region → wall along X at z=4."""
        tree = {
            "axis": "z", "ratio": 0.4,
            "left":  {"room": "front", "pattern": "r"},
            "right": {"room": "back", "pattern": "r"},
        }
        walls = []
        bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0), walls=walls)

        assert len(walls) == 1
        assert walls[0].axis == "x"
        assert walls[0].wall_x == 0.0
        assert walls[0].wall_z == 4.0
        assert walls[0].span_start == 0.0
        assert walls[0].span_end == 10.0

    def test_grid_produces_three_walls(self, bsp_no_compiler):
        """A 2×2 grid (X then two Z splits) → 3 wall specs."""
        tree = {
            "axis": "x", "ratio": 0.5,
            "left": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "A", "pattern": "r"},
                "right": {"room": "B", "pattern": "r"},
            },
            "right": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "C", "pattern": "r"},
                "right": {"room": "D", "pattern": "r"},
            },
        }
        walls = []
        bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0), walls=walls)
        assert len(walls) == 3

    def test_single_leaf_produces_no_walls(self, bsp_no_compiler):
        """A leaf-only tree produces 0 wall specs."""
        walls = []
        bsp_no_compiler._partition(
            {"room": "solo", "pattern": "r"}, (0, 0), (5, 5), walls=walls,
        )
        assert walls == []


# ── Wall generation tests ────────────────────────────────────────

class TestPartitionWalls:
    """Tests _build_partition_walls — wall segments, door gaps, dimensions."""

    def test_wall_produces_two_segments(self, bsp_no_compiler):
        """A 10m wall → 2 segments (above and below the 1.2m door gap)."""
        w = _WallSpec(
            axis="z", wall_x=5.0, wall_z=0.0,
            span_start=0.0, span_end=10.0,
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")

        # 2 segments → 2 create + 6 set_property (position, mesh, material each)
        create_steps = [s for s in steps
                        if getattr(s, "step_type", "") == "create_entity"]
        assert len(create_steps) == 2, (
            f"Expected 2 wall segments, got {len(create_steps)}"
        )
        assert create_steps[0].name == "Wall_1"
        assert create_steps[1].name == "Wall_2"

    def test_wall_segments_dont_overlap_door(self, bsp_no_compiler):
        """The gap between two wall segments in the actual steps equals the door gap."""
        w = _WallSpec(
            axis="z", wall_x=3.0, wall_z=0.0,
            span_start=0.0, span_end=10.0,
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")

        # Extract positions from actual wall segments
        pos_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        assert len(pos_steps) == 2
        # For a Z-axis wall, the segment centre is along Z
        pos_z = sorted([p.value["z"] for p in pos_steps])
        # seg1 centre ≈ 2.2 (span 0→4.4), seg2 centre ≈ 7.8 (span 5.6→10)
        # Half-lengths: seg1 half = 4.4/2 = 2.2, seg2 half = 4.4/2 = 2.2
        # seg1 end = 2.2 + 2.2 = 4.4, seg2 start = 7.8 - 2.2 = 5.6
        # Gap = 5.6 - 4.4 = 1.2
        gap_centre = (10.0 / 2)
        seg1_half = (gap_centre - _DOOR_GAP / 2) / 2  # 2.2
        seg2_half = (10.0 - gap_centre - _DOOR_GAP / 2) / 2  # 2.2
        seg1_end = pos_z[0] + seg1_half
        seg2_start = pos_z[1] - seg2_half
        assert seg2_start - seg1_end == pytest.approx(_DOOR_GAP, abs=0.01)

    def test_short_wall_skips_tiny_segments(self, bsp_no_compiler):
        """A wall shorter than the door gap → 0 segments (both < 0.01m)."""
        w = _WallSpec(
            axis="z", wall_x=1.0, wall_z=0.0,
            span_start=0.0, span_end=1.0,  # only 1m long
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")
        create_steps = [s for s in steps
                        if getattr(s, "step_type", "") == "create_entity"]
        assert len(create_steps) == 0, (
            "Wall shorter than door gap should produce 0 segments"
        )

    def test_wall_mesh_dimensions_z_axis(self, bsp_no_compiler):
        """Z-axis wall: BoxMesh x=_WALL_THICKNESS, y=_WALL_HEIGHT, z=segment_length."""
        w = _WallSpec(
            axis="z", wall_x=4.0, wall_z=0.0,
            span_start=0.0, span_end=8.0,
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")

        mesh_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "mesh"
        ]
        assert len(mesh_steps) == 2
        # Segment lengths: seg1 = 4.0 - 0.6 = 3.4, seg2 = 8.0 - 4.6 = 3.4
        # Wait — centre is at 4.0, gap is 1.2, so seg1 = 4.0 - 0.6 = 3.4, seg2 = 8.0 - (4.0+0.6) = 3.4
        gap_centre = 4.0
        expected_len = (gap_centre - _DOOR_GAP / 2)  # length of segment 1
        for i, ms in enumerate(mesh_steps):
            size = ms.value["size"]
            assert size["x"] == _WALL_THICKNESS, (
                f"segment {i}: expected x={_WALL_THICKNESS}, got {size['x']}"
            )
            assert size["y"] == _WALL_HEIGHT
            assert size["z"] == pytest.approx(expected_len, abs=0.02)

    def test_wall_mesh_dimensions_x_axis(self, bsp_no_compiler):
        """X-axis wall: BoxMesh x=segment_length, y=_WALL_HEIGHT, z=_WALL_THICKNESS."""
        w = _WallSpec(
            axis="x", wall_x=0.0, wall_z=5.0,
            span_start=0.0, span_end=8.0,
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")

        mesh_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "mesh"
        ]
        gap_centre = 4.0
        expected_len = (gap_centre - _DOOR_GAP / 2)
        for i, ms in enumerate(mesh_steps):
            size = ms.value["size"]
            assert size["x"] == pytest.approx(expected_len, abs=0.02), (
                f"segment {i}: expected x≈{expected_len}, got {size['x']}"
            )
            assert size["y"] == _WALL_HEIGHT
            assert size["z"] == _WALL_THICKNESS

    def test_wall_has_material(self, bsp_no_compiler):
        """Every wall segment gets a material_override."""
        w = _WallSpec(
            axis="z", wall_x=2.0, wall_z=0.0,
            span_start=0.0, span_end=8.0,
        )
        steps = bsp_no_compiler._build_partition_walls([w], "/root/Main")
        mat_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "material_override"
        ]
        assert len(mat_steps) == 2
        for ms in mat_steps:
            c = ms.value["albedo_color"]
            assert c["r"] == 0.75  # wall material


# ── Floor slab tests ─────────────────────────────────────────────

class TestBuildingFloor:
    """Tests _building_floor — position, mesh, material."""

    def test_floor_creates_one_node(self, bsp_no_compiler):
        steps = bsp_no_compiler._building_floor((0, 0), (12.0, 8.0), "/root/Main")
        create_steps = [s for s in steps
                        if getattr(s, "step_type", "") == "create_entity"]
        assert len(create_steps) == 1
        assert create_steps[0].name == "BuildingFloor"
        assert create_steps[0].node_type == "MeshInstance3D"

    def test_floor_position_centered(self, bsp_no_compiler):
        """Floor is at centre of footprint (6, -0.1, 4) for 12×8 at origin."""
        steps = bsp_no_compiler._building_floor((0, 0), (12.0, 8.0), "/root/Main")
        pos_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        assert len(pos_steps) == 1
        p = pos_steps[0].value
        assert p["x"] == 6.0
        assert p["y"] == pytest.approx(-_FLOOR_THICKNESS / 2)
        assert p["z"] == 4.0

    def test_floor_mesh_is_plane(self, bsp_no_compiler):
        steps = bsp_no_compiler._building_floor((0, 0), (12.0, 8.0), "/root/Main")
        mesh_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "mesh"
        ]
        assert len(mesh_steps) == 1
        assert mesh_steps[0].value["__class__"] == "PlaneMesh"
        assert mesh_steps[0].value["size"] == {"x": 12.0, "y": 8.0}

    def test_floor_has_material(self, bsp_no_compiler):
        steps = bsp_no_compiler._building_floor((0, 0), (10.0, 6.0), "/root/Main")
        mat_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "material_override"
        ]
        assert len(mat_steps) == 1
        c = mat_steps[0].value["albedo_color"]
        assert c["r"] == 0.55  # floor material

    def test_floor_with_nonzero_origin(self, bsp_no_compiler):
        """Floor at origin (2, 3), size 6×4 → centre at (5, -0.1, 5)."""
        steps = bsp_no_compiler._building_floor((2.0, 3.0), (6.0, 4.0), "/root/Main")
        pos_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
        ]
        p = pos_steps[0].value
        assert p["x"] == 5.0  # 2 + 6/2
        assert p["z"] == 5.0  # 3 + 4/2


# ── Degenerate ratio tests ───────────────────────────────────────

class TestDegenerateRatios:
    """Clamping behaviour for ratios at 0.0 and 1.0."""

    def test_zero_ratio_clamped(self, bsp_no_compiler):
        """ratio 0.0 → clamped to _MIN_RATIO (0.1). Both rooms non-zero."""
        tree = {
            "axis": "x", "ratio": 0.0,
            "left":  {"room": "tiny", "pattern": "r"},
            "right": {"room": "big", "pattern": "r"},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0))
        assert leaves[0].size[0] == pytest.approx(10.0 * _MIN_RATIO)
        assert leaves[1].size[0] == pytest.approx(10.0 * (1 - _MIN_RATIO))
        # Both rooms have positive size
        assert leaves[0].size[0] > 0
        assert leaves[1].size[0] > 0

    def test_one_ratio_clamped(self, bsp_no_compiler):
        """ratio 1.0 → clamped to _MAX_RATIO (0.9). Both rooms non-zero."""
        tree = {
            "axis": "z", "ratio": 1.0,
            "left":  {"room": "big", "pattern": "r"},
            "right": {"room": "tiny", "pattern": "r"},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0))
        assert leaves[0].size[1] == pytest.approx(10.0 * _MAX_RATIO)
        assert leaves[1].size[1] == pytest.approx(10.0 * (1 - _MAX_RATIO))
        assert leaves[0].size[1] > 0
        assert leaves[1].size[1] > 0

    def test_valid_ratio_unchanged(self, bsp_no_compiler):
        """A normal ratio (0.3) is not clamped."""
        tree = {
            "axis": "x", "ratio": 0.3,
            "left":  {"room": "left", "pattern": "r"},
            "right": {"room": "right", "pattern": "r"},
        }
        leaves = bsp_no_compiler._partition(tree, (0, 0), (10.0, 10.0))
        assert leaves[0].size[0] == pytest.approx(3.0)
        assert leaves[1].size[0] == pytest.approx(7.0)


# ── Compile_building integration tests ───────────────────────────

class TestCompileBuilding:
    """End-to-end compile_building tests with a real SpatialCompiler."""

    def test_compile_two_room_house(self, bsp_with_compiler):
        """Build a 2-room house → floor + 2 room plans + walls."""
        building_json = {
            "building": "TestHouse",
            "footprint": {"width": 10.0, "depth": 8.0},
            "tree": {
                "axis": "x", "ratio": 0.5,
                "left": {
                    "room": "living", "pattern": "rectangle_room",
                    "slot_fills": {"center_table": "table"},
                },
                "right": {
                    "room": "kitchen", "pattern": "rectangle_room",
                    "slot_fills": {"north_counter_center": "stove"},
                },
            },
        }
        plan = bsp_with_compiler.compile_building(building_json, "/root/Main")

        assert plan.goal == "BSP building: TestHouse (2 rooms)"
        steps = plan.steps
        assert len(steps) > 0

        # Should have a floor
        create_names = [
            s.name for s in steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        assert "BuildingFloor" in create_names

        # Should have wall segments (exactly 2 for one split boundary)
        wall_names = [n for n in create_names if n.startswith("Wall_")]
        assert len(wall_names) == 2, (
            f"Expected 2 wall segments, got {len(wall_names)}: {wall_names}"
        )

        # Should have furniture from both rooms. Room containers
        # ("living", "kitchen") are Node3D parents, not furniture.
        furniture_names = [
            n for n in create_names
            if n not in ("BuildingFloor", "Floor", "Ceiling", "living", "kitchen")
            and not n.startswith("Wall_")
        ]
        assert len(furniture_names) >= 2, (
            f"Expected >=2 furniture nodes, got {len(furniture_names)}: {furniture_names}"
        )

    def test_compile_no_rooms_produces_empty_plan(self, bsp_no_compiler):
        """Empty tree → 0 rooms → empty plan with warning."""
        building_json = {
            "building": "Empty",
            "footprint": {"width": 5.0, "depth": 5.0},
            "tree": {},
        }
        plan = bsp_no_compiler.compile_building(building_json, "/root/Main")
        assert plan.steps == []

    def test_compile_without_compiler_produces_floor_and_walls_only(self, bsp_no_compiler):
        """Without a room compiler, rooms are empty but floor + walls still emit."""
        building_json = {
            "building": "Skeleton",
            "footprint": {"width": 8.0, "depth": 8.0},
            "tree": {
                "axis": "x", "ratio": 0.5,
                "left":  {"room": "A", "pattern": "rectangle_room"},
                "right": {"room": "B", "pattern": "rectangle_room"},
            },
        }
        plan = bsp_no_compiler.compile_building(building_json, "/root/Main")

        create_names = [
            s.name for s in plan.steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        # Floor + room containers + walls (no furniture since no compiler).
        # Room A, B are Node3D containers created by compile_building.
        assert "BuildingFloor" in create_names
        assert "A" in create_names  # room container
        assert "B" in create_names
        wall_names = [n for n in create_names if n.startswith("Wall_")]
        assert len(wall_names) == 2

    def test_origin_offset_propagation(self, bsp_with_compiler, compiler):
        """Furniture placed at an origin offset is offset by exactly that amount.

        Compile the same room layout at origin (0,0) and (5,0) directly
        via compile_layout with shell=False, then compare table positions.
        """
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 4, "height": 3, "depth": 4},
            "slot_fills": {"center_table": "table"},
            "arcs_overrides": [],
        }

        def table_pos(plan):
            for s in plan.steps:
                if (getattr(s, "step_type", "") == "set_property"
                        and getattr(s, "property", "") == "position"
                        and s.node.endswith("table_center_table")):
                    return s.value
            return None

        base = compiler.compile_layout(layout, shell=False)
        off = compiler.compile_layout(layout, origin=(5.0, 0.0), shell=False)
        bp, op = table_pos(base), table_pos(off)

        assert bp is not None and op is not None, "table not placed"
        # X offset should be exactly 5.0
        assert op["x"] == pytest.approx(bp["x"] + 5.0), (
            f"base x={bp['x']}, offset x={op['x']}, diff={op['x'] - bp['x']}"
        )
        # Z should be the same (no Z offset)
        assert op["z"] == pytest.approx(bp["z"])
        # shell=False means no Floor/Ceiling nodes
        off_names = [
            s.name for s in off.steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        assert "Floor" not in off_names
        assert "Ceiling" not in off_names

        # Also verify through BSP: 2-room house, right room at origin (5,0)
        building_json = {
            "building": "OffsetTest",
            "footprint": {"width": 10.0, "depth": 6.0},
            "tree": {
                "axis": "x", "ratio": 0.5,
                "left": {
                    "room": "left", "pattern": "rectangle_room",
                    "slot_fills": {"center_table": "table"},
                },
                "right": {
                    "room": "right", "pattern": "rectangle_room",
                    "slot_fills": {"center_table": "table"},
                },
            },
        }
        plan = bsp_with_compiler.compile_building(building_json, "/root/Main")
        assert len(plan.steps) > 0
        # With room containers, each room's furniture is namespaced —
        # both tables should exist (no collision).
        create_names = [
            s.name for s in plan.steps
            if getattr(s, "step_type", "") == "create_entity"
        ]
        table_count = sum(1 for n in create_names if "table" in n)
        assert table_count >= 2, (
            f"Expected >=2 tables (one per room), got {table_count}: {create_names}"
        )

    def test_plan_validates_clean(self, bsp_with_compiler):
        """A fully compiled 2-room building plan should validate without errors."""
        building_json = {
            "building": "ValidHouse",
            "footprint": {"width": 8.0, "depth": 6.0},
            "tree": {
                "axis": "z", "ratio": 0.5,
                "left":  {"room": "front", "pattern": "rectangle_room",
                          "slot_fills": {"center_table": "table"}},
                "right": {"room": "back", "pattern": "rectangle_room",
                          "slot_fills": {"center_table": "table"}},
            },
        }
        plan = bsp_with_compiler.compile_building(building_json, "/root/Main")
        errors = plan.validate()
        assert len(errors) == 0, f"Validation errors: {errors}"


# ── Import / structure tests ─────────────────────────────────────

class TestBSPImports:
    def test_imports_available(self):
        from devforge.spatial.bsp import BSPPartitioner, RoomRect, _WallSpec
        assert BSPPartitioner is not None
        assert RoomRect is not None
        assert _WallSpec is not None

    def test_room_rect_is_dataclass(self):
        r = RoomRect(
            origin=(1.0, 2.0), size=(3.0, 4.0),
            pattern="rectangle_room", room_name="test",
        )
        assert r.origin == (1.0, 2.0)
        assert r.size == (3.0, 4.0)
        assert r.room_name == "test"
        assert r.slot_fills == {}
