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
    assert npc_nodes[0]["type"] == "Node3D"


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


def test_other_props_have_inert_tag():
    _, parsed, _ = _compile_and_parse()
    target = _QUEST_SPEC["target_entity"]
    for entry in _MANIFEST:
        if entry["id"] == target:
            continue
        meta = parsed["metadata"].get(entry["id"], {})
        assert meta.get("_forge_tag") == "inert", (
            f"non-target {entry['id']!r} should have inert tag, got {meta}"
        )


def test_npc_has_talk_and_give_tags():
    _, parsed, _ = _compile_and_parse()
    meta = parsed["metadata"].get("NPC", {})
    assert meta.get("_forge_tag") == "talk"
    assert meta.get("_forge_tag_give") == "give"


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
    """Entries without x/y/z get (0,0,0)."""
    manifest_no_pos: list[PlacedEntity] = [
        {"id": "thing", "category": "table", "material": "worn_oak"}
    ]
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "thing"
    text, _, _ = _compile_and_parse(quest_spec=spec, manifest=manifest_no_pos)
    expected = "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)"
    assert expected in text


# ── NPC body primitive marker ────────────────────────────────────

def test_npc_has_primitive_body():
    """NPC Body node uses CapsuleMesh (generated, not imported)."""
    _, parsed, _ = _compile_and_parse()
    body_nodes = [n for n in parsed["nodes"] if n["name"] == "Body"]
    assert len(body_nodes) == 1
    assert body_nodes[0]["parent"] == "NPC"
    assert body_nodes[0]["type"] == "MeshInstance3D"


# ── Different target entity ──────────────────────────────────────

def test_different_target_gets_pickup_tag():
    spec = dict(_QUEST_SPEC)
    spec["target_entity"] = "table_0"
    _, parsed, _ = _compile_and_parse(quest_spec=spec)
    assert parsed["metadata"]["table_0"]["_forge_tag"] == "pickup"
    assert parsed["metadata"]["shelf_0"]["_forge_tag"] == "inert"


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
