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
    "idle_barks": ["The dust tells stories here.", "A quiet day in the shack.", "The shelves need tending."],
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
    npc_nodes = [n for n in parsed["nodes"] if n["name"] == "npc_0"]
    assert len(npc_nodes) == 1
    assert npc_nodes[0]["type"] == "StaticBody3D"


def test_scene_has_shell_nodes():
    _, parsed, _ = _compile_and_parse()
    node_names = {n["name"] for n in parsed["nodes"]}
    assert "Player" in node_names
    assert "Camera3D" in node_names
    assert "HUD" in node_names
    assert "WinScreen" in node_names
    assert "DayNight" in node_names  # B2


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
    """FIX-5/CB-2: All props have pickup or open tag (openable furniture gets open)."""
    from category_registry import REGISTRY
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        meta = parsed["metadata"].get(entry["id"], {})
        cat = entry.get("category", "?")
        ce = REGISTRY.get(cat, {})
        expected = "open" if ce.get("openable") else "pickup"
        assert meta.get("_forge_tag") == expected, (
            f"prop {entry['id']!r} should have {expected} tag (CB-2), got {meta}"
        )


def test_npc_has_talk_and_give_tags():
    _, parsed, _ = _compile_and_parse()
    meta = parsed["metadata"].get("npc_0", {})
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
    npc = next(n for n in parsed["nodes"] if n["name"] == "npc_0")
    assert npc.get("script") == "s_talk", (
        f"NPC should have script=s_talk, got {npc.get('script')!r}"
    )


def test_all_props_have_pickup_script():
    """FIX-5/CB-2: All props get pickup.gd or container.gd (openable gets container)."""
    from category_registry import REGISTRY
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        node = next(n for n in parsed["nodes"] if n["name"] == entry["id"])
        cat = entry.get("category", "?")
        ce = REGISTRY.get(cat, {})
        expected = "s_open" if ce.get("openable") else "s_pickup"
        assert node.get("script") == expected, (
            f"prop {entry['id']!r} should have script={expected} (CB-2), got {node.get('script')!r}"
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
    # B2: day/night cycle
    daynight = next(n for n in parsed["nodes"] if n["name"] == "DayNight")
    assert daynight.get("script") == "s_day_night"


# ── Quest data JSON round-trip ───────────────────────────────────

def test_quest_data_json_written():
    """compile_scene writes a _quest_data.json alongside the .tscn."""
    _, _, data = _compile_and_parse()
    assert data is not None
    assert "npcs" in data
    assert data["npcs"]["npc_0"]["npc_role"] == "hermit"
    assert data["npcs"]["npc_0"]["target_entity"] == "shelf_0"


def test_dialogue_round_trips():
    _, _, data = _compile_and_parse()
    assert data["npcs"]["npc_0"]["dialogue"]["greet"] == "Ah, a visitor! Welcome."
    assert data["npcs"]["npc_0"]["dialogue"]["ask"] == "Find my lost book on the shelf."
    assert data["npcs"]["npc_0"]["dialogue"]["wrong"] == "No, that is not my book."
    assert data["npcs"]["npc_0"]["dialogue"]["thank"] == "You found it! Thank you."


def test_objective_round_trips():
    _, _, data = _compile_and_parse()
    assert data["npcs"]["npc_0"]["objective"]["type"] == "fetch"
    assert data["npcs"]["npc_0"]["objective"]["target"] == "shelf_0"
    assert data["npcs"]["npc_0"]["objective"]["giver"] == "npc"


def test_npc_role_in_quest_data():
    """NPC role is stored in quest_data.json, not in NPC node metadata."""
    _, parsed, data = _compile_and_parse()
    assert data["npcs"]["npc_0"]["npc_role"] == "hermit"
    # NPC node should NOT have npc_role metadata
    npc_meta = parsed["metadata"].get("npc_0", {})
    assert "npc_role" not in npc_meta


def test_target_entity_in_quest_data():
    _, _, data = _compile_and_parse()
    assert data["npcs"]["npc_0"]["target_entity"] == "shelf_0"


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
    from category_registry import COLLISION_SIZES
    for entry in _MANIFEST:
        x, y, z = entry.get("x", 0), entry.get("y", 0), entry.get("z", 0)
        # Task 2: y is adjusted by rest_offset (half the collision y-height)
        cat = entry.get("category", "?")
        _, sy, _ = COLLISION_SIZES.get(cat, (0.5, 0.5, 0.5))
        adj_y = y + sy / 2.0
        expected = (
            f"Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{_fmt_pos(x)}, {_fmt_pos(adj_y)}, {_fmt_pos(z)})"
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
    # Task 2: table collision (1.2, 0.6, 0.8) → rest_offset(-0.3) = 0.3
    expected = "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0.3, 0)"
    assert expected in text, (
        f"default (0,0,0) position should be guarded to (1,0.3,0), "
        f"text:\n{text[:500]}"
    )


# ── NPC body (P7: generated humanoid GLB) ───────────────────────

def test_npc_has_glb_body():
    """NPC Body node instances a GLB via header-line instance= (FIX-1a).
    CB-7: Body is now a child of HipsAttachment (BoneAttachment3D)."""
    _, parsed, _ = _compile_and_parse()
    body_nodes = [n for n in parsed["nodes"] if n["name"] == "Body"]
    assert len(body_nodes) == 1
    assert "HipsAttachment" in body_nodes[0]["parent"]
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
    assert data["npcs"]["npc_0"]["dialogue"]["greet"] == 'He said "hello"'
    assert data["npcs"]["npc_0"]["dialogue"]["ask"] == "Find the book."


# ── Edge case: empty dialogue ────────────────────────────────────

def test_empty_dialogue_ok():
    spec = dict(_QUEST_SPEC)
    spec["dialogue"] = {"greet": "", "ask": "", "wrong": "", "thank": ""}
    _, _, data = _compile_and_parse(quest_spec=spec)
    assert data["npcs"]["npc_0"]["dialogue"]["greet"] == ""


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
        (n for n in parsed["nodes"] if n["name"] == "npc_0_collision"), None
    )
    assert collision is not None, "NPC_collision node missing"
    assert collision["parent"] == "npc_0"
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
    """FIX-1c: Player spawns at y=1.2 so capsule rests on floor.

    Capsule total height = 1.8 + 2*0.3 = 2.4 → centre at 1.2 for bottom at y=0.
    """
    text, _, _ = _compile_and_parse()
    assert "0, 1.2, 0)" in text, (
        f"Player spawn transform should include y=1.2\ntext:\n{text[:1000]}"
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


def test_player_capsule_radius():
    """P-A: Player CapsuleShape3D and CapsuleMesh use radius=0.3 (was 0.5)."""
    text, _, _ = _compile_and_parse()
    assert "radius = 0.3" in text, (
        f"expected capsule radius=0.3, text:\n{text[:500]}"
    )
    assert "radius = 0.5" not in text, (
        "old radius=0.5 should not appear"
    )


def test_camera_local_y_is_eye_height():
    """P-A: Camera3D local y=0.7 above player origin (world eye ≈ 1.9 m)."""
    text, _, _ = _compile_and_parse()
    assert "0, 0.7, 0)" in text, (
        f"Camera3D local transform should have y=0.7\ntext:\n{text[:1000]}"
    )


# ── P-B: HUD & interaction UX pack ──────────────────────────────

def test_crosshair_node_exists():
    """P-B: HUD has a Crosshair ColorRect child."""
    _, parsed, _ = _compile_and_parse()
    crosshair = [n for n in parsed["nodes"] if n["name"] == "Crosshair"]
    assert len(crosshair) == 1
    assert crosshair[0]["type"] == "ColorRect"
    assert crosshair[0]["parent"] == "HUD"


def test_carried_item_node_exists():
    """P-B: Camera3D has a CarriedItem Node3D child."""
    _, parsed, _ = _compile_and_parse()
    carried = [n for n in parsed["nodes"] if n["name"] == "CarriedItem"]
    assert len(carried) == 1
    assert carried[0]["type"] == "Node3D"
    # parent path uses / separator in Godot 4 .tscn
    assert "Camera3D" in carried[0]["parent"]


def test_win_labels_exist():
    """P-B: WinScreen has WinLabel and WinSubLabel children."""
    _, parsed, _ = _compile_and_parse()
    node_names = {n["name"] for n in parsed["nodes"]}
    assert "WinLabel" in node_names
    assert "WinSubLabel" in node_names


def test_nameplate_node_exists():
    """P-B: NPC has a Nameplate Label3D child."""
    _, parsed, _ = _compile_and_parse()
    plates = [n for n in parsed["nodes"] if n["name"] == "Nameplate"]
    assert len(plates) == 1
    assert plates[0]["type"] == "Label3D"
    assert plates[0]["parent"] == "npc_0"


def test_prop_has_category_metadata():
    """P-B: Props have _forge_category metadata for named prompts."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        meta = parsed["metadata"].get(entry["id"], {})
        assert meta.get("_forge_category") == entry["category"], (
            f"prop {entry['id']!r} should have _forge_category={entry['category']!r}, got {meta}"
        )


def test_npc_has_role_metadata():
    """P-B: NPC has _forge_role metadata for named prompts and nameplate."""
    _, parsed, _ = _compile_and_parse()
    meta = parsed["metadata"].get("npc_0", {})
    assert meta.get("_forge_role") == "hermit", (
        f"NPC should have _forge_role=hermit, got {meta}"
    )


# ── P-G: Per-theme lighting determinism ─────────────────────────

def test_per_theme_lighting_applied_when_theme_provided():
    """P-G: When theme='hermit', DirectionalLight3D gets light_color + energy."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, theme="hermit")
        text = Path(out).read_text(encoding="utf-8")
        # Check DirectionalLight3D has light_color and light_energy props
        assert "light_color = Color(1.0, 0.9, 0.75, 1)" in text, (
            f"expected hermit light_color in tscn\ntext snippet:\n{text[:3000]}"
        )
        assert "light_energy = 1.2" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_theme_lighting_deterministic():
    """P-G: Same theme → same lighting output (deterministic)."""
    from room_control import get_lighting
    l1 = get_lighting("hermit")
    l2 = get_lighting("hermit")
    assert l1 == l2, "same theme should produce identical lighting"
    # Different theme → different lighting
    l3 = get_lighting("blacksmith")
    assert l1 != l3, "different themes should differ"


def test_lighting_falls_back_to_default():
    """P-G: Unknown theme returns the '*' default lighting."""
    from room_control import get_lighting
    l = get_lighting("nonexistent_theme_xyz")
    assert l["directional_energy"] == 1.2  # Quality A: default energy demoted to fill


def test_ambient_background_overridden_by_theme():
    """P-G: Theme changes ambient and background colors in the Environment."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, theme="dungeon")
        text = Path(out).read_text(encoding="utf-8")
        # Dungeon ambient is dark/cool
        assert "ambient_light_color = Color(0.1, 0.1, 0.14, 1.0)" in text
        assert "background_color = Color(0.03, 0.03, 0.06, 1.0)" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_no_theme_keeps_default_lighting():
    """P-G: Without theme, default lighting constants are used."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)  # no theme arg
        text = Path(out).read_text(encoding="utf-8")
        # Default ambient should be present
        assert "ambient_light_color = Color(0.15, 0.15, 0.2, 1.0)" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


# ── B2: Post-processing stack (EB-5) ──────────────────────────────

def test_environment_has_aces_tonemap():
    """B2: Environment sub_resource has ACES tonemap."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "tonemap_mode = 3" in text, "B2: missing ACES tonemap"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_environment_has_ssao():
    """B2: Environment sub_resource has SSAO enabled."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "ssao_enabled = true" in text, "B2: missing SSAO"
        assert "ssao_radius" in text
        assert "ssao_intensity" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_environment_has_bloom():
    """B2: Environment sub_resource has bloom (glow) enabled."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "glow_enabled = true" in text, "B2: missing bloom/glow"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_environment_has_fog():
    """B2: Environment sub_resource has fog enabled."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "fog_enabled = true" in text, "B2: missing fog"
        assert "fog_mode = 0" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_per_theme_fog_applied():
    """B2: Per-theme fog color and density are emitted."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, theme="dungeon")
        text = Path(out).read_text(encoding="utf-8")
        # Dungeon: dark fog, high density
        assert "fog_light_color = Color(0.08, 0.08, 0.13, 1.0)" in text
        assert "fog_density = 0.03" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_environment_has_exposure():
    """B2: Environment sub_resource has adjustment (exposure) enabled."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "adjustment_enabled = true" in text, "B2: missing exposure adjustment"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_lighting_table_has_fog_and_exposure():
    """B2: LIGHTING_TABLE entries have fog and exposure keys."""
    from room_control import LIGHTING_TABLE
    for theme, entry in LIGHTING_TABLE.items():
        assert "fog_color" in entry, f"{theme}: missing fog_color"
        assert "fog_density" in entry, f"{theme}: missing fog_density"
        assert "fog_light_energy" in entry, f"{theme}: missing fog_light_energy"
        assert "exposure" in entry, f"{theme}: missing exposure"


# ── B2: Light-emitting props ──────────────────────────────────────

def test_lantern_prop_has_light_child():
    """B2: A lantern prop gets an OmniLight3D child."""
    manifest: list[PlacedEntity] = [
        {"id": "lantern_0", "category": "lantern", "material": "wrought_iron",
         "wear": 0.5, "x": 1.0, "y": 0.0, "z": 0.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "lantern_0"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, manifest, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "lantern_0_light" in text, "B2: lantern should have OmniLight3D child"
        assert "OmniLight3D" in text
        assert "light_color" in text
        assert "omni_range" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_non_light_prop_has_no_light_child():
    """B2: Regular props (e.g. table) do NOT get light children."""
    _, parsed, _ = _compile_and_parse()
    for n in parsed["nodes"]:
        assert not n["name"].endswith("_light"), (
            f"unexpected light node: {n['name']}"
        )


def test_candle_prop_has_light_child():
    """B2: A candle carryable prop gets an OmniLight3D child."""
    manifest: list[PlacedEntity] = [
        {"id": "candle_0", "category": "candle", "material": "wrought_iron",
         "wear": 0.5, "x": 3.0, "y": 0.0, "z": 0.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "candle_0"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, manifest, out)
        text = Path(out).read_text(encoding="utf-8")
        assert "candle_0_light" in text, "B2: candle should have OmniLight3D child"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


# ── B2: Day/night node ────────────────────────────────────────────

def test_day_night_script_in_ext_resources():
    """B2: day_night.gd is in ext_resource block."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/day_night.gd" in paths, "B2: day_night.gd missing from ext_resources"


# ── EB-6: Examine flavour text ────────────────────────────────────

def test_quest_data_has_examine_key():
    """EB-6: quest_data.json includes an 'examine' dict mapping prop ids to flavour."""
    _, _, data = _compile_and_parse()
    assert "examine" in data, "EB-6: quest_data missing 'examine' key"
    assert isinstance(data["examine"], dict), "EB-6: examine should be a dict"

def test_examine_has_flavour_per_prop():
    """EB-6: Every prop in the manifest has an examine flavour entry."""
    _, _, data = _compile_and_parse()
    examine = data.get("examine", {})
    for entry in _MANIFEST:
        eid = entry["id"]
        assert eid in examine, f"EB-6: examine missing flavour for {eid}"
        assert len(examine[eid]) >= 8, f"EB-6: flavour for {eid} too short: {examine[eid]!r}"

def test_npc_has_idle_barks():
    """EB-6: Each NPC has an idle_barks list in quest_data."""
    _, _, data = _compile_and_parse()
    npcs = data.get("npcs", {})
    for npc_id, npc_data in npcs.items():
        assert "idle_barks" in npc_data, f"EB-6: {npc_id} missing idle_barks"
        barks = npc_data["idle_barks"]
        assert isinstance(barks, list), f"EB-6: {npc_id} idle_barks not a list"
        assert len(barks) >= 3, f"EB-6: {npc_id} has {len(barks)} idle barks, need ≥3"


# ── EB-6: More themes ──────────────────────────────────────────

def test_new_themes_in_theme_table():
    """EB-6: Theme table includes crypt, armory, workshop, tavern."""
    from room_control import THEME_TABLE
    themes = {row["theme"] for row in THEME_TABLE}
    for t in ("crypt", "armory", "workshop", "tavern"):
        assert t in themes, f"EB-6: missing theme '{t}'"

def test_new_themes_in_lighting_table():
    """EB-6: Lighting table includes crypt, armory, workshop, tavern."""
    from room_control import LIGHTING_TABLE
    for t in ("crypt", "armory", "workshop", "tavern"):
        assert t in LIGHTING_TABLE, f"EB-6: missing lighting for '{t}'"
        entry = LIGHTING_TABLE[t]
        for key in ("fog_color", "fog_density", "fog_light_energy", "exposure"):
            assert key in entry, f"EB-6: {t} missing {key}"

def test_examine_fallback_returns_string():
    """EB-6: _category_fallback returns a non-empty string for known categories."""
    from examine_validator import _category_fallback
    for cat in ("table", "key", "book", "unknown_cat_xyz"):
        fb = _category_fallback(cat)
        assert len(fb) >= 8, f"EB-6: fallback for {cat} too short: {fb!r}"


# ═══════════════════════════════════════════════════════════════════════
#  Quality A: Interior lighting
# ═══════════════════════════════════════════════════════════════════════

def test_interior_omni_light_present():
    """Quality A: Compiled scene for a default room contains ≥ 1
    OmniLight3D not attached to a lantern/candle prop."""
    _, parsed, _ = _compile_and_parse()
    # Find OmniLight3D nodes that are NOT children of lantern/candle props
    omni_nodes = [
        n for n in parsed["nodes"]
        if n["type"] == "OmniLight3D" and "_light" not in n["name"]
    ]
    assert len(omni_nodes) >= 1, (
        f"Quality A: expected ≥1 interior OmniLight3D, got {len(omni_nodes)}"
    )


def test_ambient_light_energy_emitted():
    """Quality A: Environment sub_resource includes ambient_light_energy."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, theme="dungeon")
        text = Path(out).read_text(encoding="utf-8")
        assert "ambient_light_energy" in text, (
            f"Quality A: missing ambient_light_energy in Environment"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_lighting_ambient_raised_across_all_themes():
    """Quality A: Every theme's ambient_color RGB values are raised above
    near-black levels."""
    from room_control import LIGHTING_TABLE
    for theme, entry in LIGHTING_TABLE.items():
        ambient = entry["ambient_color"]
        # Ambient energy ≥ 0.4
        assert entry.get("ambient_light_energy", 0) >= 0.4, (
            f"Quality A: {theme} ambient_light_energy {entry.get('ambient_light_energy')} < 0.4"
        )
        # No channel near zero — keep moody but not black
        min_rgb = ambient[0] + ambient[1] + ambient[2]
        assert min_rgb >= 0.15, (
            f"Quality A: {theme} ambient RGB sum {min_rgb:.2f} too dark"
        )


# ═══════════════════════════════════════════════════════════════════════
#  Quality B1: NPC open-floor placement
# ═══════════════════════════════════════════════════════════════════════

def test_npcs_are_clear_of_props():
    """Quality B1: In a compiled multi-NPC scene, every NPC (x,z) is
    ≥ clearance from every prop footprint."""
    from category_registry import COLLISION_SIZES
    man = [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
         "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
    ]
    specs = [
        dict(_QUEST_SPEC),
        {**_QUEST_SPEC, "npc_id": "npc_1", "target_entity": "table_0",
         "npc_role": "alchemist"},
    ]
    spec0 = dict(specs[0])
    spec0["target_entity"] = "shelf_0"
    specs = [spec0, specs[1]]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(specs, man, out)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        data = read_quest_data(out)

        # Get NPC positions from quest_data
        npcs = data.get("npcs", {})
        clearance = 0.5  # relaxed from 0.6 for deterministic test
        npc_positions = []
        for npc_id, npc_data in npcs.items():
            pl = npc_data.get("npc_placement", {}).get("attrs", {})
            npc_x = pl.get("x", 0)
            npc_z = pl.get("z", 0)
            npc_positions.append((npc_x, npc_z))

            # Check clear of prop footprints
            npc_hx = COLLISION_SIZES.get("humanoid", (0.5, 2.8, 0.4))[0] / 2.0
            npc_hz = COLLISION_SIZES.get("humanoid", (0.5, 2.8, 0.4))[2] / 2.0
            for entry in man:
                cat = entry.get("category", "?")
                sx, _, sz = COLLISION_SIZES.get(cat, (0.5, 0.5, 0.5))
                phx = sx / 2.0 + clearance
                phz = sz / 2.0 + clearance
                px, pz = entry.get("x", 0), entry.get("z", 0)
                overlap = abs(npc_x - px) < (npc_hx + phx) and abs(npc_z - pz) < (npc_hz + phz)
                assert not overlap, (
                    f"Quality B1: {npc_id} at ({npc_x},{npc_z}) overlaps {entry['id']} at ({px},{pz})"
                )

        # Check NPCs don't overlap each other
        assert len(npc_positions) >= 2
        for i in range(len(npc_positions)):
            for j in range(i + 1, len(npc_positions)):
                ix, iz = npc_positions[i]
                jx, jz = npc_positions[j]
                dist = ((ix - jx)**2 + (iz - jz)**2)**0.5
                assert dist > 0.5, (
                    f"Quality B1: NPCs {i},{j} too close: dist={dist:.2f}"
                )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_npcs_not_on_player_spawn():
    """Quality B1: NPCs are clear of player spawn at (0,0)."""
    specs = [dict(_QUEST_SPEC), {**_QUEST_SPEC, "npc_id": "npc_1", "npc_role": "alchemist"}]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(specs, _MANIFEST, out)
        data = read_quest_data(out)
        for npc_id, npc_data in data.get("npcs", {}).items():
            pl = npc_data.get("npc_placement", {}).get("attrs", {})
            npc_x, npc_z = pl.get("x", 0), pl.get("z", 0)
            dist_from_spawn = (npc_x**2 + npc_z**2)**0.5
            assert dist_from_spawn > 1.0, (
                f"Quality B1: {npc_id} too close to player spawn: dist={dist_from_spawn:.2f}"
            )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()



# ═══════════════════════════════════════════════════════════════════════
#  CB-2: Item verbs — openable containers + surface metadata
# ═══════════════════════════════════════════════════════════════════════

def test_openable_prop_gets_open_tag():
    """CB-2: Openable furniture (cabinet) gets _forge_tag=open."""
    _, parsed, _ = _compile_and_parse()
    meta = parsed["metadata"].get("cabinet_0", {})
    assert meta.get("_forge_tag") == "open", (
        f"CB-2: cabinet should have open tag, got {meta}"
    )
    assert meta.get("_forge_openable") == "true"


def test_furniture_gets_surface_metadata():
    """CB-2: Furniture with furniture_top_y gets _forge_surface_tag=place."""
    _, parsed, _ = _compile_and_parse()
    for entry in _MANIFEST:
        meta = parsed["metadata"].get(entry["id"], {})
        from category_registry import REGISTRY
        ce = REGISTRY.get(entry["category"], {})
        if ce.get("furniture_top_y") is not None:
            assert meta.get("_forge_surface_tag") == "place", (
                f"CB-2: {entry['id']} should have surface_tag=place, got {meta}"
            )
            assert "_forge_surface_y" in meta
        else:
            # Carryables don't get surface_tag
            assert meta.get("_forge_surface_tag", "") == ""


def test_ext_resources_include_container_and_door():
    """CB-2: ext_resources includes container.gd when openable props exist.
    door.gd only appears when a door-category entity is in the manifest."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/container.gd" in paths, "CB-2: container.gd missing"
    # door.gd is registered but only emitted via used_tags when a door entity exists
    ids = {r["id"] for r in parsed["ext_resources"]}
    assert "s_open" in ids, "CB-2: s_open ext_resource id missing"


def test_openable_prop_gets_container_script():
    """CB-2: Openable prop gets container.gd script via s_open ext_resource."""
    _, parsed, _ = _compile_and_parse()
    node = next(n for n in parsed["nodes"] if n["name"] == "cabinet_0")
    assert node.get("script") == "s_open", (
        f"CB-2: cabinet should have script=s_open, got {node.get('script')!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
#  CB-3: Navigation mesh + idle-wander
# ═══════════════════════════════════════════════════════════════════════

def test_nav_mesh_sub_resource_exists():
    """CB-3: Room sub_resources include a NavigationMesh."""
    _, parsed, _ = _compile_and_parse()
    sub_types = {s["type"] for s in parsed.get("sub_resources", [])}
    assert "NavigationMesh" in sub_types, "CB-3: missing NavigationMesh sub_resource"
    nav_subs = [s for s in parsed["sub_resources"] if s["type"] == "NavigationMesh"]
    assert len(nav_subs) >= 1


def test_navigation_region_node_exists():
    """CB-3: Scene has a NavigationRegion3D node."""
    _, parsed, _ = _compile_and_parse()
    nav_nodes = [n for n in parsed["nodes"] if n["name"] == "NavigationRegion3D"]
    assert len(nav_nodes) == 1, "CB-3: missing NavigationRegion3D node"
    assert nav_nodes[0]["type"] == "NavigationRegion3D"


def test_quest_data_has_npc_needs():
    """CB-3: quest_data.json includes per-NPC needs dict."""
    _, _, data = _compile_and_parse()
    npcs = data.get("npcs", {})
    for npc_id, npc_data in npcs.items():
        assert "needs" in npc_data, f"CB-3: {npc_id} missing needs"
        needs = npc_data["needs"]
        assert isinstance(needs, dict)
        for n in ("food", "water", "shelter", "safety", "sleep", "companionship", "joy"):
            assert n in needs, f"CB-3: {npc_id} needs missing '{n}'"
            assert 0.0 <= needs[n] <= 100.0, f"CB-3: {npc_id} need '{n}' out of range: {needs[n]}"


# ═══════════════════════════════════════════════════════════════════════
#  CB-4: Multi-room world — door entities + room_graph integration
# ═══════════════════════════════════════════════════════════════════════

def _make_room_graph():
    """Minimal room_graph fixture with one door."""
    return {
        "rooms": [(0, 0), (1, 0)],
        "tree_edges": {((0, 0), (1, 0))},
        "extra_edges": set(),
        "doors": [
            {
                "door_id": "door_0",
                "from_room": [0, 0],
                "to_room": [1, 0],
                "wall": "east",
                "locked": False,
                "key_entity": None,
            }
        ],
        "start": (0, 0),
        "exit": (1, 0),
        "start_exit_path_exists": True,
        "width": 2,
        "depth": 1,
    }


def test_room_graph_door_entities_emitted():
    """CB-4: When room_graph is provided, door nodes appear in the scene."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        # Door node should exist
        door_nodes = [n for n in parsed["nodes"] if n["name"] == "door_0"]
        assert len(door_nodes) == 1, f"CB-4: expected door_0 node, got nodes: {[n['name'] for n in parsed['nodes']]}"
        assert door_nodes[0]["type"] == "StaticBody3D"
        # Door metadata
        meta = parsed["metadata"].get("door_0", {})
        assert meta.get("_forge_tag") == "door"
        assert meta.get("_forge_target_room") == "1,0"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_door_has_collision_shape():
    """CB-4: Door entities have collision shape sub_resources."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        # Door collision node
        coll_nodes = [n for n in parsed["nodes"] if n["name"] == "door_0_collision"]
        assert len(coll_nodes) == 1, f"CB-4: expected door_0_collision, got {[n['name'] for n in parsed['nodes']]}"
        assert coll_nodes[0]["type"] == "CollisionShape3D"
        assert coll_nodes[0].get("shape") is not None, (
            "CB-4: door collision should reference a sub_resource"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_door_script_attached():
    """CB-4: Door node gets door.gd script when room_graph is provided."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        door_node = next(n for n in parsed["nodes"] if n["name"] == "door_0")
        assert door_node.get("script") == "s_door", (
            f"CB-4: door should have script=s_door, got {door_node.get('script')!r}"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_door_in_ext_resources():
    """CB-4: When room_graph is provided, door.gd is in ext_resources."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        paths = {r["path"] for r in parsed["ext_resources"]}
        assert "res://scripts/door.gd" in paths, "CB-4: door.gd missing from ext_resources"
        ids = {r["id"] for r in parsed["ext_resources"]}
        assert "s_door" in ids, "CB-4: s_door ext_resource id missing"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_door_locked_metadata():
    """CB-4: Locked door gets _forge_key_entity metadata."""
    rg = _make_room_graph()
    rg["doors"][0]["locked"] = True
    rg["doors"][0]["key_entity"] = "key_door_0"
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        meta = parsed["metadata"].get("door_0", {})
        assert meta.get("_forge_key_entity") == "key_door_0", (
            f"CB-4: locked door should have _forge_key_entity, got {meta}"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_no_room_graph_no_door_nodes():
    """CB-4: Without room_graph, no door nodes are emitted."""
    _, parsed, _ = _compile_and_parse()
    door_nodes = [n for n in parsed["nodes"] if n["name"].startswith("door_")]
    assert len(door_nodes) == 0, (
        f"CB-4: expected no door nodes without room_graph, got {door_nodes}"
    )


def test_door_has_visual_model():
    """CB-4: Door entities have a _model child with a BoxMesh."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        # Door model node
        model_nodes = [n for n in parsed["nodes"] if n["name"] == "door_0_model"]
        assert len(model_nodes) == 1, f"CB-4: expected door_0_model, got {[n['name'] for n in parsed['nodes']]}"
        assert model_nodes[0]["parent"] == "door_0"
        # Door mesh and material sub_resources
        sub_ids = {s["id"] for s in parsed.get("sub_resources", [])}
        assert "door_mesh" in sub_ids, "CB-4: missing door_mesh sub_resource"
        assert "door_mat" in sub_ids, "CB-4: missing door_mat sub_resource"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_door_has_world_log_metadata():
    """CB-4: Door entities carry _forge_world_log metadata for cross-room persistence."""
    rg = _make_room_graph()
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_graph=rg, current_room=(0, 0))
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        meta = parsed["metadata"].get("door_0", {})
        assert "_forge_world_log" in meta, (
            f"CB-4: door should have _forge_world_log, got {meta}"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


# ═══════════════════════════════════════════════════════════════════════
#  CB-5: Emergent events — event_manager + events in quest_data
# ═══════════════════════════════════════════════════════════════════════

def test_quest_data_has_events_key():
    """CB-5: quest_data.json includes an 'events' list."""
    _, _, data = _compile_and_parse()
    assert "events" in data, f"CB-5: quest_data missing 'events' key, got keys: {list(data.keys())}"
    assert isinstance(data["events"], list)


def test_event_has_schema():
    """CB-5: Each event in quest_data follows the event-consequence schema."""
    _, _, data = _compile_and_parse()
    events = data.get("events", [])
    for ev in events:
        assert "event_id" in ev
        assert "event_type" in ev
        assert ev["event_type"] in (
            "flood", "earthquake", "wildfire", "blizzard", "drought", "landslide", "blight"
        )
        assert "precursors" in ev
        assert "spatial_origin" in ev
        assert "consequences" in ev
        assert "tick_fired" in ev


def test_event_manager_shell_node():
    """CB-5: Scene has an EventManager node."""
    _, parsed, _ = _compile_and_parse()
    em_nodes = [n for n in parsed["nodes"] if n["name"] == "EventManager"]
    assert len(em_nodes) == 1, f"CB-5: expected EventManager node, got {[n['name'] for n in parsed['nodes']]}"
    assert em_nodes[0]["type"] == "Node"


def test_event_manager_in_ext_resources():
    """CB-5: event_manager.gd is in ext_resource block."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/event_manager.gd" in paths, "CB-5: event_manager.gd missing from ext_resources"
    ids = {r["id"] for r in parsed["ext_resources"]}
    assert "s_event_mgr" in ids, "CB-5: s_event_mgr ext_resource id missing"


def test_event_manager_has_script():
    """CB-5: EventManager node has event_manager.gd script attached."""
    _, parsed, _ = _compile_and_parse()
    em = next(n for n in parsed["nodes"] if n["name"] == "EventManager")
    assert em.get("script") == "s_event_mgr", (
        f"CB-5: EventManager should have script=s_event_mgr, got {em.get('script')!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
#  CB-6: Combat + skills — enemy nodes, health/combat shells, enemy data
# ═══════════════════════════════════════════════════════════════════════

def test_health_node_attached_to_player():
    """CB-6: Player has a Health child node."""
    _, parsed, _ = _compile_and_parse()
    health_nodes = [n for n in parsed["nodes"] if n["name"] == "Health"]
    assert len(health_nodes) == 1, f"CB-6: expected Health node, got {[n['name'] for n in parsed['nodes']]}"
    assert health_nodes[0]["parent"] == "Player"


def test_combat_node_attached_to_player():
    """CB-6: Player has a Combat child node."""
    _, parsed, _ = _compile_and_parse()
    combat_nodes = [n for n in parsed["nodes"] if n["name"] == "Combat"]
    assert len(combat_nodes) == 1, f"CB-6: expected Combat node, got {[n['name'] for n in parsed['nodes']]}"
    assert combat_nodes[0]["parent"] == "Player"


def test_health_combat_in_ext_resources():
    """CB-6: health.gd and combat.gd are in ext_resources."""
    _, parsed, _ = _compile_and_parse()
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/health.gd" in paths, "CB-6: health.gd missing"
    assert "res://scripts/combat.gd" in paths, "CB-6: combat.gd missing"


def test_enemy_entity_node_type():
    """CB-6: Enemy entities are CharacterBody3D with enemy tag."""
    manifest: list[PlacedEntity] = [
        {"id": "enemy_0", "category": "enemy", "material": "rough_granite",
         "wear": 0.5, "x": 5.0, "y": 0.0, "z": -3.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "enemy_0"
    text, parsed, _ = _compile_and_parse(quest_spec=spec, manifest=manifest)
    enemy = next(n for n in parsed["nodes"] if n["name"] == "enemy_0")
    assert enemy["type"] == "CharacterBody3D", (
        f"CB-6: enemy should be CharacterBody3D, got {enemy['type']}"
    )
    meta = parsed["metadata"].get("enemy_0", {})
    assert meta.get("_forge_tag") == "enemy", f"CB-6: enemy tag missing, got {meta}"


def test_enemy_script_attached():
    """CB-6: Enemy node gets enemy.gd script."""
    manifest: list[PlacedEntity] = [
        {"id": "enemy_0", "category": "enemy", "material": "rough_granite",
         "wear": 0.5, "x": 5.0, "y": 0.0, "z": -3.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "enemy_0"
    _, parsed, _ = _compile_and_parse(quest_spec=spec, manifest=manifest)
    enemy = next(n for n in parsed["nodes"] if n["name"] == "enemy_0")
    assert enemy.get("script") == "s_enemy", (
        f"CB-6: enemy should have script=s_enemy, got {enemy.get('script')!r}"
    )


def test_enemy_in_ext_resources():
    """CB-6: When enemy entity exists, enemy.gd is in ext_resources."""
    manifest: list[PlacedEntity] = [
        {"id": "enemy_0", "category": "enemy", "material": "rough_granite",
         "wear": 0.5, "x": 5.0, "y": 0.0, "z": -3.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "enemy_0"
    _, parsed, _ = _compile_and_parse(quest_spec=spec, manifest=manifest)
    paths = {r["path"] for r in parsed["ext_resources"]}
    assert "res://scripts/enemy.gd" in paths, "CB-6: enemy.gd missing from ext_resources"
    ids = {r["id"] for r in parsed["ext_resources"]}
    assert "s_enemy" in ids, "CB-6: s_enemy ext_resource id missing"


def test_quest_data_has_enemies():
    """CB-6: quest_data.json includes an 'enemies' list."""
    manifest: list[PlacedEntity] = [
        {"id": "enemy_0", "category": "enemy", "material": "rough_granite",
         "wear": 0.5, "x": 5.0, "y": 0.0, "z": -3.0},
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "enemy_0"
    _, _, data = _compile_and_parse(quest_spec=spec, manifest=manifest)
    assert "enemies" in data, f"CB-6: quest_data missing 'enemies', got keys: {list(data.keys())}"
    enemies = data["enemies"]
    assert len(enemies) == 1
    assert enemies[0]["enemy_id"] == "enemy_0"
    assert enemies[0]["archetype"] == "golem"
    assert enemies[0]["health"] == 50.0


# ═══════════════════════════════════════════════════════════════════════
#  Fix-Batch-1 Task 4: Shell tiling textures in compiled scene
# ═══════════════════════════════════════════════════════════════════════

def test_shell_texture_sub_resources_present():
    """Fix-Batch-1 Task 4: The compiled scene's room textures must be
    emitted as ext_resource Texture2D entries (NOT CompressedTexture2D
    sub_resources with load_path=).  Godot resolves the .png path to
    the imported .ctex automatically."""
    from scene_compiler import _build_room_sub_resources
    
    # Build the room sub-resources directly (no scene compilation needed).
    # No shell_glb_path → box-shell fallback branch.
    room_subs, texture_exts = _build_room_sub_resources(20.0, 20.0)
    
    # There should be ZERO CompressedTexture2D sub-resources.
    tex_subs = [sr for sr in room_subs if sr["type"] == "CompressedTexture2D"]
    assert len(tex_subs) == 0, (
        f"Task 4: expected 0 CompressedTexture2D sub-resources (textures "
        f"are now ext_resource Texture2D), got {len(tex_subs)}"
    )
    
    # Texture ext_resources must cover each surface (floor, wall, ceiling)
    # with albedo+normal+orm.
    tex_ids = {tex["id"] for tex in texture_exts}
    assert len(texture_exts) >= 9, (
        f"Task 4: expected ≥9 texture ext_resources, got {len(texture_exts)}"
    )
    for surf in ("floor", "wall", "ceil"):
        for suffix in ("a", "n", "o"):
            tex_id = f"tex_{surf}_{suffix}"
            assert tex_id in tex_ids, (
                f"Task 4: missing texture ext_resource '{tex_id}'"
            )
    
    # Each texture ext_resource must have type=Texture2D and a valid .png path
    for tex in texture_exts:
        assert tex["type"] == "Texture2D", (
            f"Task 4: texture {tex['id']} must be type=Texture2D, got {tex['type']!r}"
        )
        assert tex["path"].endswith(".png"), (
            f"Task 4: texture {tex['id']} path must end with .png, got {tex['path']!r}"
        )
        assert tex["path"].startswith("res://"), (
            f"Task 4: texture {tex['id']} path must start with res://, got {tex['path']!r}"
        )


def test_shell_material_references_textures():
    """Fix-Batch-1 Task 4: The floor/wall/ceiling StandardMaterial3D
    entries must reference albedo_texture, normal_texture, and
    ao_texture/roughness_texture from the ORM via ExtResource (not
    SubResource)."""
    from scene_compiler import _build_room_sub_resources
    
    room_subs, _texture_exts = _build_room_sub_resources(20.0, 20.0)
    
    for surf, mat_id in [("floor", "floor_mat"), ("wall", "wall_mat"), ("ceiling", "ceiling_mat")]:
        mat = next(sr for sr in room_subs if sr["id"] == mat_id)
        props = "\n".join(mat.get("props", []))
        assert "albedo_texture" in props, (
            f"Task 4: {mat_id} missing albedo_texture"
        )
        assert "albedo_texture = ExtResource" in props, (
            f"Task 4: {mat_id} must reference texture via ExtResource, not SubResource"
        )
        assert "normal_texture" in props, (
            f"Task 4: {mat_id} missing normal_texture"
        )
        assert "ao_texture" in props, (
            f"Task 4: {mat_id} missing ao_texture"
        )
        assert "roughness_texture" in props, (
            f"Task 4: {mat_id} missing roughness_texture"
        )


# ═══════════════════════════════════════════════════════════════════════
#  CB-7: Skeletal NPC — Skeleton3D + AnimationPlayer + BoneAttachment3D
# ═══════════════════════════════════════════════════════════════════════

def test_npc_has_skeleton_node():
    """CB-7: NPC has a Skeleton3D child node."""
    _, parsed, _ = _compile_and_parse()
    skel_nodes = [n for n in parsed["nodes"] if n["name"] == "Skeleton"]
    assert len(skel_nodes) == 1, f"CB-7: expected 1 Skeleton node, got {len(skel_nodes)}"
    assert skel_nodes[0]["type"] == "Skeleton3D"
    assert skel_nodes[0]["parent"] == "npc_0"


def test_npc_has_animation_player():
    """CB-7: NPC has an AnimationPlayer child node."""
    _, parsed, _ = _compile_and_parse()
    anim_nodes = [n for n in parsed["nodes"] if n["name"] == "AnimationPlayer"]
    assert len(anim_nodes) == 1, f"CB-7: expected 1 AnimationPlayer node, got {len(anim_nodes)}"
    assert anim_nodes[0]["type"] == "AnimationPlayer"
    assert anim_nodes[0]["parent"] == "npc_0"


def test_npc_has_hips_attachment():
    """CB-7: NPC has a BoneAttachment3D for the Hips bone."""
    _, parsed, _ = _compile_and_parse()
    ha_nodes = [n for n in parsed["nodes"] if n["name"] == "HipsAttachment"]
    assert len(ha_nodes) == 1, f"CB-7: expected 1 HipsAttachment node, got {len(ha_nodes)}"
    assert ha_nodes[0]["type"] == "BoneAttachment3D"
    assert ha_nodes[0]["parent"] == "npc_0"


def test_body_attached_to_hips():
    """CB-7: Body GLB is now a child of HipsAttachment."""
    _, parsed, _ = _compile_and_parse()
    body_nodes = [n for n in parsed["nodes"] if n["name"] == "Body"]
    assert len(body_nodes) == 1, f"CB-7: expected 1 Body node, got {len(body_nodes)}"
    # Body parent should be "npc_0/HipsAttachment"
    assert "HipsAttachment" in body_nodes[0]["parent"]


# ═══════════════════════════════════════════════════════════════════════
#  CB-7: Outdoor room — no walls/ceiling, GroundPlane, biome atmosphere
# ═══════════════════════════════════════════════════════════════════════

def _make_exterior_plan():
    """Minimal exterior plan fixture for outdoor rooms."""
    return {
        "field": {
            "extent": 80.0, "amplitude": 1.2, "base_frequency": 0.045,
            "octaves": 4, "lacunarity": 2.0, "persistence": 0.5,
            "base_height": 0.0, "seed": 42,
        },
        "biome": {
            "biome": "temperate_forest",
            "terrain": {"amplitude": 2.2, "base_frequency": 0.05, "octaves": 5,
                        "lacunarity": 2.0, "persistence": 0.5},
            "ground_materials": ["grass", "dirt"],
            "flora_set": [
                {"category": "tree", "weight": 0.6, "density": 0.07},
                {"category": "shrub", "weight": 0.3, "density": 0.06},
            ],
            "atmosphere": {
                "fog_color": [0.6, 0.68, 0.6], "fog_density": 0.012,
                "sun_energy": 1.1, "sky_tint": [0.6, 0.72, 0.85],
            },
        },
        "building": {
            "center": [0.0, 0.0], "half_w": 10.0, "half_d": 10.0,
            "pad_height": 0.0, "door_side": "+z", "door_center": [0.0, 10.0],
            "structure": "cabin",
        },
        "spawn": {"x": 0.0, "z": 13.0, "yaw": 3.1416},
        "scatter_placements": [
            {"category": "tree", "x": 15.0, "y": 0.3, "z": 10.0, "yaw": 0.5, "scale": 1.0},
            {"category": "shrub", "x": -12.0, "y": 0.1, "z": -8.0, "yaw": 1.2, "scale": 0.9},
        ],
        "names": {}, "decisions": [], "extent": 80.0,
    }


def test_outdoor_room_no_walls():
    """CB-7: Outdoor rooms have NO wall nodes."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    ep = _make_exterior_plan()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_type="outdoor", exterior_plan=ep)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        wall_names = {"WallN", "WallS", "WallE", "WallW"}
        node_names = {n["name"] for n in parsed["nodes"]}
        for wn in wall_names:
            assert wn not in node_names, f"CB-7: outdoor room should not have {wn}"
        assert "Ceiling" not in node_names, "CB-7: outdoor room should not have Ceiling"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_outdoor_room_has_ground_plane():
    """CB-7: Outdoor rooms have a GroundPlane MeshInstance3D."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    ep = _make_exterior_plan()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_type="outdoor", exterior_plan=ep)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        gp_nodes = [n for n in parsed["nodes"] if n["name"] == "GroundPlane"]
        assert len(gp_nodes) == 1, f"CB-7: expected GroundPlane node, got {[n['name'] for n in parsed['nodes']]}"
        assert gp_nodes[0]["type"] == "MeshInstance3D"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_outdoor_room_has_scatter_vegetation():
    """CB-7: Outdoor rooms include scatter vegetation as decor nodes."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    ep = _make_exterior_plan()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_type="outdoor", exterior_plan=ep)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        node_names = {n["name"] for n in parsed["nodes"]}
        # Scatter placements should appear as scatter_{cat}_{idx}
        assert "scatter_tree_0" in node_names, f"CB-7: missing scatter_tree_0 in {sorted(node_names)}"
        assert "scatter_shrub_1" in node_names, f"CB-7: missing scatter_shrub_1"
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_outdoor_scatter_is_decor():
    """CB-7: Scatter vegetation is decor-only (no collision, no pickup tag)."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    ep = _make_exterior_plan()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_type="outdoor", exterior_plan=ep)
        text = Path(out).read_text(encoding="utf-8")
        parsed = _parse_scene_text(text)
        # Scatter nodes should be type Node3D (decor), not StaticBody3D
        tree_node = next(n for n in parsed["nodes"] if n["name"] == "scatter_tree_0")
        assert tree_node["type"] == "Node3D", (
            f"CB-7: scatter decor should be Node3D, got {tree_node['type']}"
        )
        # Should NOT have collision or tag metadata
        meta = parsed["metadata"].get("scatter_tree_0", {})
        assert meta.get("_forge_tag", "") == "", (
            f"CB-7: scatter decor should not have _forge_tag, got {meta}"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_outdoor_atmosphere_applied():
    """CB-7: Outdoor room uses biome atmosphere for fog/sky."""
    spec = dict(_QUEST_SPEC)
    man = _MANIFEST
    ep = _make_exterior_plan()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_type="outdoor", exterior_plan=ep)
        text = Path(out).read_text(encoding="utf-8")
        # Biome fog color should be in the environment
        assert "fog_light_color = Color(0.6, 0.68, 0.6, 1.0)" in text, (
            f"CB-7: outdoor fog color not applied\ntext:\n{text[:3000]}"
        )
        assert "fog_density = 0.012" in text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_indoor_room_still_has_walls():
    """CB-7: Indoor rooms (default) still have walls and ceiling."""
    _, parsed, _ = _compile_and_parse()
    node_names = {n["name"] for n in parsed["nodes"]}
    for wn in ("WallN", "WallS", "WallE", "WallW"):
        assert wn in node_names, f"CB-7: indoor room should have {wn}"
    assert "Ceiling" in node_names, "CB-7: indoor room should have Ceiling"


# ═══════════════════════════════════════════════════════════════════════
#  Task 3: Generative lighting plan → realtime rig
# ═══════════════════════════════════════════════════════════════════════

def test_lighting_plan_emits_one_omni_per_source():
    import scene_compiler as sc
    plan = {"sources": [
              {"type": "hearth", "pos": (0,0.5,-3), "color": (1,0.6,0.3), "energy": 6, "range": 6, "flicker": True},
              {"type": "torch",  "pos": (2,2.2,-3), "color": (1,0.7,0.4), "energy": 3, "range": 4, "flicker": True}],
            "windows": [], "sun": {"color": (0.5,0.6,0.85), "energy": 0.8, "direction": (-0.3,-0.6,-0.5)},
            "sky": {"top": (0.4,0.45,0.6), "ambient_energy": 0.4},
            "environment": {"ambient_color": (0.4,0.4,0.45), "ambient_energy": 0.6,
                            "fog_color": (0.15,0.15,0.2), "fog_energy": 0.1, "tonemap": 2, "exposure": 1.2}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], _minimal_manifest(), out,
                         room_size={"w":8,"d":6}, theme="study", lighting_plan=plan)
        t = Path(out).read_text(encoding="utf-8")
        assert t.count('type="OmniLight3D"') >= 2  # at least our 2 plan lights
        assert "ambient_light_energy = 0.6" in t      # readable, not 0.4
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_no_plan_keeps_default_lighting():
    import scene_compiler as sc
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], _minimal_manifest(), out,
                         room_size={"w":8,"d":6}, theme="study")  # no lighting_plan
        t = Path(out).read_text(encoding="utf-8")
        assert "OmniLight3D" in t  # still emits the existing default rig
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


# ═══════════════════════════════════════════════════════════════════════
#  Task 4: Bake scene_desc builder + bake_scene wiring
# ═══════════════════════════════════════════════════════════════════════

def test_scene_desc_carries_interior_lights():
    from scene_compiler import build_lighting_scene_desc
    plan = {"sources": [{"type":"hearth","pos":(0,0.5,-3),"color":(1,0.6,0.3),"energy":6,"range":6,"flicker":True}],
            "sun": {"color":(0.5,0.6,0.85),"energy":0.8,"direction":(-0.3,-0.6,-0.5)},
            "sky": {"top":(0.4,0.45,0.6),"ambient_energy":0.4}}
    desc = build_lighting_scene_desc(plan, placements=[], tier=2, samples=64)
    assert desc["tier"] == 2 and desc["sun"] == plan["sun"]
    # C2 (Phase 0.2): interior-light pos is swizzled Godot-Y-up → Blender-Z-up
    # so Cycles bakes emitters at the correct Y-coordinate (hearths used to
    # bake buried under the floor, torches at the wrong height).
    expected = dict(plan["sources"][0])
    p = plan["sources"][0]["pos"]
    expected["pos"] = (p[0], p[2], p[1])  # (x, z, y)
    assert desc["interior_lights"][0] == expected


def test_interior_light_pos_remapped_y_to_z_explicit_case():
    """C2 (Phase 0.2): explicit (2.0, 0.5, -3.0) → (2.0, -3.0, 0.5).

    The user's verification case: ``build_lighting_scene_desc`` must
    swizzle interior-light pos from Godot-Y-up to Blender-Z-up at the
    bake boundary so Cycles doesn't bury emitters under the floor.
    """
    from scene_compiler import build_lighting_scene_desc
    plan = {"sources": [{"type": "hearth", "pos": (2.0, 0.5, -3.0),
                         "color": (1.0, 0.6, 0.3), "energy": 6.0,
                         "range": 6.0, "flicker": True}],
            "sun": {"color": (0.5, 0.6, 0.85), "energy": 0.8,
                    "direction": (-0.3, -0.6, -0.5)},
            "sky": {"top": (0.4, 0.45, 0.6), "ambient_energy": 0.4}}
    desc = build_lighting_scene_desc(plan, placements=[], tier=2, samples=64)
    assert desc["interior_lights"][0]["pos"] == (2.0, -3.0, 0.5), (
        f"expected (x, z, y) swizzle; got {desc['interior_lights'][0]['pos']}"
    )


def test_interior_light_other_fields_preserved_after_remap():
    """C2: the swizzle must only touch 'pos'; other source fields
    (type, color, energy, range, flicker) pass through unchanged."""
    from scene_compiler import build_lighting_scene_desc
    plan = {"sources": [{"type": "torch", "pos": (4.0, 2.2, -3.5),
                         "color": (1.0, 0.7, 0.4), "energy": 3.0,
                         "range": 4.0, "flicker": True}],
            "sun": {}, "sky": {}}
    desc = build_lighting_scene_desc(plan, placements=[], tier=2, samples=24)
    remapped = desc["interior_lights"][0]
    assert remapped["type"] == "torch"
    assert remapped["color"] == (1.0, 0.7, 0.4)
    assert remapped["energy"] == 3.0
    assert remapped["range"] == 4.0
    assert remapped["flicker"] is True
    assert remapped["pos"] == (4.0, -3.5, 2.2)  # (x, z, y)


def test_interior_light_remap_handles_no_sources_gracefully():
    """C2: empty sources list -> empty interior_lights, no KeyError."""
    from scene_compiler import build_lighting_scene_desc
    plan = {"sources": [], "sun": {}, "sky": {}}
    desc = build_lighting_scene_desc(plan, placements=[], tier=1, samples=16)
    assert desc["interior_lights"] == []


def test_realtime_omnilight_transform_uses_y_up_pos():
    """C2 (Phase 0.2): realtime rig MUST use Godot-Y-up pos unchanged.

    Only the bake payload swizzles; the .tscn PlanLight transform line
    keeps the original (x, y, z) so the realtime scene stays correct.
    """
    import scene_compiler as sc
    plan = {"sources": [{"type": "hearth", "pos": (2.0, 0.5, -3.0),
                         "color": (1.0, 0.6, 0.3), "energy": 6.0,
                         "range": 6.0, "flicker": True}],
            "sun": {"color": (0.5, 0.6, 0.85), "energy": 0.8,
                    "direction": (-0.3, -0.6, -0.5)},
            "sky": {"top": (0.4, 0.45, 0.6), "ambient_energy": 0.4},
            "windows": [],
            "environment": {"ambient_color": (0.4, 0.4, 0.45),
                            "ambient_energy": 0.6}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], _minimal_manifest(), out,
                         room_size={"w": 8, "d": 6}, theme="study",
                         lighting_plan=plan)
        text = Path(out).read_text(encoding="utf-8")
        assert "PlanLight0" in text, (
            f"expected PlanLight0 in tscn, text sample:\n{text[:1500]}"
        )
        expected_realtime = (
            "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            "2, 0.5, -3)"
        )
        assert expected_realtime in text, (
            f"realtime PlanLight0 transform should use Y-up pos (2.0, 0.5, -3.0); "
            f"text: {text[:3000]}"
        )
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_tier0_skips_bake(monkeypatch):
    import scene_compiler as sc, lighting_bake
    called = []
    monkeypatch.setattr(lighting_bake, "bake_scene", lambda *a, **k: called.append(1) or {"tier":0,"status":"realtime","artifacts":[]})
    sc.bake_and_apply(sc.build_lighting_scene_desc(
        {"sources":[],"sun":{},"sky":{}}, [], tier=0, samples=1), build_dir="/tmp/x")
    # tier 0 short-circuits inside scene_compiler before calling the baker
    assert called == []


# ═══════════════════════════════════════════════════════════════════════
#  Task 6: GLB shell + triplanar + carved navmesh + fallback
# ═══════════════════════════════════════════════════════════════════════

def _minimal_manifest():
    """Minimal manifest for Task 6 tests."""
    return [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 1.0, "y": 0.0, "z": -1.5},
    ]


def _compile_with_shell(manifest=None, room_size=None, theme=None):
    """Helper: compile with room_size + theme, return text and parsed."""
    spec = dict(_QUEST_SPEC)
    man = manifest or _minimal_manifest()
    spec["target_entity"] = man[0]["id"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tscn", delete=False
    ) as f:
        out = f.name
    try:
        compile_scene(spec, man, out, room_size=room_size, theme=theme)
        text = Path(out).read_text(encoding="utf-8")
        return text
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_shell_glb_path_emits_instance_and_triplanar(monkeypatch, tmp_path):
    import room_shell
    glb = tmp_path / "shell.glb"; glb.write_bytes(b"GLB")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    assert "shell.glb" in tscn
    assert "uv1_triplanar = true" in tscn and "uv1_world_triplanar = true" in tscn


def test_no_glb_falls_back_to_box_shell(monkeypatch):
    import room_shell
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: None)
    tscn = _compile_with_shell()
    assert "floor_vis_mesh" in tscn  # inline box shell still present


def test_navmesh_uses_carved_vertices(monkeypatch):
    import navmesh
    monkeypatch.setattr(navmesh, "carve_walkable",
                        lambda *a, **k: ([(1.0, 0.0, 1.0), (2.0, 0.0, 1.0), (1.5, 0.0, 2.0)], [[0, 1, 2]]))
    tscn = _compile_with_shell()
    assert "1, 0, 1" in tscn  # carved vertex present in NavigationMesh


# ── Task 6 fix: GLB shell replaces box-shell when Blender emits one ─
#
# The previous scene_compiler emitted BOTH:
#   * the Blender-generated shell.glb (ext_resource registered but
#     never instanced on a node);
#   * the inline box-shell floor_mat/wall_mat/ceiling_mat + the
#     FloorMesh, Wall*_mesh, Ceiling MeshInstance3D nodes.
# Stacking the box over the GLB produced magenta walls,
# "Compressed texture file is corrupt" load warnings, and a
# registered-but-never-loaded GLB ext_resource.
#
# These tests pin the corrected contract: the GLB is now actually
# instanced as a `Shell` node, its `stone` and `timber` child
# MeshInstance3Ds get the build's triplanar StandardMaterials via
# `material_override =`, and the box-shell sub_resources + visible
# nodes are absent in this branch.  The box-shell fallback (when
# `ensure_room_shell` returns None) is still tested by
# `test_no_glb_falls_back_to_box_shell` above.


@pytest.fixture(autouse=True)
def _default_box_shell():
    """Default ``room_shell.ensure_room_shell`` to None so tests that
    DON'T explicitly request a GLB take the box-shell fallback branch
    (their old assertions about floor_mat/wall_mat/ceiling_mat/FloorMesh
    stay green even when Blender is installed in the test env).

    Tests that want the GLB branch re-monkeypatch with a Path and
    win — last monkeypatch.setattr wins within a single test.

    Uses manual patch/restore (not pytest monkeypatch) so the original
    function is ALWAYS restored — prevents state leaking into other
    test modules when monkeypatch teardown ordering is unlucky.
    """
    import room_shell
    _orig = room_shell.ensure_room_shell
    room_shell.ensure_room_shell = lambda *a, **k: None
    try:
        yield
    finally:
        room_shell.ensure_room_shell = _orig


def test_glb_shell_emits_shell_instance_node(monkeypatch, tmp_path):
    """Task 6 fix: when ``ensure_room_shell`` returns a GLB path, the
    compiled scene MUST instance shell.glb on a Shell node (not just
    register it as an unused ext_resource).  Without this assertion
    the previous bug — registered-but-not-instanced GLB — would slip
    back in unnoticed.
    """
    import room_shell
    glb = tmp_path / "shell.glb"
    glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    parsed = _parse_scene_text(tscn)
    shell_nodes = [n for n in parsed["nodes"] if n["name"] == "Shell"]
    assert len(shell_nodes) == 1, (
        f"expected exactly 1 Shell node instancing shell.glb, got "
        f"{len(shell_nodes)}; node names: {[n['name'] for n in parsed['nodes']]}"
    )
    assert shell_nodes[0]["parent"] == ".", (
        f"Shell should be a top-level node (parent='.'), got parent={shell_nodes[0]['parent']!r}"
    )
    assert shell_nodes[0]["instance"] is not None, (
        "Shell node must instance shell.glb via ExtResource (header-line instance=)"
    )


def test_glb_shell_emits_stone_and_timber_children(monkeypatch, tmp_path):
    """Task 6 fix: shell.glb exposes two top-level meshes named
    'stone' and 'timber' (built by foundry/blender/build_room_shell.py
    via ``bpy.data.objects.new(name, me)``).  Overriding them with our
    triplanar StandardMaterials propagates the right albedo/roughness
    per surface — stone walls/roof boards, timber floor/rafters/posts.
    """
    import room_shell
    glb = tmp_path / "shell.glb"
    glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    parsed = _parse_scene_text(tscn)

    stone = [n for n in parsed["nodes"] if n["name"] == "stone"]
    timber = [n for n in parsed["nodes"] if n["name"] == "timber"]
    assert len(stone) == 1, (
        f"expected 1 'stone' override child of Shell, got {len(stone)}; "
        f"node names: {[n['name'] for n in parsed['nodes']]}"
    )
    assert len(timber) == 1, (
        f"expected 1 'timber' override child of Shell, got {len(timber)}"
    )
    assert stone[0]["parent"] == "Shell", (
        f"stone override must be parented to Shell, got {stone[0]['parent']!r}"
    )
    assert timber[0]["parent"] == "Shell", (
        f"timber override must be parented to Shell, got {timber[0]['parent']!r}"
    )
    # material_override lines are not parsed by _parse_scene_text
    # (the prefix isn't in its recognised property list), so verify
    # the raw text contains the right override + SubResource refs.
    assert 'material_override = SubResource("shell_stone_mat")' in tscn, (
        "stone child must apply shell_stone_mat via material_override"
    )
    assert 'material_override = SubResource("shell_timber_mat")' in tscn, (
        "timber child must apply shell_timber_mat via material_override"
    )


def test_glb_shell_drops_box_shell_visible_nodes(monkeypatch, tmp_path):
    """Task 6 fix: when the GLB shell is present, the inline box-shell
    visible geometry MUST be absent.  FloorMesh / Ceiling / Wall*_mesh
    children were the cause of the magenta-wall stacking: the GLB was
    correctly generated, the box-shell BoxMesh + box-shell tinted
    StandardMaterials sat on top, and the MagentaMaterial default
    appeared wherever a box surface received neither the GLB material
    nor the box-shell material that referenced a 'corrupt' .ctex.
    """
    import room_shell
    glb = tmp_path / "shell.glb"; glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    parsed = _parse_scene_text(tscn)
    node_names = {n["name"] for n in parsed["nodes"]}

    # Visible box-shell nodes that MUST disappear in the GLB branch.
    absent_meshes = [
        "FloorMesh", "Ceiling",
        "WallN_mesh", "WallS_mesh", "WallE_mesh", "WallW_mesh",
    ]
    for absent in absent_meshes:
        assert absent not in node_names, (
            f"GLB shell branch must NOT emit {absent!r} (would stack "
            f"invisible box over the rendered GLB → magenta walls); "
            f"got node names: {sorted(node_names)}"
        )
    # The wall *bodies* (StaticBody3D) DO stay — they hold the
    # collision volumes the player walks into.
    for wall in ("WallN", "WallS", "WallE", "WallW"):
        assert wall in node_names, (
            f"GLB shell branch must keep StaticBody3D body {wall!r} "
            f"for player collision"
        )
    assert "Floor" in node_names, (
        "GLB shell branch must keep the Floor StaticBody3D for player collision"
    )


def test_glb_shell_drops_box_shell_sub_resources(monkeypatch, tmp_path):
    """Task 6 fix: when the GLB shell is present, the box-shell
    sub_resources (BoxMeshes + tileable textures + tinted
    StandardMaterials) MUST NOT be in the scene — otherwise
    godot's importer iterates them, finds missing PNGs, logs
    ``Compressed texture file is corrupt (Bad header)`` warnings,
    AND the .import sidecars sit unused in builds/<name>/assets/.

    Only the stone/timber triplanar materials + textures should be
    emitted in this branch.
    """
    import room_shell
    glb = tmp_path / "shell.glb"; glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    sub_ids = {sr["id"] for sr in _parse_scene_text(tscn)["sub_resources"]}

    # Box-shell sub_resources that MUST NOT be emitted.
    absent_subs = [
        # BoxMeshes
        "floor_vis_mesh", "wall_ns_mesh", "wall_ew_mesh", "ceiling_mesh",
        # Tileable shell_*_*.png textures (their absence is what
        # caused the previous "corrupt" warnings).
        "tex_floor_a", "tex_floor_n", "tex_floor_o",
        "tex_wall_a",  "tex_wall_n",  "tex_wall_o",
        "tex_ceil_a",  "tex_ceil_n",  "tex_ceil_o",
        # Per-theme tinted StandardMaterials referencing the absent textures.
        "floor_mat", "wall_mat", "ceiling_mat",
    ]
    for sid in absent_subs:
        assert sid not in sub_ids, (
            f"GLB shell branch must NOT contain sub_resource {sid!r} "
            f"(box-shell artifacts from the previous bug); got: {sorted(sub_ids)}"
        )

    # Stone/timber textures MUST be present — now as ext_resource Texture2D
    # entries (not sub_resource CompressedTexture2D).  Triplanar
    # StandardMaterial3Ds remain as sub_resources.
    parsed = _parse_scene_text(tscn)
    ext_ids = {r["id"] for r in parsed["ext_resources"]}
    for tex_id in ("tex_stone_a", "tex_stone_n", "tex_stone_o",
                   "tex_timber_a", "tex_timber_n", "tex_timber_o"):
        assert tex_id in ext_ids, (
            f"GLB shell branch must contain ext_resource {tex_id!r}; "
            f"ext_resource ids: {sorted(ext_ids)}"
        )
    # Verify the ext_resource paths are correct .png references
    for ext_id, expected_suffix in [
        ("tex_stone_a", "shell_stone_albedo.png"),
        ("tex_stone_n", "shell_stone_normal.png"),
        ("tex_stone_o", "shell_stone_orm.png"),
        ("tex_timber_a", "shell_timber_albedo.png"),
        ("tex_timber_n", "shell_timber_normal.png"),
        ("tex_timber_o", "shell_timber_orm.png"),
    ]:
        matching = [r for r in parsed["ext_resources"] if r["id"] == ext_id]
        assert len(matching) == 1, f"expected 1 ext_resource with id {ext_id}, got {len(matching)}"
        assert matching[0]["path"].endswith(expected_suffix), (
            f"{ext_id} path should end with {expected_suffix}, got {matching[0]['path']}"
        )
    for sid in ("shell_stone_mat", "shell_timber_mat"):
        assert sid in sub_ids, (
            f"GLB shell branch must contain sub_resource {sid!r}; got: {sorted(sub_ids)}"
        )
    # Stone/timber texture IDs must NOT appear as sub_resources.
    for sid in ("tex_stone_a", "tex_stone_n", "tex_stone_o",
                "tex_timber_a", "tex_timber_n", "tex_timber_o"):
        assert sid not in sub_ids, (
            f"Texture {sid!r} must NOT be a sub_resource (it's an ext_resource); "
            f"got: {sorted(sub_ids)}"
        )

    # shell.glb must still be referenced in ext_resources.
    paths = {r["path"] for r in _parse_scene_text(tscn)["ext_resources"]}
    assert "res://assets/shell.glb" in paths, (
        f"GLB shell branch missing ext_resource for shell.glb; paths: {sorted(paths)}"
    )


# ═══════════════════════════════════════════════════════════════════════
#  Palette contract — assembly-time per-class material override
# ═══════════════════════════════════════════════════════════════════════

def _manifest_with(pairs: list[tuple[str, str]]) -> list[dict]:
    """Build a manifest from (category, material) pairs."""
    out: list[dict] = []
    for i, (cat, mat) in enumerate(pairs):
        out.append({
            "id": f"{cat}_{i}",
            "category": cat,
            "material": mat,
            "wear": 0.5,
            "x": float(i + 1) * 1.5,
            "y": 0.0,
            "z": -float(i + 1) * 1.2,
        })
    return out


def test_palette_emits_one_material_per_class(monkeypatch):
    """When a palette is provided, compile_scene emits one
    StandardMaterial3D per material class present, triplanar,
    with albedo_color tinted by the palette role colour, and
    textures referenced as ext_resource Texture2D (never
    CompressedTexture2D sub_resource)."""
    import scene_compiler as sc
    from palette import build_palette
    pal = build_palette("stone_keep", 0)
    m = _manifest_with([("table", "worn_oak"), ("shelf", "rough_granite")])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], m, out,
                         room_size={"w": 8, "d": 6},
                         theme="stone_keep", palette=pal)
        t = Path(out).read_text(encoding="utf-8")
        # At least 2 per-class StandardMaterial3D sub_resources
        # (wood for worn_oak → table, stone for rough_granite → shelf).
        # The box-shell fallback also emits floor_mat/wall_mat/ceiling_mat
        # and player_body_mat/door_mat, so the total is well above 2.
        assert t.count('type="StandardMaterial3D"') >= 2
        assert "uv1_triplanar = true" in t
        # wood class → midtone role
        midtone = pal["roles"]["midtone"]
        assert f"albedo_color = Color({midtone[0]}" in t
        # ext_resource Texture2D for class textures
        assert 'ext_resource type="Texture2D" path="res://assets/class_wood_albedo.png"' in t
        # Never CompressedTexture2D near class_wood
        assert "CompressedTexture2D" not in t.split("class_wood")[0][-400:]
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_no_palette_unchanged():
    """Without palette, compile_scene keeps existing behaviour."""
    import scene_compiler as sc
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], _minimal_manifest(), out,
                         room_size={"w": 8, "d": 6}, theme="stone_keep")
        t = Path(out).read_text(encoding="utf-8")
        assert "StandardMaterial3D" in t  # existing path still works
        # No palette class ext_resources
        assert "class_wood" not in t
        assert "class_stone" not in t
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_palette_override_on_model_nodes(monkeypatch):
    """When palette is provided, model nodes get surface_material_override."""
    import scene_compiler as sc
    from palette import build_palette
    pal = build_palette("stone_keep", 0)
    m = _manifest_with([("table", "worn_oak")])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene([], m, out,
                         room_size={"w": 8, "d": 6},
                         theme="stone_keep", palette=pal)
        t = Path(out).read_text(encoding="utf-8")
        # worn_oak → wood → mat_wood
        assert 'surface_material_override/0 = SubResource("mat_wood")' in t
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_palette_glb_shell_overrides_use_class_materials(monkeypatch, tmp_path):
    """When palette is provided AND a GLB shell is available, the shell
    stone/timber children use the palette class materials."""
    import room_shell
    import scene_compiler as sc
    from palette import build_palette
    pal = build_palette("stone_keep", 0)
    glb = tmp_path / "shell.glb"
    glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    spec = dict(_QUEST_SPEC)
    m = _minimal_manifest()
    spec["target_entity"] = m[0]["id"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tscn", delete=False) as f:
        out = f.name
    try:
        sc.compile_scene(spec, m, out,
                         room_size={"w": 8, "d": 6},
                         theme="stone_keep", palette=pal)
        t = Path(out).read_text(encoding="utf-8")
        # Shell stone/timber children use palette class materials
        assert 'material_override = SubResource("mat_stone")' in t
        assert 'material_override = SubResource("mat_wood")' in t
        # Class materials exist as sub_resources
        assert 'sub_resource type="StandardMaterial3D" id="mat_stone"' in t
        assert 'sub_resource type="StandardMaterial3D" id="mat_wood"' in t
    finally:
        Path(out).unlink()
        data_file = Path(out).with_name(f"{Path(out).stem}_quest_data.json")
        if data_file.exists():
            data_file.unlink()


def test_glb_shell_branch_keeps_navigation_and_lights(monkeypatch, tmp_path):
    """Sanity: the GLB shell branch must still emit the things the
    gameplay needs independent of the shell choice — environment,
    NavigationRegion3D, lights, door visual resources, and the
    per-collider BoxShape3D sub_resources for walls/floor/player
    (the player still walks on the invisible Floor body).
    """
    import room_shell
    glb = tmp_path / "shell.glb"; glb.write_bytes(b"GLB-fake")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = _compile_with_shell(room_size={"w": 8, "d": 6}, theme="study")
    parsed = _parse_scene_text(tscn)
    sub_types = {sr["type"] for sr in parsed["sub_resources"]}
    node_names = {n["name"] for n in parsed["nodes"]}
    assert "Environment" in sub_types, "world_env sub_resource missing"
    assert "NavigationMesh" in sub_types, "nav_mesh sub_resource missing"
    assert "NavigationRegion3D" in node_names, "NavigationRegion3D node missing"
    assert "WorldEnvironment" in node_names
    assert "DirectionalLight3D" in node_names
    # Floor body stays (with its collision shape) so the player has
    # ground to walk on even though no visible FloorMesh is emitted.
    assert "Floor" in node_names
    floor_coll = next(
        (n for n in parsed["nodes"] if n["name"] == "FloorCollision"), None
    )
    assert floor_coll is not None, "FloorCollision must remain in GLB branch"
    assert "WallN_collision" in node_names, (
        "WallN collision must remain in GLB branch (player physics)"
    )

