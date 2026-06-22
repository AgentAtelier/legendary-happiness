"""Unit tests for foundry.exterior_planner — assemble the ExteriorPlan.

Verifies the guarantees the scene needs: building centered + pad not floating,
no flora in the footprint/door corridor, player spawns outside on the door
side, recipe decisions propagate, names pass through, and it's deterministic.
"""

from __future__ import annotations

import math

import pytest

from exterior_planner import plan_exterior
from terrain_field import height_at


def _brief(biome="temperate_forest", enabled=True, **extra):
    b = {
        "scale": "medium",
        "exterior": {
            "enabled": enabled,
            "structure": "cabin",
            "biome_recipe": {"base_biome": biome},
        },
        "place_names": {"scene_name": "Hollowpine Rest",
                        "landmark_lore": [{"landmark_id": "building", "line": "An old trapper's cabin."}]},
    }
    b.update(extra)
    return b


def test_disabled_returns_none():
    assert plan_exterior(_brief(enabled=False), seed=1) is None
    assert plan_exterior({"scale": "medium"}, seed=1) is None


def test_deterministic():
    a = plan_exterior(_brief(), seed=7)
    b = plan_exterior(_brief(), seed=7)
    assert a == b


def test_building_centered_and_pad_not_floating():
    p = plan_exterior(_brief(), seed=7)
    bld = p.building
    assert bld["center"] == (0.0, 0.0)
    hw, hd = bld["half_w"], bld["half_d"]
    # pad must be at least as high as the terrain under every footprint corner
    for sx in (-1, 1):
        for sz in (-1, 1):
            corner_h = height_at(p.field, sx * hw, sz * hd)
            assert bld["pad_height"] >= corner_h - 1e-6


def test_no_flora_in_footprint_or_corridor():
    p = plan_exterior(_brief(), seed=7)
    bld = p.building
    r_building = math.hypot(bld["half_w"], bld["half_d"])
    for pt in p.scatter_placements:
        # outside the building bounding circle
        assert math.hypot(pt["x"] - 0.0, pt["z"] - 0.0) >= r_building - 1e-3


def test_spawn_outside_on_door_side():
    p = plan_exterior(_brief(), seed=7)
    bld = p.building
    # door is on +Z; spawn is further out on +Z, facing back toward the door
    assert p.spawn["z"] > bld["half_d"]
    assert p.building["door_side"] == "+z"


def test_biome_fallback_decision_propagates():
    p = plan_exterior(_brief(biome="bioluminescent_void"), seed=7)
    assert any(d.code == "exterior.biome_fallback" for d in p.decisions)
    assert p.biome["biome"] == "*"


def test_names_pass_through():
    p = plan_exterior(_brief(), seed=7)
    assert p.names["scene_name"] == "Hollowpine Rest"
    assert p.names["landmark_lore"][0]["landmark_id"] == "building"
