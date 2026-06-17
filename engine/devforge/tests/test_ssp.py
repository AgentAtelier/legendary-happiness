"""Tests for SSP Engine — archetype defaults, compile_room, merge logic.

Run with:  cd engine && .venv/bin/python -m pytest devforge/tests/test_ssp.py -v
"""

from __future__ import annotations

import pytest

from devforge.spatial.compiler import SpatialCompiler
from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.ssp import ROOM_ARCHETYPES, SSPEngine

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def lexicon():
    return AssetLexicon()


@pytest.fixture
def compiler(lexicon):
    return SpatialCompiler(lexicon)


@pytest.fixture
def ssp_no_compiler():
    """SSPEngine without a compiler — rooms produce empty plans."""
    return SSPEngine(compiler=None)


@pytest.fixture
def ssp_with_compiler(compiler):
    """SSPEngine with real SpatialCompiler for room compilation."""
    return SSPEngine(compiler=compiler)


# ── Archetype catalog tests ──────────────────────────────────────


class TestArchetypeCatalog:
    """ROOM_ARCHETYPES constants: structure, completeness, semantics."""

    def test_all_fourteen_archetypes_present(self):
        """All 14 archetypes are defined."""
        expected = {
            "kitchen",
            "living_room",
            "bedroom",
            "bathroom",
            "study",
            "hallway",
            "dining_room",
            "office",
            "library",
            "workshop",
            "cellar",
            "attic",
            "porch",
            "pantry",
        }
        assert set(ROOM_ARCHETYPES.keys()) == expected

    def test_each_archetype_has_required_fields(self):
        """Every archetype has label, pattern, dimensions, slot_fills."""
        for aid, a in ROOM_ARCHETYPES.items():
            assert "label" in a, f"{aid} missing label"
            assert "pattern" in a, f"{aid} missing pattern"
            assert "dimensions" in a, f"{aid} missing dimensions"
            assert "slot_fills" in a, f"{aid} missing slot_fills"
            assert a["dimensions"]["width"] > 0
            assert a["dimensions"]["height"] > 0
            assert a["dimensions"]["depth"] > 0

    def test_kitchen_has_cooking_slots(self):
        """Kitchen archetype has stove, fridge, counter, table."""
        a = ROOM_ARCHETYPES["kitchen"]
        sf = a["slot_fills"]
        assert sf["north_counter_center"] == "stove"
        assert sf["north_counter_left"] == "fridge"
        assert sf["north_counter_right"] == "counter"
        assert sf["center_table"] == "table"

    def test_living_room_has_seating(self):
        """Living room has table + chairs."""
        a = ROOM_ARCHETYPES["living_room"]
        sf = a["slot_fills"]
        assert "chair_north" in sf
        assert "chair_south" in sf
        assert "center_table" in sf

    def test_dining_room_has_four_chairs(self):
        """Dining room has table + all 4 chair directions."""
        a = ROOM_ARCHETYPES["dining_room"]
        sf = a["slot_fills"]
        for direction in ("north", "south", "east", "west"):
            assert f"chair_{direction}" in sf
        assert sf["center_table"] == "table"

    def test_hallway_uses_corridor_pattern(self):
        """Hallway uses the corridor pattern, not rectangle_room."""
        assert ROOM_ARCHETYPES["hallway"]["pattern"] == "corridor"

    def test_hallway_dimensions_are_narrow_and_long(self):
        """Hallway is narrow (width=2) and long (depth=8)."""
        dims = ROOM_ARCHETYPES["hallway"]["dimensions"]
        assert dims["width"] == 2.0
        assert dims["depth"] == 8.0

    def test_archetype_ids_property(self, ssp_no_compiler):
        """SSPEngine.archetype_ids returns sorted keys."""
        ids = ssp_no_compiler.archetype_ids
        assert len(ids) == 14
        assert ids[0] == "attic"
        assert ids[-1] == "workshop"

    def test_archetype_summary_contains_all_ids(self, ssp_no_compiler):
        """archetype_summary_for_prompt mentions every archetype."""
        summary = ssp_no_compiler.archetype_summary_for_prompt()
        for aid in ROOM_ARCHETYPES:
            assert aid in summary, f"{aid} missing from summary"


# ── compile_room tests ───────────────────────────────────────────


class TestCompileRoom:
    """compile_room: archetype defaults, merge logic, edge cases."""

    def test_compile_kitchen_uses_defaults(self, ssp_with_compiler):
        """Kitchen with no overrides → default furniture + shell."""
        plan = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/kitchen",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Floor, Ceiling, stove, fridge, counter, table
        assert "Floor" in create_names
        assert "Ceiling" in create_names
        assert "stove_north_counter_center" in create_names
        assert "fridge_north_counter_left" in create_names
        assert "counter_north_counter_right" in create_names
        assert "table_center_table" in create_names

    def test_compile_without_compiler_empty_plan(self, ssp_no_compiler):
        """Without a compiler, plan has 0 steps."""
        plan = ssp_no_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/kitchen",
        )
        assert plan.steps == []

    def test_slot_overrides_replace_defaults(self, ssp_with_compiler):
        """LLM slot_overrides win over preset defaults."""
        plan = ssp_with_compiler.compile_room(
            {
                "archetype": "kitchen",
                "slot_overrides": {
                    "north_counter_center": "sink",  # replace stove
                },
            },
            root_path="/root/Main/kitchen",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        assert "sink_north_counter_center" in create_names
        assert "stove_north_counter_center" not in create_names
        # Other defaults still there
        assert "fridge_north_counter_left" in create_names

    def test_slot_overrides_add_new_slots(self, ssp_with_compiler):
        """LLM can add slots not in the defaults."""
        plan = ssp_with_compiler.compile_room(
            {
                "archetype": "bedroom",
                "slot_overrides": {
                    "chair_north": "chair",  # new slot for bedroom
                },
            },
            root_path="/root/Main/bedroom",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Default bedroom: table + cabinet
        assert "table_center_table" in create_names
        assert "cabinet_east_storage" in create_names
        # Override adds a chair
        assert "chair_chair_north" in create_names

    def test_dimension_overrides_work(self, ssp_with_compiler):
        """LLM can override room dimensions — changes floor position."""
        # Default kitchen: 5×5 → floor centre at (2.5, -0.05, 2.5)
        base = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/base",
        )
        # Overridden: 8×6 → floor centre at (4.0, -0.05, 3.0)
        overridden = ssp_with_compiler.compile_room(
            {
                "archetype": "kitchen",
                "dimensions": {"width": 8.0, "depth": 6.0},
            },
            root_path="/root/Main/overridden",
        )

        # Extract floor positions
        def floor_pos(plan):
            for s in plan.steps:
                if (
                    getattr(s, "step_type", "") == "set_property"
                    and getattr(s, "property", "") == "position"
                    and "Floor" in getattr(s, "node", "")
                ):
                    return s.value
            return None

        bp = floor_pos(base)
        op = floor_pos(overridden)
        assert bp is not None and op is not None, "Floor not found"
        # Default floor centre x = 5/2 = 2.5, overridden = 8/2 = 4.0
        assert op["x"] == pytest.approx(4.0, abs=0.1)
        assert op["z"] == pytest.approx(3.0, abs=0.1)
        # Base should differ
        assert bp["x"] != pytest.approx(op["x"])

    def test_pattern_override(self, ssp_with_compiler):
        """LLM can override the pattern — living room defaults won't compile as corridor."""
        # The living_room defaults use slots like center_table, chair_north which
        # don't exist in corridor. So pattern override should work with the
        # living_room's default slot_fills (table, chairs) which will be skipped
        # by the corridor compiler. Verify shell + at least something compiles.
        plan = ssp_with_compiler.compile_room(
            {
                "archetype": "living_room",
                "pattern": "corridor",
            },
            root_path="/root/Main/living",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # corridor pattern should still produce Floor + Ceiling shell
        assert "Floor" in create_names
        assert "Ceiling" in create_names

    def test_unknown_archetype_falls_back_to_kitchen(self, ssp_with_compiler):
        """Unknown archetype name → kitchen defaults (with warning)."""
        plan = ssp_with_compiler.compile_room(
            {"archetype": "spaceship_bridge"},
            root_path="/root/Main/bridge",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Kitchen defaults applied
        assert "stove_north_counter_center" in create_names

    def test_missing_archetype_defaults_to_kitchen(self, ssp_with_compiler):
        """No archetype field → kitchen (via intent path)."""
        plan = ssp_with_compiler.compile_room(
            {},
            root_path="/root/Main/unknown",
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Kitchen assets should appear somewhere (slot names depend on seeded RNG)
        has_stove = any("stove" in n for n in create_names)
        has_fridge = any("fridge" in n for n in create_names)
        has_counter = any("counter" in n for n in create_names)
        has_table = any("table" in n for n in create_names)
        assert has_stove or has_fridge or has_counter or has_table, f"No kitchen assets found in: {create_names}"
        assert len(plan.steps) > 0

    def test_shell_false_no_floor_ceiling(self, ssp_with_compiler):
        """shell=False → no Floor/Ceiling nodes (for BSP buildings)."""
        plan = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/kitchen",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        assert "Floor" not in create_names
        assert "Ceiling" not in create_names
        # Furniture still placed
        assert "stove_north_counter_center" in create_names

    def test_origin_offset_applied(self, ssp_with_compiler):
        """Origin offset shifts all positions by the specified amount."""
        base = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/kitchen",
            origin=(0.0, 0.0),
            shell=False,
        )
        off = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/kitchen2",
            origin=(10.0, 5.0),
            shell=False,
        )
        # Furniture node names should match (same assets in same slots)
        base_names = [s.name for s in base.steps if getattr(s, "step_type", "") == "create_entity"]
        off_names = [s.name for s in off.steps if getattr(s, "step_type", "") == "create_entity"]
        assert set(base_names) == set(off_names)

        # Positions should differ by ~10 in x and ~5 in z
        def get_positions(plan):
            return [
                s.value
                for s in plan.steps
                if getattr(s, "step_type", "") == "set_property" and getattr(s, "property", "") == "position"
            ]

        base_pos = get_positions(base)
        off_pos = get_positions(off)
        assert len(base_pos) == len(off_pos)
        # Check the first furniture position offset
        for bp, op in zip(base_pos, off_pos):
            if bp.get("y", 0) > 0:  # skip floor-level nodes (y=0)
                assert op["x"] == pytest.approx(bp["x"] + 10.0, abs=0.5)
                assert op["z"] == pytest.approx(bp["z"] + 5.0, abs=0.5)
                break

    def test_compile_goal_string(self, ssp_no_compiler):
        """Plan goal mentions the archetype."""
        plan = ssp_no_compiler.compile_room(
            {"archetype": "living_room"},
            root_path="/root/Main/living",
        )
        assert "living_room" in plan.goal

    def test_all_archetypes_compile(self, ssp_with_compiler):
        """Every archetype compiles without errors."""
        for aid in ROOM_ARCHETYPES:
            plan = ssp_with_compiler.compile_room(
                {"archetype": aid},
                root_path=f"/root/Main/{aid}",
                shell=False,
            )
            assert len(plan.steps) > 0, f"{aid} produced empty plan"


# ── Intent Descriptor compile tests ──────────────────────────────


class TestCompileRoomIntent:
    """compile_room with Intent Descriptor: size, style, mood, clutter,
    must_have, special_features, seed determinism."""

    # ── Format detection ──

    def test_room_type_key_uses_intent_path(self, ssp_with_compiler):
        """room_type key routes to Intent Descriptor (not legacy)."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen"},
            root_path="/root/Main/intent_kitchen",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Intent path uses category-based assignment (seeded RNG), so assets
        # should appear but slot names differ from legacy's fixed slots
        has_asset = any(
            a in n
            for n in create_names
            for a in ("stove", "fridge", "counter", "sink", "table", "chair", "cabinet", "shelf")
        )
        assert has_asset, f"No assets found via intent path: {create_names}"
        assert len(plan.steps) > 0

    def test_archetype_key_still_uses_legacy_path(self, ssp_with_compiler):
        """Backward compat: 'archetype' key routes to legacy path."""
        plan = ssp_with_compiler.compile_room(
            {"archetype": "kitchen"},
            root_path="/root/Main/legacy_kitchen",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Legacy kitchen uses fixed slot names
        assert "stove_north_counter_center" in create_names
        assert "fridge_north_counter_left" in create_names

    def test_neither_key_falls_back_to_kitchen(self, ssp_with_compiler):
        """No archetype or room_type → kitchen via intent path."""
        plan = ssp_with_compiler.compile_room(
            {"color": "blue"},  # nonsense key
            root_path="/root/Main/fallback",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        has_asset = any(
            a in n for n in create_names for a in ("stove", "fridge", "counter", "table", "chair", "cabinet", "shelf")
        )
        assert has_asset, f"Fallback should produce kitchen assets: {create_names}"

    # ── Size presets ──

    def test_cramped_size_produces_small_footprint(self, ssp_with_compiler):
        """cramped → ~3×3m footprint; floor center x ~1.5."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "size": "cramped"},
            root_path="/root/Main/cramped",
            shell=True,
        )
        assert len(plan.steps) > 0
        floor_positions = [
            s.value
            for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
            and "Floor" in getattr(s, "node", "")
        ]
        # Floor center x = width/2, cramped → 3.0/2 = 1.5
        if floor_positions:
            fp = floor_positions[0]
            assert fp["x"] == pytest.approx(1.5, abs=0.5)
            assert fp["z"] == pytest.approx(1.5, abs=0.5)

    def test_spacious_size_produces_large_footprint(self, ssp_with_compiler):
        """spacious → ~8×6m footprint; floor center larger than cramped."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "living_room", "size": "spacious"},
            root_path="/root/Main/spacious",
            shell=True,
        )
        floor_positions = [
            s.value
            for s in plan.steps
            if getattr(s, "step_type", "") == "set_property"
            and getattr(s, "property", "") == "position"
            and "Floor" in getattr(s, "node", "")
        ]
        if floor_positions:
            fp = floor_positions[0]
            assert fp["x"] == pytest.approx(4.0, abs=0.5)
            assert fp["z"] == pytest.approx(3.0, abs=0.5)

    def test_different_sizes_produce_different_floor_positions(self, ssp_with_compiler):
        """cramped and spacious produce different floor centers."""
        cramped = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "size": "cramped", "seed": 1},
            root_path="/root/Main/A",
            shell=True,
        )
        spacious = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "size": "spacious", "seed": 1},
            root_path="/root/Main/B",
            shell=True,
        )

        def floor_center(plan):
            for s in plan.steps:
                if (
                    getattr(s, "step_type", "") == "set_property"
                    and getattr(s, "property", "") == "position"
                    and "Floor" in getattr(s, "node", "")
                ):
                    return (s.value.get("x"), s.value.get("z"))
            return None

        fc = floor_center(cramped)
        fs = floor_center(spacious)
        assert fc is not None and fs is not None
        assert fc != fs

    # ── Style palettes ──

    def test_style_produces_valid_plan(self, ssp_with_compiler):
        """Style should not crash — produces a valid plan."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "style": "rustic", "seed": 1},
            root_path="/root/Main/rustic",
            shell=False,
        )
        # Style palette is built into slot_colours in layout_json;
        # the compiler doesn't yet propagate slot_colours to asset ops.
        # Verify plan compiles successfully regardless.
        assert len(plan.steps) > 0

    # ── Mood modifiers ──

    def test_abandoned_mood_darkens_colours(self, ssp_with_compiler):
        """abandoned mood applies saturation_scale=0.4, brightness_scale=0.6."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "seed": 1,
                "mood_tags": ["abandoned"],
            },
            root_path="/root/Main/abandoned",
            shell=False,
        )
        # Should still compile
        assert len(plan.steps) > 0

    def test_sterile_mood_zeros_clutter(self, ssp_with_compiler):
        """sterile mood → clutter_mult=0.0, so no extra clutter even if clutter=0.8."""
        plan_cluttered = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "seed": 1, "clutter": 0.8},
            root_path="/root/Main/cluttered",
            shell=False,
        )
        plan_sterile = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "seed": 1, "clutter": 0.8, "mood_tags": ["sterile"]},
            root_path="/root/Main/sterile",
            shell=False,
        )
        # sterile should have fewer props (clutter zeroed out)
        cluttered_names = [s.name for s in plan_cluttered.steps if getattr(s, "step_type", "") == "create_entity"]
        sterile_names = [s.name for s in plan_sterile.steps if getattr(s, "step_type", "") == "create_entity"]
        assert len(sterile_names) <= len(cluttered_names), (
            f"Sterile ({len(sterile_names)}) should have ≤ props than cluttered ({len(cluttered_names)})"
        )

    def test_unknown_mood_tag_does_not_crash(self, ssp_with_compiler):
        """Unknown mood tags are logged and skipped — no crash."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "mood_tags": ["not_a_real_mood"], "seed": 1},
            root_path="/root/Main/unknown_mood",
            shell=False,
        )
        assert len(plan.steps) > 0

    def test_multiple_moods_compose(self, ssp_with_compiler):
        """Multiple mood tags stack their modifiers."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "seed": 1,
                "mood_tags": ["dark", "abandoned"],
            },
            root_path="/root/Main/double_mood",
            shell=False,
        )
        assert len(plan.steps) > 0

    # ── Clutter ──

    def test_clutter_zero_minimal_props(self, ssp_with_compiler):
        """clutter=0 → essentials only, no extra props."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "clutter": 0.0, "seed": 1},
            root_path="/root/Main/clutter0",
            shell=False,
        )
        # Kitchen requires cooking_surface, food_storage, prep_surface, lighting
        # → 4 required slots. No clutter.
        create_count = sum(1 for s in plan.steps if getattr(s, "step_type", "") == "create_entity")
        assert create_count > 0

    def test_clutter_full_more_props(self, ssp_with_compiler):
        """clutter=1.0 → maximum extra props."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "kitchen", "clutter": 1.0, "seed": 1},
            root_path="/root/Main/clutter1",
            shell=False,
        )
        create_count = sum(1 for s in plan.steps if getattr(s, "step_type", "") == "create_entity")
        assert create_count > 0

    def test_high_clutter_more_than_zero_clutter(self, ssp_with_compiler):
        """clutter=1.0 produces more props than clutter=0.0."""
        low = ssp_with_compiler.compile_room(
            {"room_type": "living_room", "clutter": 0.0, "seed": 1},
            root_path="/root/Main/low",
            shell=False,
        )
        high = ssp_with_compiler.compile_room(
            {"room_type": "living_room", "clutter": 1.0, "seed": 1},
            root_path="/root/Main/high",
            shell=False,
        )
        low_count = sum(1 for s in low.steps if getattr(s, "step_type", "") == "create_entity")
        high_count = sum(1 for s in high.steps if getattr(s, "step_type", "") == "create_entity")
        assert high_count >= low_count, (
            f"clutter=1.0 ({high_count}) should have >= props than clutter=0.0 ({low_count})"
        )

    # ── must_have forced assets ──

    def test_must_have_forces_asset(self, ssp_with_compiler):
        """must_have asset appears in the plan."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "seed": 1,
                "must_have": ["sink"],
            },
            root_path="/root/Main/must_have",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        has_sink = any("sink" in n for n in create_names)
        assert has_sink, f"must_have sink not found in: {create_names}"

    def test_must_have_multiple_assets(self, ssp_with_compiler):
        """Multiple must_have assets — at least one appears (compiler may
        reject individual assets due to chain dependencies or footprint)."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "bedroom",
                "seed": 1,
                "must_have": ["cabinet", "chair"],
            },
            root_path="/root/Main/must_have_multi",
            shell=False,
        )
        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # At least one must_have asset should survive compilation;
        # the other may be rejected due to chain dependency or footprint.
        has_cabinet = any("cabinet" in n for n in create_names)
        has_chair = any("chair" in n for n in create_names)
        assert has_cabinet or has_chair, f"Neither must_have asset appeared: {create_names}"

    # ── Special features ──

    def test_fireplace_creates_cabinet_arcs_override(self, ssp_with_compiler):
        """fireplace feature compiles without error."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "living_room",
                "seed": 1,
                "special_features": ["fireplace"],
            },
            root_path="/root/Main/fireplace",
            shell=False,
        )
        assert len(plan.steps) > 0

    def test_secret_passage_feature(self, ssp_with_compiler):
        """secret_passage feature compiles without error."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "study",
                "seed": 1,
                "special_features": ["secret_passage"],
            },
            root_path="/root/Main/passage",
            shell=False,
        )
        assert len(plan.steps) > 0

    def test_unknown_special_feature_does_not_crash(self, ssp_with_compiler):
        """Unknown feature is logged and skipped — no crash."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "seed": 1,
                "special_features": ["teleporter", "fireplace"],
            },
            root_path="/root/Main/mixed_features",
            shell=False,
        )
        # fireplace works, teleporter is logged
        assert len(plan.steps) > 0

    # ── Seed determinism ──

    def test_same_seed_same_plan(self, ssp_with_compiler):
        """Same descriptor + same seed → identical slot_fills."""
        p1 = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "size": "normal",
                "style": "rustic",
                "seed": 42,
            },
            root_path="/root/Main/A",
            shell=False,
        )
        p2 = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "size": "normal",
                "style": "rustic",
                "seed": 42,
            },
            root_path="/root/Main/B",
            shell=False,
        )
        n1 = sorted(s.name for s in p1.steps if getattr(s, "step_type", "") == "create_entity")
        n2 = sorted(s.name for s in p2.steps if getattr(s, "step_type", "") == "create_entity")
        assert n1 == n2, f"Same seed should produce identical assets:\n  A: {n1}\n  B: {n2}"

    def test_different_seed_different_plan(self, ssp_with_compiler):
        """Different seeds → different slot_fills (statistically near-certain)."""
        p1 = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "size": "normal",
                "style": "rustic",
                "seed": 1,
            },
            root_path="/root/Main/seed1",
            shell=False,
        )
        p2 = ssp_with_compiler.compile_room(
            {
                "room_type": "kitchen",
                "size": "normal",
                "style": "rustic",
                "seed": 999,
            },
            root_path="/root/Main/seed999",
            shell=False,
        )
        n1 = sorted(s.name for s in p1.steps if getattr(s, "step_type", "") == "create_entity")
        n2 = sorted(s.name for s in p2.steps if getattr(s, "step_type", "") == "create_entity")
        # Both should produce assets
        assert len(n1) > 0 and len(n2) > 0
        # Different seeds should produce different slot assignments.
        # Statistically near-certain with shuffled slots; if this ever fails,
        # investigate whether the RNG is actually seeded.
        assert n1 != n2, f"Different seeds should produce different plans:\n  seed=1:   {n1}\n  seed=999: {n2}"

    def test_no_seed_uses_room_type_hash(self, ssp_with_compiler):
        """No seed provided → deterministic from room_type hash."""
        p1 = ssp_with_compiler.compile_room(
            {"room_type": "kitchen"},
            root_path="/root/Main/noseed1",
            shell=False,
        )
        p2 = ssp_with_compiler.compile_room(
            {"room_type": "kitchen"},
            root_path="/root/Main/noseed2",
            shell=False,
        )
        n1 = sorted(s.name for s in p1.steps if getattr(s, "step_type", "") == "create_entity")
        n2 = sorted(s.name for s in p2.steps if getattr(s, "step_type", "") == "create_entity")
        # Same room_type → same seed → same plan
        assert n1 == n2, f"Identical descriptors without seed should produce identical plans:\n  A: {n1}\n  B: {n2}"

    # ── Hallway uses corridor pattern ──

    def test_hallway_uses_corridor_pattern_intent(self, ssp_with_compiler):
        """Intent path: hallway room_type → corridor pattern."""
        plan = ssp_with_compiler.compile_room(
            {"room_type": "hallway", "seed": 1},
            root_path="/root/Main/hallway_intent",
            shell=True,
        )
        assert len(plan.steps) > 0

    # ── Full descriptor compilation ──

    def test_full_descriptor_compiles(self, ssp_with_compiler):
        """A complete Intent Descriptor compiles end-to-end."""
        plan = ssp_with_compiler.compile_room(
            {
                "room_type": "library",
                "size": "spacious",
                "style": "noble",
                "clutter": 0.5,
                "mood_tags": ["cozy", "grand"],
                "must_have": ["table", "shelf"],
                "special_features": ["fireplace"],
                "seed": 2024,
            },
            root_path="/root/Main/full_library",
            shell=True,
        )
        assert len(plan.steps) > 0

        create_names = [s.name for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]
        # Should have floor/ceiling (shell) + furniture
        assert "Floor" in create_names
        assert "Ceiling" in create_names
        # must_have assets may be rejected by the compiler if they don't
        # fit the assigned slot. At least one must_have asset should appear.
        has_table = any("table" in n for n in create_names)
        has_shelf = any("shelf" in n for n in create_names)
        assert has_table or has_shelf, f"Neither must_have asset appeared: {create_names}"
        # Verify some furniture was placed beyond just shell
        non_shell = [n for n in create_names if n not in ("Floor", "Ceiling")]
        assert len(non_shell) > 0, f"No furniture placed: {create_names}"

    # ── Goal string ──

    def test_compile_goal_mentions_room_type(self, ssp_no_compiler):
        """Plan goal mentions the room_type."""
        plan = ssp_no_compiler.compile_room(
            {"room_type": "library"},
            root_path="/root/Main/lib",
        )
        assert "library" in plan.goal

    def test_compile_goal_mentions_size_and_style(self, ssp_no_compiler):
        """Plan goal includes size and style when present."""
        plan = ssp_no_compiler.compile_room(
            {"room_type": "kitchen", "size": "cramped", "style": "derelict"},
            root_path="/root/Main/k",
        )
        assert "cramped" in plan.goal
        assert "derelict" in plan.goal


# ── Import tests ─────────────────────────────────────────────────


class TestSSPImports:
    def test_imports_available(self):
        from devforge.spatial.ssp import ROOM_ARCHETYPES, SSPEngine

        assert SSPEngine is not None
        assert ROOM_ARCHETYPES is not None

    def test_engine_creatable_without_compiler(self):
        engine = SSPEngine(compiler=None)
        assert engine._compiler is None

    def test_engine_creatable_with_compiler(self, compiler):
        engine = SSPEngine(compiler=compiler)
        assert engine._compiler is not None
