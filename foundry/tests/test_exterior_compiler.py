"""Unit tests for foundry.exterior_compiler — exterior-layer .tscn emission."""

from __future__ import annotations

from exterior_compiler import compile_exterior_build, emit_exterior_layer
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


def test_building_shell_with_door_gap_and_roof():
    tscn = emit_exterior_layer(_plan())
    for wall in ("WallBack", "WallE", "WallW", "WallFrontL", "WallFrontR", "Roof"):
        assert f'[node name="{wall}" type="StaticBody3D"' in tscn or f'[node name="{wall}"' in tscn
    # door gap: the +Z (front) wall is two segments, not one solid wall
    assert '"WallFrontL"' in tscn and '"WallFrontR"' in tscn
    # walls are collidable (player blocked) — CollisionShape3D + BoxShape3D
    assert "CollisionShape3D" in tscn and 'type="BoxShape3D"' in tscn


def test_load_steps_counts_all_resources():
    tscn = emit_exterior_layer(_plan())
    declared = int(tscn.split("load_steps=", 1)[1].split(" ", 1)[0])
    actual = tscn.count("[ext_resource") + tscn.count("[sub_resource") + 1
    assert declared == actual


def test_interior_props_emitted_inside_building():
    plan = _plan()
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak", "x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0},
        {"id": "npc_0", "category": "humanoid", "material": "rough_granite", "x": 1.5, "y": 0.0, "z": -1.0, "yaw": 1.0},
    ]
    tscn = emit_exterior_layer(plan, interior_manifest=manifest)
    assert 'path="res://assets/table_worn_oak.glb"' in tscn
    assert 'path="res://assets/humanoid_rough_granite.glb"' in tscn
    assert '[node name="table_0" parent="." instance=ExtResource(' in tscn
    assert '[node name="npc_0" parent="." instance=ExtResource(' in tscn


def test_no_interior_is_fine():
    tscn = emit_exterior_layer(_plan(), interior_manifest=None)
    assert "[gd_scene" in tscn  # still a valid scene with no interior


_BRIEF = {
    "scale": "medium", "setting": "snowy cabin", "theme_tag": "hermit",
    "key_features": [], "characters": [],
    "exterior": {"enabled": True, "structure": "cabin",
                 "biome_recipe": {"base_biome": "temperate_forest"}},
    "place_names": {"scene_name": "Hollowpine", "landmark_lore": []},
}


def test_compile_exterior_build_sources_interior_live():
    tscn = compile_exterior_build(_BRIEF, seed=7)
    assert tscn.startswith("[gd_scene")
    assert '[node name="Terrain"' in tscn          # exterior layer
    assert '[node name="WallBack"' in tscn          # building shell
    assert "res://assets/table_worn_oak.glb" in tscn  # interior SOURCED from layout_room


def test_compile_exterior_build_deterministic():
    assert compile_exterior_build(_BRIEF, seed=5) == compile_exterior_build(_BRIEF, seed=5)


def test_deterministic():
    a = emit_exterior_layer(_plan(seed=3))
    b = emit_exterior_layer(_plan(seed=3))
    assert a == b


# ── lighting_tier routing (bake injected as a stub) ──────────────────

def _stub_baker(desc, out_dir):
    import os
    p = os.path.join(out_dir, "baked.glb")
    with open(p, "w") as f:
        f.write("glb")
    return [p]


def test_lighting_tier0_emits_realtime_instances():
    tscn = compile_exterior_build(_BRIEF, 7, lighting_tier=0)
    assert '[node name="Terrain"' in tscn  # individual realtime instances


def test_lighting_tier1_emits_single_baked_scene(tmp_path):
    tscn = compile_exterior_build(_BRIEF, 7, lighting_tier=1,
                                  baker=_stub_baker, cache_root=tmp_path)
    assert '[node name="BakedScene" parent="." instance=ExtResource(' in tscn
    assert "baked.glb" in tscn
    assert '[node name="Terrain"' not in tscn  # not individual instances anymore


def test_lighting_bake_failure_falls_back_to_realtime(tmp_path):
    def bad_baker(desc, out_dir):
        raise RuntimeError("hip oom")

    tscn = compile_exterior_build(_BRIEF, 7, lighting_tier=2,
                                  baker=bad_baker, cache_root=tmp_path)
    assert '[node name="Terrain"' in tscn  # degraded to realtime, scene still renders
