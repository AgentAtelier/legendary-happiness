"""Unit tests for foundry.exterior_compiler — exterior-layer .tscn emission."""

from __future__ import annotations

from exterior_compiler import emit_exterior_layer
from exterior_planner import plan_exterior


def _plan(seed=7):
    brief = {
        "scale": "medium",
        "exterior": {"enabled": True, "structure": "cabin",
                     "biome_recipe": {"base_biome": "temperate_forest"}},
        "place_names": {"scene_name": "Hollowpine Rest", "landmark_lore": []},
    }
    return plan_exterior(brief, seed=seed)


def test_emits_valid_scene_header_and_terrain():
    tscn = emit_exterior_layer(_plan())
    assert tscn.startswith("[gd_scene load_steps=")
    assert 'path="res://assets/terrain.glb"' in tscn
    assert '[node name="Terrain" parent="." instance=ExtResource("1_terrain")]' in tscn


def test_world_environment_and_sun_present():
    tscn = emit_exterior_layer(_plan())
    assert '[node name="WorldEnvironment"' in tscn
    assert 'environment = SubResource("world_env")' in tscn
    assert '[node name="Sun" type="DirectionalLight3D"' in tscn
    assert '[sub_resource type="Environment" id="world_env"]' in tscn


def test_one_flora_node_per_placement():
    plan = _plan()
    tscn = emit_exterior_layer(plan)
    n_flora_nodes = tscn.count('parent="." instance=ExtResource(') - 1  # minus the terrain node
    assert n_flora_nodes == len(plan.scatter_placements)
    assert len(plan.scatter_placements) > 0


def test_flora_ext_resource_per_category():
    plan = _plan()
    tscn = emit_exterior_layer(plan)
    cats = {p["category"] for p in plan.scatter_placements}
    for cat in cats:
        assert f'path="res://assets/{cat}.glb"' in tscn


def test_player_spawn_outside_at_spawn_position():
    plan = _plan()
    tscn = emit_exterior_layer(plan)
    assert '[node name="PlayerSpawn" type="Marker3D"' in tscn
    # spawn z (outside, +Z) appears in a transform
    assert f"{plan.spawn['z']:.4f}" in tscn


def test_deterministic():
    a = emit_exterior_layer(_plan(seed=3))
    b = emit_exterior_layer(_plan(seed=3))
    assert a == b
