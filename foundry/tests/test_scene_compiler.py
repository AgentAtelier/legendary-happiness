"""Tests for the deterministic scene compiler — .tscn generation from
quest spec + placed-entity manifest.

Tests assert structural correctness of the generated .tscn text
WITHOUT launching Godot (per P3 TDD spec).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scene_compiler import (
    PlacedEntity,
    _resolve_unique_glbs,
    _glb_res_path,
    _ext_resource_block,
    _fmt_pos,
    _parse_scene_text,
    _resolve_prop_overlaps,
    _prop_half_extents,
    compile_scene,
    read_quest_data,
)


# ── Test manifest ────────────────────────────────────────────────

_MANIFEST: list[PlacedEntity] = [
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "wear": 0.8, "x": 1.0, "y": 0.0, "z": -1.5},
    {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
     "wear": 0.15, "x": -2.0, "y": 0.0, "z": -3.0},
    {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
     "wear": 0.8, "x": 2.5, "y": 0.0, "z": -2.0},
    {"id": "table_1", "category": "table", "material": "worn_oak",
     "wear": 0.15, "x": -1.0, "y": 0.0, "z": -0.5},
]

_QUEST_SPEC = {
    "npc_role": "hermit",
    "target_entity": "shelf_0",
    "dialogue": {
        "greet": "Ah, a visitor! Welcome.",
        "ask": "Find my lost book on the shelf.",
        "wrong": "No, that is not my book.",
        "thank": "You found it! Thank you.",
    },
    "objective": {
        "type": "fetch",
        "target": "shelf_0",
        "giver": "npc",
    },
}


# ── Unit tests (no file I/O) ─────────────────────────────────────

def test_glb_res_path():
    assert _glb_res_path("table", "worn_oak") == "res://assets/table_worn_oak.glb"
    assert _glb_res_path("shelf", "rough_granite", "models") == \
        "res://models/shelf_rough_granite.glb"


def test_resolve_unique_glbs():
    pairs = _resolve_unique_glbs(_MANIFEST)
    assert len(pairs) == 3
    assert ("cabinet", "wrought_iron") in pairs
    assert ("shelf", "rough_granite") in pairs
    assert ("table", "worn_oak") in pairs
    assert pairs == sorted(pairs)


def test_ext_resource_block():
    pairs = [("shelf", "rough_granite"), ("table", "worn_oak")]
    block = _ext_resource_block(pairs, "assets")
    lines = block.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert line.startswith('[ext_resource type="PackedScene"')
        assert 'path="res://assets/' in line
        assert 'id="' in line
        # No uid — deterministic output
        assert "uid=" not in line


def test_fmt_pos():
    assert _fmt_pos(0.0) == "0"
    assert _fmt_pos(1.0) == "1"
    assert _fmt_pos(0.5) == "0.5"
    assert _fmt_pos(-2.0) == "-2"


# ── Compile + structural assertions ──────────────────────────────

def _compile_and_parse(
    quest_spec=None, manifest=None, target="shelf_0"
):
    """Helper: compile to a temp file, read it back, parse it."""
    spec = dict(quest_spec or _QUEST_SPEC)
    if "target_entity" not in spec:
        spec["target_entity"] = target
    man = manifest or _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        data = read_quest_data(out)
        return text, parsed, data
    finally:
        Path(out).unlink()
        # Clean up the quest_data.json too
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_compile_writes_file():
    """compile_scene writes a file and returns the path."""
    path = compile_scene(_QUEST_SPEC, _MANIFEST, "/tmp/test_p3.tscn")
    assert Path(path).exists()
    Path(path).unlink()
    # Clean up quest data
    data_file = Path("/tmp/test_p3_quest_data.json")
    if data_file.exists():
        data_file.unlink()


def test_scene_has_header():
    _, parsed, _ = _compile_and_parse()
    root_nodes = [n for n in parsed["nodes"] if n["name"] == "Root"]
    assert len(root_nodes) == 1
    assert root_nodes[0]["type"] == "Node3D"


# ── Node name assertions ─────────────────────────────────────────

def test_scene_has_all_prop_nodes():
    _, parsed, _ = _compile_and_parse()
    node_names = {n["name"] for n in parsed["nodes"]}
    for entry in _MANIFEST:
        assert entry["id"] in node_names, f"missing node for {entry['id']}"
        assert f"{entry['id']}_model" in node_names


def test_scene_has_npc_node():
    _, parsed, _ = _compile_and_parse()
    npc_nodes = [n for n in parsed["nodes"] if n["name"] == "NPC"]
    assert len(npc_nodes) == 1
    assert npc_nodes[0]["type"] == "StaticBody3D"


def test_scene_has_shell_nodes():
    _, parsed, _ = _compile_and_parse()
    node_names = {n["name"] for n in parsed["nodes"]}
    assert "Player" in node_names
    assert "Camera3D" in node_names
    assert "HUD" in node_names
    assert "WinScreen" in node_names


def test_camera_is_child_of_player():
    _, parsed, _ = _compile_and_parse()
    camera = next(n for n in parsed["nodes"] if n["name"] == "Camera3D")
    assert camera["parent"] == "Player"


# ── Tag assertions (tag → behaviour table) ───────────────────────

def test_target_prop_has_pickup_tag():
    _, parsed, _ = _compile_and_parse()
    target = _QUEST_SPEC["target_entity"]  # shelf_0
    meta = parsed["metadata"].get(target, {})
    assert meta.get("_forge_tag") == "pickup", (
        f"target prop {target!r} should have pickup tag, got {meta}"
    )


def test_all_props_have_pickup_tag():
    """FIX-5: All props (not just target) have pickup tag."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        meta = parsed["metadata"].get(entry["id"], {})
        assert meta.get("_forge_tag") == "pickup", (
            f"prop {entry['id']!r} should have pickup tag (FIX-5), got {meta}"
        )


def test_npc_has_talk_and_give_tags():
    _, parsed, _ = _compile_and_parse()
    meta = parsed["metadata"].get("NPC", {})
    assert meta.get("_forge_tag") == "talk"
    assert meta.get("_forge_tag_give") == "give"


# ── P5: component script attachment (tag→script wiring) ──────────

def test_target_prop_has_pickup_script():
    """The target prop node gets pickup.gd attached via script=."""
    _, parsed, _ = _compile_and_parse()
    target = _QUEST_SPEC["target_entity"]
    node = next(n for n in parsed["nodes"] if n["name"] == target)
    assert node.get("script") == "s_pickup", (
        f"target prop {target!r} should have script=s_pickup, got {node.get('script')!r}"
    )


def test_npc_has_talk_script():
    """The NPC node gets npc.gd attached via the talk tag."""
    _, parsed, _ = _compile_and_parse()
    npc = next(n for n in parsed["nodes"] if n["name"] == "NPC")
    assert npc.get("script") == "s_talk", (
        f"NPC should have script=s_talk, got {npc.get('script')!r}"
    )


def test_all_props_have_pickup_script():
    """FIX-5: All props (not just target) get pickup.gd script."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        node = next(n for n in parsed["nodes"] if n["name"] == entry["id"])
        assert node.get("script") == "s_pickup", (
            f"prop {entry['id']!r} should have script=s_pickup (FIX-5), got {node.get('script')!r}"
        )


def test_ext_resources_include_component_scripts():
    """ext_resources block includes pickup.gd and npc.gd."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/pickup.gd" in paths
    assert "res://scripts/npc.gd" in paths
    ids = {r["id"] for r in parsed["ext_resources"]}
    assert "s_pickup" in ids
    assert "s_talk" in ids


def test_shell_nodes_have_shell_scripts():
    """P4 shell scripts are still attached after P5 changes."""
    _, parsed, _ = _compile_and_parse()
    player = next(n for n in parsed["nodes"] if n["name"] == "Player")
    assert player.get("script") == "s_player"
    interact = next(n for n in parsed["nodes"] if n["name"] == "InteractionRaycast")
    assert interact.get("script") == "s_interact"
    hud = next(n for n in parsed["nodes"] if n["name"] == "HUD")
    assert hud.get("script") == "s_hud"
    win = next(n for n in parsed["nodes"] if n["name"] == "WinScreen")
    assert win.get("script") == "s_win"


# ── Quest data JSON round-trip ───────────────────────────────────

def test_quest_data_json_written():
    """compile_scene writes a _quest_data.json alongside the .tscn."""
    _, _, data = _compile_and_parse()
    assert data is not None
    assert data["npc_role"] == "hermit"
    assert data["target_entity"] == "shelf_0"


def test_dialogue_round_trips():
    _, _, data = _compile_and_parse()
    assert data["dialogue"]["greet"] == "Ah, a visitor! Welcome."
    assert data["dialogue"]["ask"] == "Find my lost book on the shelf."
    assert data["dialogue"]["wrong"] == "No, that is not my book."
    assert data["dialogue"]["thank"] == "You found it! Thank you."


def test_objective_round_trips():
    _, _, data = _compile_and_parse()
    assert data["objective"]["type"] == "fetch"
    assert data["objective"]["target"] == "shelf_0"
    assert data["objective"]["giver"] == "npc"


def test_npc_role_in_quest_data():
    """NPC role is stored in quest_data.json, not in NPC node metadata."""
    _, parsed, data = _compile_and_parse()
    assert data["npc_role"] == "hermit"
    # NPC node should NOT have npc_role metadata
    npc_meta = parsed["metadata"].get("NPC", {})
    assert "npc_role" not in npc_meta


def test_target_entity_in_quest_data():
    _, _, data = _compile_and_parse()
    assert data["target_entity"] == "shelf_0"


# ── GLB instancing ──────────────────────────────────────────────

def test_ext_resources_reference_glbs():
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://assets/table_worn_oak.glb" in paths
    assert "res://assets/shelf_rough_granite.glb" in paths
    assert "res://assets/cabinet_wrought_iron.glb" in paths


def test_model_nodes_instance_glbs():
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        model_name = f"{entry['id']}_model"
        model = next(n for n in parsed["nodes"] if n["name"] == model_name)
        assert model["instance"] is not None, (
            f"{model_name} should instance a GLB via ExtResource"
        )


# ── Transforms ───────────────────────────────────────────────────

def test_prop_transforms_match_manifest():
    text, _, _ = _compile_and_parse()
    for entry in _MANIFEST:
        x, y, z = entry.get("x", 0), entry.get("y", 0), entry.get("z", 0)
        expected = (
            f"Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{_fmt_pos(x)}, {_fmt_pos(y)}, {_fmt_pos(z)})"
        )
        assert expected in text, (
            f"missing transform for {entry['id']}: {expected}"
        )


def test_default_position_zero():
    """Entries without x/y/z default to (0,0,0) but get pushed away
    from player spawn (FIX-1e guard)."""
    manifest_no_pos: list[PlacedEntity] = [
        {"id": "thing", "category": "table", "material": "worn_oak"}
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "thing"
    text, _, _ = _compile_and_parse(quest_spec=spec, manifest=manifest_no_pos)
    # (0,0,0) is within PLAYER_CLEAR_RADIUS (1.0) → pushed to (1, 0, 0)
    expected = "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0)"
    assert expected in text, (
        f"default (0,0,0) position should be guarded to (1,0,0), "
        f"text:\n{text[:500]}"
    )


# ── NPC body (P7: generated humanoid GLB) ───────────────────────

def test_npc_has_glb_body():
    """NPC Body node instances a GLB via header-line instance= (FIX-1a)."""
    _, parsed, _ = _compile_and_parse()
    body_nodes = [n for n in parsed["nodes"] if n["name"] == "Body"]
    assert len(body_nodes) == 1
    assert body_nodes[0]["parent"] == "NPC"
    # FIX-1a: type= is omitted when instance= is on the [node] header line
    assert body_nodes[0].get("instance") is not None, (
        "Body node should instance a GLB via ExtResource (on header line)"
    )


def test_ext_resources_include_npc_body_glb():
    """ext_resources includes the humanoid GLB for the NPC body."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://assets/humanoid_rough_granite.glb" in paths, (
        f"expected humanoid GLB in ext_resources, got {paths}"
    )


def test_no_capsule_mesh_sub_resource():
    """P7 removes the CapsuleMesh sub_resource — NPC body is now a GLB.

    CapsuleMesh for the player visible body (Item 4) and room shell
    materials (Item 2) are expected.
    """
    text, _, _ = _compile_and_parse()
    assert "npc_mesh" not in text
    assert "npc_mat" not in text


# ── Different target entity ──────────────────────────────────────

def test_different_target_still_has_pickup_tag():
    """FIX-5: Changing target_entity doesn't affect tags — all props are pickup."""
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "table_0"
    _, parsed, _ = _compile_and_parse(quest_spec=spec)
    assert parsed["metadata"]["table_0"]["_forge_tag"] == "pickup"
    assert parsed["metadata"]["shelf_0"]["_forge_tag"] == "pickup"


# ── Dialogue with special characters (JSON round-trip) ───────────

def test_dialogue_with_special_chars():
    """Dialogue with double quotes round-trips correctly via JSON."""
    spec = dict(_QUEST_SPEC)
    spec["dialogue"] = {
        "greet": 'He said "hello"',
        "ask": "Find the book.",
        "wrong": "Not it.",
        "thank": "Thanks!",
    }
    _, _, data = _compile_and_parse(quest_spec=spec)
    assert data["dialogue"]["greet"] == 'He said "hello"'
    assert data["dialogue"]["ask"] == "Find the book."


# ── Edge case: empty dialogue ────────────────────────────────────

def test_empty_dialogue_ok():
    spec = dict(_QUEST_SPEC)
    spec["dialogue"] = {"greet": "", "ask": "", "wrong": "", "thank": ""}
    _, _, data = _compile_and_parse(quest_spec=spec)
    assert data["dialogue"]["greet"] == ""


# ── FIX-1: Floor node ───────────────────────────────────────────

def test_floor_node_exists():
    """FIX-1b: Scene has a Floor StaticBody3D."""
    _, parsed, _ = _compile_and_parse()
    floor_nodes = [n for n in parsed["nodes"] if n["name"] == "Floor"]
    assert len(floor_nodes) == 1
    assert floor_nodes[0]["type"] == "StaticBody3D"
    assert floor_nodes[0]["parent"] == "."


def test_floor_collision_shape_exists():
    """FIX-1b: Floor has a CollisionShape3D child with BoxShape3D sub_resource."""
    _, parsed, _ = _compile_and_parse()
    collision = next(
        (n for n in parsed["nodes"] if n["name"] == "FloorCollision"), None
    )
    assert collision is not None, "FloorCollision node missing"
    assert collision["parent"] == "Floor"
    assert collision["type"] == "CollisionShape3D"
    assert collision.get("shape") is not None, (
        "FloorCollision should reference a SubResource"
    )


def test_sub_resources_include_box_and_capsule():
    """FIX-1: sub_resources block has at least BoxShape3D (floor) and
    CapsuleShape3D (player)."""
    _, parsed, _ = _compile_and_parse()
    sub_types = {s["type"] for s in parsed.get("sub_resources", [])}
    assert "BoxShape3D" in sub_types, (
        f"expected BoxShape3D in sub_resources, got {sub_types}"
    )
    assert "CapsuleShape3D" in sub_types, (
        f"expected CapsuleShape3D in sub_resources, got {sub_types}"
    )


# ── FIX-1: Player collision ─────────────────────────────────────

def test_player_collision_shape_exists():
    """FIX-1c: Player has a CollisionShape3D child (CapsuleShape3D)."""
    _, parsed, _ = _compile_and_parse()
    collision = next(
        (n for n in parsed["nodes"] if n["name"] == "PlayerCollision"), None
    )
    assert collision is not None, "PlayerCollision node missing"
    assert collision["parent"] == "Player"
    assert collision["type"] == "CollisionShape3D"
    assert collision.get("shape") is not None, (
        "PlayerCollision should reference a CapsuleShape3D SubResource"
    )


# ── FIX-1: Interactable collision shapes ────────────────────────

def test_target_prop_has_collision_shape():
    """FIX-1d: The target prop has a CollisionShape3D child."""
    _, parsed, _ = _compile_and_parse()
    target = _QUEST_SPEC["target_entity"]
    collision = next(
        (n for n in parsed["nodes"] if n["name"] == f"{target}_collision"), None
    )
    assert collision is not None, (
        f"expected {target}_collision node, got nodes: "
        f"{[n['name'] for n in parsed['nodes']]}"
    )
    assert collision["parent"] == target
    assert collision["type"] == "CollisionShape3D"
    assert collision.get("shape") is not None


def test_all_props_have_collision_shape():
    """FIX-5: All props have a CollisionShape3D child."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        eid = entry["id"]
        collision = next(
            (n for n in parsed["nodes"] if n["name"] == f"{eid}_collision"), None
        )
        assert collision is not None, (
            f"expected {eid}_collision node (FIX-5), got nodes: "
            f"{[n['name'] for n in parsed['nodes']]}"
        )
        assert collision["parent"] == eid
        assert collision["type"] == "CollisionShape3D"
        assert collision.get("shape") is not None


def test_npc_has_collision_shape():
    """FIX-1d: The NPC has a CollisionShape3D child."""
    _, parsed, _ = _compile_and_parse()
    collision = next(
        (n for n in parsed["nodes"] if n["name"] == "NPC_collision"), None
    )
    assert collision is not None, "NPC_collision node missing"
    assert collision["parent"] == "NPC"
    assert collision["type"] == "CollisionShape3D"
    assert collision.get("shape") is not None


def test_target_prop_type_is_static_body():
    """FIX-1a/d: The target prop (interactable) is a StaticBody3D."""
    _, parsed, _ = _compile_and_parse()
    target = _QUEST_SPEC["target_entity"]
    node = next(n for n in parsed["nodes"] if n["name"] == target)
    assert node["type"] == "StaticBody3D", (
        f"target prop should be StaticBody3D (for raycast), got {node['type']}"
    )


def test_all_props_are_static_body():
    """FIX-5: All props are StaticBody3D (pickable with collision)."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        node = next(n for n in parsed["nodes"] if n["name"] == entry["id"])
        assert node["type"] == "StaticBody3D", (
            f"prop {entry['id']!r} should be StaticBody3D (FIX-5), got {node['type']}"
        )


# ── FIX-1a: GLB instancing via header line ──────────────────────

def test_model_nodes_have_no_type():
    """FIX-1a: GLB model nodes omit type= (instance= on header line)."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        model_name = f"{entry['id']}_model"
        model = next(n for n in parsed["nodes"] if n["name"] == model_name)
        assert model.get("type") == "", (
            f"{model_name} should have no type= (instanced via header line), "
            f"got type={model.get('type')!r}"
        )
        assert model.get("instance") is not None


# ── FIX-1b: Floor transform ─────────────────────────────────────

def test_floor_transform_is_at_y_neg_half():
    """Floor top at y=0 → centre at y=-0.5 for a 1-unit-thick box."""
    text, _, _ = _compile_and_parse()
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)" in text, (
        "Floor should be centred at y=-0.5 (top at y=0)"
    )


# ── FIX-1c: Player spawn transform ──────────────────────────────

def test_player_spawn_at_y_1():
    """FIX-1c: Player spawns at y=1 to be clear of floor and props."""
    text, _, _ = _compile_and_parse()
    # Player should have a transform with y=1 (not the old default 0)
    assert "0, 1, 0)" in text, (
        f"Player spawn transform should include y=1\ntext:\n{text[:1000]}"
    )


# ── FIX-1e: Player spawn guard ──────────────────────────────────

def test_prop_near_origin_pushed_away():
    """Props at (0,0,0) get pushed away from player spawn."""
    from scene_compiler import _guard_player_spawn
    x, z = _guard_player_spawn(0.0, 0.0)
    assert x > 0.5, (
        f"(0,0) should be pushed away from origin, got ({x},{z})"
    )
    assert z == 0.0


def test_prop_far_from_origin_stays():
    """Props far from origin are not moved by the guard."""
    from scene_compiler import _guard_player_spawn
    x, z = _guard_player_spawn(5.0, 3.0)
    assert (x, z) == (5.0, 3.0), (
        f"(5,3) should stay unchanged, got ({x},{z})"
    )


# ── Item 1: Lights ──────────────────────────────────────────────

def test_world_environment_node_exists():
    """Item 1: Scene has a WorldEnvironment node."""
    _, parsed, _ = _compile_and_parse()
    env_nodes = [n for n in parsed["nodes"] if n["type"] == "WorldEnvironment"]
    assert len(env_nodes) >= 1, (
        f"expected at least 1 WorldEnvironment node, got {len(env_nodes)}"
    )
    assert env_nodes[0]["name"] == "WorldEnvironment"


def test_directional_light_node_exists():
    """Item 1: Scene has a DirectionalLight3D."""
    _, parsed, _ = _compile_and_parse()
    light_nodes = [n for n in parsed["nodes"] if n["type"] == "DirectionalLight3D"]
    assert len(light_nodes) >= 1, (
        f"expected at least 1 DirectionalLight3D node, got {len(light_nodes)}"
    )


def test_environment_sub_resource_exists():
    """Item 1: Scene has an Environment sub_resource."""
    _, parsed, _ = _compile_and_parse()
    sub_types = {s["type"] for s in parsed.get("sub_resources", [])}
    assert "Environment" in sub_types, (
        f"expected Environment sub_resource, got {sub_types}"
    )


# ── Item 2: Room shell ──────────────────────────────────────────

def test_visible_floor_mesh_exists():
    """Item 2: Scene has a FloorMesh MeshInstance3D child of Floor."""
    _, parsed, _ = _compile_and_parse()
    floor_nodes = [n for n in parsed["nodes"] if n["name"] == "FloorMesh"]
    assert len(floor_nodes) == 1, (
        f"expected 1 FloorMesh node, got {len(floor_nodes)}"
    )
    assert floor_nodes[0]["type"] == "MeshInstance3D"
    assert floor_nodes[0]["parent"] == "Floor"


def test_wall_nodes_exist():
    """Item 2: Scene has 4 wall StaticBody3D nodes."""
    _, parsed, _ = _compile_and_parse()
    for wall_name in ("WallN", "WallS", "WallE", "WallW"):
        wall_nodes = [n for n in parsed["nodes"] if n["name"] == wall_name]
        assert len(wall_nodes) == 1, f"expected 1 {wall_name} node, got {len(wall_nodes)}"
        assert wall_nodes[0]["type"] == "StaticBody3D"


def test_walls_have_collision_and_mesh_children():
    """Item 2: Each wall has a CollisionShape3D and MeshInstance3D child."""
    _, parsed, _ = _compile_and_parse()
    for wall_name in ("WallN", "WallS", "WallE", "WallW"):
        coll_children = [
            n for n in parsed["nodes"]
            if n["name"] == f"{wall_name}_collision" and n["type"] == "CollisionShape3D"
        ]
        assert len(coll_children) == 1, (
            f"{wall_name} missing collision child"
        )
        mesh_children = [
            n for n in parsed["nodes"]
            if n["name"] == f"{wall_name}_mesh" and n["type"] == "MeshInstance3D"
        ]
        assert len(mesh_children) == 1, (
            f"{wall_name} missing mesh child"
        )


def test_ceiling_node_exists():
    """Item 2: Scene has a Ceiling MeshInstance3D."""
    _, parsed, _ = _compile_and_parse()
    ceiling_nodes = [n for n in parsed["nodes"] if n["name"] == "Ceiling"]
    assert len(ceiling_nodes) == 1
    assert ceiling_nodes[0]["type"] == "MeshInstance3D"


def test_room_material_sub_resources_exist():
    """Item 2: Sub resources include StandardMaterial3D for floor/walls/ceiling."""
    _, parsed, _ = _compile_and_parse()
    sub_ids = {s["id"] for s in parsed.get("sub_resources", [])}
    for mat_id in ("floor_mat", "wall_mat", "ceiling_mat"):
        assert mat_id in sub_ids, f"expected {mat_id} sub_resource, got {sub_ids}"


def test_room_box_mesh_sub_resources_exist():
    """Item 2: Sub resources include BoxMeshes for floor, walls, ceiling."""
    _, parsed, _ = _compile_and_parse()
    sub_ids = {s["id"] for s in parsed.get("sub_resources", [])}
    for mesh_id in ("floor_vis_mesh", "wall_ns_mesh", "wall_ew_mesh", "ceiling_mesh"):
        assert mesh_id in sub_ids, f"expected {mesh_id} sub_resource, got {sub_ids}"


# ── Item 3: No-clip placement ───────────────────────────────────

def test_prop_half_extents_returns_half_sizes():
    """Item 3: _prop_half_extents returns (sx/2, sy/2, sz/2)."""
    hx, hy, hz = _prop_half_extents("table")
    assert hx == 0.6  # 1.2 / 2
    assert hy == 0.3  # 0.6 / 2
    assert hz == 0.4  # 0.8 / 2


def test_no_overlap_manifest_is_unchanged():
    """Item 3: Non-overlapping manifest is returned unchanged."""
    manifest: list[PlacedEntity] = [
        {"id": "a", "category": "table", "material": "worn_oak", "x": 5.0, "z": 5.0},
        {"id": "b", "category": "shelf", "material": "rough_granite", "x": -5.0, "z": -5.0},
    ]
    result = _resolve_prop_overlaps(manifest)
    assert len(result) == 2
    assert result[0]["x"] == 5.0
    assert result[0]["z"] == 5.0
    assert result[1]["x"] == -5.0
    assert result[1]["z"] == -5.0


def test_overlapping_props_are_separated():
    """Item 3: Two props at exactly the same position get pushed apart."""
    manifest: list[PlacedEntity] = [
        {"id": "a", "category": "table", "material": "worn_oak", "x": 0.0, "z": 0.0},
        {"id": "b", "category": "table", "material": "worn_oak", "x": 0.0, "z": 0.0},
    ]
    result = _resolve_prop_overlaps(manifest)
    # Props should be separated (x or z different)
    a_x = result[0].get("x", 0.0)
    a_z = result[0].get("z", 0.0)
    b_x = result[1].get("x", 0.0)
    b_z = result[1].get("z", 0.0)
    # At least one axis should differ
    diff = abs(a_x - b_x) + abs(a_z - b_z)
    assert diff > 0.01, (
        f"props not separated: a=({a_x},{a_z}) b=({b_x},{b_z})"
    )


def test_props_dont_overlap_npc():
    """Item 3: Props placed at NPC position get pushed away."""
    manifest: list[PlacedEntity] = [
        {"id": "a", "category": "table", "material": "worn_oak", "x": 0.0, "z": -2.0},
    ]
    result = _resolve_prop_overlaps(manifest, npc_x=0.0, npc_z=-2.0)
    # Prop should have been pushed away from NPC at (0, -2)
    px = result[0].get("x", 0.0)
    pz = result[0].get("z", 0.0)
    dist_from_npc = ((px - 0) ** 2 + (pz + 2) ** 2) ** 0.5
    assert dist_from_npc > 0.5, (
        f"prop too close to NPC: ({px},{pz}), dist={dist_from_npc}"
    )


def test_separation_is_deterministic():
    """Item 3: Same input → same output every time."""
    manifest: list[PlacedEntity] = [
        {"id": "a", "category": "table", "material": "worn_oak", "x": 0.0, "z": 0.0},
        {"id": "b", "category": "shelf", "material": "rough_granite", "x": 0.0, "z": 0.0},
        {"id": "c", "category": "cabinet", "material": "wrought_iron", "x": 0.0, "z": 0.0},
    ]
    results = [_resolve_prop_overlaps(manifest) for _ in range(5)]
    # All results should be byte-identical
    for i in range(1, len(results)):
        for j, entry in enumerate(results[i]):
            assert entry["x"] == results[0][j]["x"], (
                f"run {i} prop {j} x differs: {entry['x']} vs {results[0][j]['x']}"
            )
            assert entry["z"] == results[0][j]["z"], (
                f"run {i} prop {j} z differs"
            )


def test_scene_uses_separated_positions():
    """Item 3: The compiled .tscn uses positions from the separation pass."""
    # Same-position props should have different transforms in the tscn
    manifest_4: list[PlacedEntity] = [
        {"id": "p0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 0.0, "y": 0.0, "z": 0.0},
        {"id": "p1", "category": "shelf", "material": "rough_granite",
         "wear": 0.3, "x": 0.0, "y": 0.0, "z": 0.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "p0"
    text, _, _ = _compile_and_parse(quest_spec=spec, manifest=manifest_4)
    # Both props should appear in the text
    assert "p0" in text and "p1" in text
    # Their transforms should be different (separated)
    import re
    transforms = re.findall(r'Transform3D\([^)]+\)', text)
    # at least 2 prop transforms should exist and be different
    assert len(transforms) >= 2, f"expected at least 2 transforms, got {len(transforms)}"


# ── Item 4: Player body ─────────────────────────────────────────

def test_player_body_mesh_node_exists():
    """Item 4: Player has a BodyMesh MeshInstance3D child."""
    _, parsed, _ = _compile_and_parse()
    body_nodes = [n for n in parsed["nodes"] if n["name"] == "BodyMesh"]
    assert len(body_nodes) == 1, (
        f"expected 1 BodyMesh node, got {len(body_nodes)}"
    )
    assert body_nodes[0]["type"] == "MeshInstance3D"
    assert body_nodes[0]["parent"] == "Player"


def test_player_body_has_mesh_sub_resource():
    """Item 4: Sub resources include CapsuleMesh for player body."""
    _, parsed, _ = _compile_and_parse()
    sub_ids = {s["id"] for s in parsed.get("sub_resources", [])}
    assert "player_body_mesh" in sub_ids, (
        f"expected player_body_mesh sub_resource, got {sub_ids}"
    )
    assert "player_body_mat" in sub_ids, (
        f"expected player_body_mat sub_resource, got {sub_ids}"
    )
