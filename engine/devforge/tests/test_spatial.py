"""Tests for the spatial layout engine — anchors, lexicon, compiler.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_spatial.py -v
"""

from __future__ import annotations

import pytest

from devforge.spatial.anchors import AnchorResolver
from devforge.spatial.compiler import SpatialCompiler
from devforge.spatial.lexicon import AssetLexicon, SlotViolation

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def lexicon():
    """Create an AssetLexicon from the built-in greybox lexicon."""
    return AssetLexicon()


@pytest.fixture
def resolver():
    """Create an AnchorResolver with test dimensions."""
    anchors = {
        "center": {"position": ["$width/2", 0, "$depth/2"]},
        "north_wall": {"position": ["$width/2", 1.5, 0]},
        "nw_corner": {"position": [0.6, 0, 0.6]},
    }
    dims = {"width": 6.0, "depth": 5.0, "height": 3.0}
    return AnchorResolver(anchors, dims)


@pytest.fixture
def compiler(lexicon):
    """Create a SpatialCompiler with the greybox lexicon."""
    return SpatialCompiler(lexicon)


# ── Lexicon tests ─────────────────────────────────────────────────


class TestAssetLexicon:
    def test_loads_eight_assets(self, lexicon):
        assert len(lexicon.asset_ids) >= 8

    def test_get_known_asset(self, lexicon):
        entry = lexicon.get("fridge")
        assert entry is not None
        assert entry["category"][0] == "kitchen"
        assert entry["footprint"]["width"] == 0.9

    def test_get_missing_returns_none(self, lexicon):
        assert lexicon.get("spaceship") is None

    def test_require_missing_raises(self, lexicon):
        with pytest.raises(SlotViolation, match="not found"):
            lexicon.require("ghost_asset")

    def test_footprint(self, lexicon):
        fp = lexicon.footprint("chair")
        assert fp == {"width": 0.5, "depth": 0.5}

    def test_height(self, lexicon):
        assert lexicon.height("fridge") == 1.8

    def test_fits_slot(self, lexicon):
        assert lexicon.fits_slot("chair", {"width": 1.0, "depth": 1.0})
        assert not lexicon.fits_slot("fridge", {"width": 0.3, "depth": 0.3})

    def test_by_category(self, lexicon):
        appliances = lexicon.by_category("appliance")
        assert "fridge" in appliances
        assert "stove" in appliances

    def test_summary_for_prompt(self, lexicon):
        summary = lexicon.summary_for_prompt()
        assert "fridge" in summary
        assert "stove" in summary

    def test_greybox_ops_structure(self, lexicon):
        ops = lexicon.greybox_ops(
            "counter",
            "/root/Main",
            "counter_north_counter_center",
            {"x": 1.5, "y": 0, "z": 0.3},
        )
        types = [o["type"] for o in ops]
        assert types == ["add_node", "set_property", "set_property", "set_property"]
        assert ops[0]["name"] == "counter_north_counter_center"
        assert ops[0]["node_type"] == "MeshInstance3D"
        # position should include half-height offset
        pos_op = ops[2]
        assert pos_op["property"] == "position"
        # counter height=0.9, so y = 0 + 0.45
        assert pos_op["value"]["y"] == 0.45


# ── Anchor tests ──────────────────────────────────────────────────


class TestAnchorResolver:
    def test_resolve_center(self, resolver):
        pos = resolver.resolve("center")
        assert pos == {"x": 3.0, "y": 0, "z": 2.5}

    def test_resolve_north_wall(self, resolver):
        pos = resolver.resolve("north_wall")
        assert pos == {"x": 3.0, "y": 1.5, "z": 0}

    def test_resolve_caches(self, resolver):
        pos1 = resolver.resolve("center")
        pos2 = resolver.resolve("center")
        assert pos1 is pos2  # same object reference

    def test_resolve_missing_raises(self, resolver):
        with pytest.raises(ValueError, match="not found"):
            resolver.resolve("saturn")

    def test_chain_resolution(self, resolver):
        # Register a placed object
        resolver.register_placed("table", {"x": 3.0, "y": 0, "z": 2.5}, {"half_width": 0.75, "half_depth": 0.5})
        # Chain north from table
        pos = resolver.resolve_chain(
            ["table", "north", 1.2],
            {"table": {"half_width": 0.75, "half_depth": 0.5}},
        )
        # table.z=2.5, table half_depth=0.5, gap=1.2, north = -z
        # so: 2.5 - 0.5 - 1.2 = 0.8
        assert pos["x"] == 3.0
        assert pos["z"] == pytest.approx(0.8)

    def test_chain_missing_object(self, resolver):
        with pytest.raises(ValueError, match="not a placed object"):
            resolver.resolve_chain(["ghost", "north", 1.0])

    def test_chain_bad_direction(self, resolver):
        resolver.register_placed("table", {"x": 0, "y": 0, "z": 0})
        with pytest.raises(ValueError, match="Unknown direction"):
            resolver.resolve_chain(["table", "southwest", 1.0])

    def test_register_placed(self, resolver):
        resolver.register_placed("hero", {"x": 1, "y": 0, "z": 2})
        assert resolver._resolved["hero"] == {"x": 1, "y": 0, "z": 2}


# ── Compiler tests ────────────────────────────────────────────────


class TestSpatialCompiler:
    def test_loads_patterns(self, compiler):
        assert "rectangle_room" in compiler.pattern_ids
        assert "l_shape_room" in compiler.pattern_ids
        assert "corridor" in compiler.pattern_ids

    def test_pattern_summary(self, compiler):
        summary = compiler.pattern_summary_for_prompt()
        assert "rectangle_room" in summary
        assert "L-Shape Room" in summary
        assert "Corridor" in summary

    def test_compile_basic_kitchen(self, compiler):
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 5, "height": 3, "depth": 5},
            "slot_fills": {
                "north_counter_center": "stove",
                "center_table": "table",
            },
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        steps = plan.steps
        assert len(steps) > 0, "Plan should have steps"

        # Check shell nodes exist
        create_steps = [s for s in steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        assert "Floor" in names
        assert "Ceiling" in names

        # Check assets are placed
        asset_names = [s.name for s in create_steps if s.name not in ("Floor", "Ceiling")]
        assert len(asset_names) >= 2, f"Expected >=2 greybox assets, got {asset_names}"

    def test_compile_with_invalid_pattern_raises(self, compiler):
        layout = {
            "pattern": "bouncy_castle",
            "dimensions": {},
            "slot_fills": {},
            "arcs_overrides": [],
        }
        with pytest.raises(ValueError, match="not found"):
            compiler.compile_layout(layout)

    def test_compile_with_invalid_asset_skips(self, compiler):
        """Invalid assets should be logged but not crash the plan."""
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 5, "height": 3, "depth": 5},
            "slot_fills": {
                "north_counter_center": "ghost_asset_xyz",
            },
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        # Should still have shell nodes but no ghost asset
        create_steps = [s for s in plan.steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        assert "Floor" in names
        # The ghost asset shouldn't be created
        assert "ghost_asset_xyz" not in " ".join(names)

    def test_compile_empty_slots(self, compiler):
        """Layout with no slot fills should still produce shell."""
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 4, "height": 2.5, "depth": 4},
            "slot_fills": {},
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        create_steps = [s for s in plan.steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        # Should have floor + ceiling
        assert "Floor" in names
        assert "Ceiling" in names
        # No asset steps beyond shell
        assert all(n in ("Floor", "Ceiling") for n in names)

    def test_compile_l_shape(self, compiler):
        layout = {
            "pattern": "l_shape_room",
            "dimensions": {"width_main": 6, "height": 3, "depth_main": 3, "width_return": 3, "depth_return": 6},
            "slot_fills": {
                "cook_counter": "counter",
                "cook_appliance_left": "fridge",
                "cook_appliance_right": "stove",
                "center_table": "table",
                "chair_inner": "chair",
            },
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        create_steps = [s for s in plan.steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        assert "Floor" in names
        # Should have at least 4 greybox assets
        asset_count = len([n for n in names if n not in ("Floor", "Ceiling")])
        assert asset_count >= 4, f"Expected >=4 assets, got {asset_count}: {names}"

    def test_compile_corridor(self, compiler):
        layout = {
            "pattern": "corridor",
            "dimensions": {"length": 10, "width": 2.5, "height": 3},
            "slot_fills": {
                "north_start_slot": "shelf",
                "north_mid_slot": "cabinet",
                "south_mid_slot": "chair",
            },
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        create_steps = [s for s in plan.steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        assert "Floor" in names
        asset_count = len([n for n in names if n not in ("Floor", "Ceiling")])
        assert asset_count >= 3, f"Expected >=3 assets, got {asset_count}: {names}"

    def test_compile_with_arcs_overrides(self, compiler):
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 5, "height": 3, "depth": 5},
            "slot_fills": {
                "north_counter_left": "fridge",
            },
            "arcs_overrides": [
                {
                    "asset": "stove",
                    "anchor": {"chain": ["fridge_north_counter_left", "east", 0.2]},
                    "offset": [0, 0, 0],
                },
            ],
        }
        plan = compiler.compile_layout(layout)
        create_steps = [s for s in plan.steps if s.step_type == "create_entity"]
        names = [s.name for s in create_steps]
        assert "stove_arcs" in names or any("stove" in n for n in names)

    def test_validate_no_errors(self, compiler):
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 5, "height": 3, "depth": 5},
            "slot_fills": {"center_table": "table"},
            "arcs_overrides": [],
        }
        plan = compiler.compile_layout(layout)
        errors = plan.validate()
        # Plan should be valid (steps exist)
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_compile_layout_origin_offset(self, compiler):
        """A room compiled at an origin offset places furniture by that offset;
        shell=False suppresses the room's own floor/ceiling (for BSP reuse).
        Default origin=(0,0)+shell=True keeps existing callers unchanged."""
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 4, "height": 3, "depth": 4},
            "slot_fills": {"center_table": "table"},
            "arcs_overrides": [],
        }

        def table_pos(plan):
            for s in plan.steps:
                if (
                    getattr(s, "step_type", "") == "set_property"
                    and getattr(s, "property", "") == "position"
                    and s.node.endswith("table_center_table")
                ):
                    return s.value
            return None

        base = compiler.compile_layout(layout)
        off = compiler.compile_layout(layout, origin=(10.0, 20.0), shell=False)
        bp, op = table_pos(base), table_pos(off)
        assert bp is not None and op is not None, "table not placed"
        assert abs(op["x"] - (bp["x"] + 10.0)) < 1e-6, (bp, op)
        assert abs(op["z"] - (bp["z"] + 20.0)) < 1e-6, (bp, op)
        # shell=False → no Floor/Ceiling nodes
        off_names = [s.name for s in off.steps if getattr(s, "step_type", "") == "create_entity"]
        assert not any(n in ("Floor", "Ceiling") for n in off_names), off_names
        # shell=True (base) DOES build the shell
        base_names = [s.name for s in base.steps if getattr(s, "step_type", "") == "create_entity"]
        assert any(n in ("Floor", "Ceiling") for n in base_names), base_names

    def test_arcs_override_nudged_off_slot_object(self, compiler):
        """ARCS overrides get the same collision-nudge as slot fills — an
        override placed on top of a slot asset must not clip into it
        (regression: _process_arcs used to skip the overlap/nudge pass)."""
        layout = {
            "pattern": "rectangle_room",
            "dimensions": {"width": 6, "height": 3, "depth": 6},
            "slot_fills": {"center_table": "table"},
            "arcs_overrides": [
                {"asset": "table", "anchor": "center", "offset": [0, 0, 0]},
            ],
        }
        plan = compiler.compile_layout(layout)
        pos = {
            s.node: s.value
            for s in plan.steps
            if getattr(s, "step_type", "") == "set_property" and getattr(s, "property", "") == "position"
        }
        slot = next((v for k, v in pos.items() if k.endswith("table_center_table")), None)
        arc = next((v for k, v in pos.items() if k.endswith("table_arcs")), None)
        assert slot is not None and arc is not None, f"positions: {pos}"
        # table footprint 1.5×1.0 → halves 0.75×0.5; AABB must not overlap.
        assert abs(slot["x"] - arc["x"]) >= 1.5 - 1e-6 or abs(slot["z"] - arc["z"]) >= 1.0 - 1e-6, (
            f"ARCS table clips the slot table: slot={slot}, arc={arc}"
        )


# ── Layout Planner tests (unit, no LLM) ──────────────────────────


class TestLayoutPlanner:
    def test_import(self):
        from devforge.spatial.layout_planner import LayoutPlanner

        planner = LayoutPlanner()
        assert planner.grammar is not None

    def test_grammar_loads(self):
        from devforge.spatial.layout_planner import LayoutPlanner

        planner = LayoutPlanner()
        assert planner.grammar is not None
        assert "root ::=" in planner.grammar
        assert "pattern" in planner.grammar
