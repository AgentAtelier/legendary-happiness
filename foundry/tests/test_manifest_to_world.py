"""Tests for the manifest → world bridge (unit 5).

Covers: manifest_to_ops shape, manifest_to_world produces a gate-valid
World, and the round-trip through space_to_compile_inputs preserves
entity ids/types/positions.
"""

import pytest
from manifest_to_world import manifest_to_ops, manifest_to_world
from world.assembly import space_to_compile_inputs
from world.model import Entity, SpaceNode
from world.validation import WorldValidationError

# ── Simple manifest/room_size/theme fixtures ──────────────────────────

_MANIFEST = [
    {"id": "throne_0", "category": "throne", "material": "rough_granite",
     "x": 0.0, "y": 0.0, "z": -1.0},
    {"id": "table_0", "category": "table", "material": "worn_oak",
     "x": 2.0, "y": 0.0, "z": 2.0},
]

_ROOM_SIZE = {"w": 8.0, "d": 6.0, "h": 3.0}
_THEME = "hall"


# ── manifest_to_ops ───────────────────────────────────────────────────

def test_manifest_to_ops_produces_add_space_first():
    ops = manifest_to_ops(_MANIFEST, _ROOM_SIZE, _THEME)
    assert ops[0]["op"] == "add_space"
    assert ops[0]["id"] == "root"
    assert ops[0]["brief"] == {"theme": "hall"}
    assert ops[0]["footprint"] == {
        "origin": [0.0, 0.0, 0.0],
        "size": [8.0, 3.0, 6.0],
    }


def test_manifest_to_ops_produces_add_entity_per_item():
    ops = manifest_to_ops(_MANIFEST, _ROOM_SIZE, _THEME)
    assert len(ops) == 3  # 1 space + 2 entities
    assert ops[1]["op"] == "add_entity"
    assert ops[1]["space"] == "root"
    assert ops[1]["entity"]["id"] == "throne_0"
    assert ops[1]["entity"]["type"] == "throne"
    assert ops[1]["entity"]["properties"] == {"material": "rough_granite"}

    assert ops[2]["entity"]["id"] == "table_0"


def test_manifest_to_ops_uses_centre_offset():
    """Entity positions are offset from the footprint CENTRE (not origin)
    so that the round-trip with space_to_compile_inputs is exact."""
    manifest = [
        {"id": "a", "category": "prop", "material": "worn_oak",
         "x": 0.0, "y": 1.0, "z": 0.0},
    ]
    # room 8×3×6 at origin (0,0,0): centre = (4, 1.5, 3)
    ops = manifest_to_ops(manifest, _ROOM_SIZE, _THEME)
    pos = ops[1]["entity"]["pos"]
    assert pos == [4.0, 1.0, 3.0]  # centre_x + x, y, centre_z + z


def test_manifest_to_ops_custom_space_id_and_origin():
    manifest = [
        {"id": "a", "category": "prop", "material": "worn_oak",
         "x": 0.0, "y": 0.0, "z": 0.0},
    ]
    ops = manifest_to_ops(
        manifest, {"w": 4.0, "d": 4.0, "h": 3.0}, "dungeon",
        space_id="cellar", origin=(0.0, -4.0, 0.0),
    )
    assert ops[0]["id"] == "cellar"
    assert ops[0]["footprint"]["origin"] == [0.0, -4.0, 0.0]
    # centre = (2, -2.5, 2) — entity at (0,0,0) → world (2, 0, 2)
    assert ops[1]["entity"]["pos"] == [2.0, 0.0, 2.0]


# ── manifest_to_world ─────────────────────────────────────────────────

def test_manifest_to_world_produces_gate_valid_world():
    w = manifest_to_world(_MANIFEST, _ROOM_SIZE, _THEME)
    assert "root" in w.nodes
    node = w.nodes["root"]
    assert node.footprint == {
        "origin": [0.0, 0.0, 0.0],
        "size": [8.0, 3.0, 6.0],
    }
    assert node.brief["theme"] == "hall"
    assert len(node.entities) == 2
    assert {e.id for e in node.entities} == {"throne_0", "table_0"}
    assert len(w.op_log) == 3  # 1 space + 2 entities


def test_manifest_to_world_entities_inside_footprint():
    """Every entity passes the W3 gate (inside the footprint)."""
    w = manifest_to_world(_MANIFEST, _ROOM_SIZE, _THEME)
    for e in w.nodes["root"].entities:
        origin = w.nodes["root"].footprint["origin"]
        size = w.nodes["root"].footprint["size"]
        assert origin[0] <= e.pos[0] <= origin[0] + size[0]
        assert origin[1] <= e.pos[1] <= origin[1] + size[1]
        assert origin[2] <= e.pos[2] <= origin[2] + size[2]


def test_manifest_to_world_rejects_entity_out_of_bounds():
    """Entity outside footprint → WorldValidationError from the gate."""
    manifest = [
        {"id": "far", "category": "prop", "material": "worn_oak",
         "x": 99.0, "y": 0.0, "z": 99.0},
    ]
    with pytest.raises(WorldValidationError) as exc:
        manifest_to_world(manifest, _ROOM_SIZE, _THEME)
    assert exc.value.violations[0].code == "entity.out_of_bounds"


def test_manifest_to_world_empty_manifest():
    """Empty manifest → World with one space and no entities."""
    w = manifest_to_world([], _ROOM_SIZE, _THEME)
    assert "root" in w.nodes
    assert w.nodes["root"].entities == []
    assert len(w.op_log) == 1


# ── Round-trip: SpaceNode → compile inputs → manifest_to_world → back ─

def test_round_trip_preserves_entity_ids_types_positions():
    """SpaceNode → space_to_compile_inputs → manifest_to_world
    should reconstruct the same entities in the same positions."""
    fp = {"origin": [10.0, 0.0, 20.0], "size": [4.0, 3.0, 6.0]}
    original_entities = [
        Entity(id="throne", type="chair", pos=(12.0, 0.0, 23.0),
               properties={"material": "rough_granite"}),
        Entity(id="table", type="table", pos=(11.0, 0.0, 21.0),
               properties={"material": "worn_oak"}),
    ]
    node = SpaceNode(
        id="test_space", seed=1, brief={"theme": "hall"},
        footprint=fp, entities=original_entities,
    )

    # Step 1: world → compile inputs
    inputs = space_to_compile_inputs(node)
    manifest = inputs["manifest"]
    room_size = inputs["room_size"]
    theme = inputs["theme"]

    # Step 2: compile inputs → world (via manifest_to_world)
    world = manifest_to_world(
        manifest, room_size, theme,
        space_id="test_space",
        origin=(fp["origin"][0], fp["origin"][1], fp["origin"][2]),
    )

    # Assert: same number of entities
    assert len(world.nodes["test_space"].entities) == len(original_entities)

    # Assert: entity ids, types, and positions match
    for orig in original_entities:
        rebuilt = next(
            e for e in world.nodes["test_space"].entities if e.id == orig.id
        )
        assert rebuilt.type == orig.type
        assert rebuilt.properties.get("material") == orig.properties.get("material")
        # Positions are bit-exact: float precision preserved through the
        # centre subtraction/addition round-trip
        assert rebuilt.pos[0] == pytest.approx(orig.pos[0])
        assert rebuilt.pos[1] == pytest.approx(orig.pos[1])
        assert rebuilt.pos[2] == pytest.approx(orig.pos[2])
