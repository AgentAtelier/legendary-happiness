"""Unit 3 (core) — the World → scene_compiler adapter.

Pure tests of the field + coordinate mapping. The Godot LOAD of an
assembled scene is verified by the orchestrator (needs a live Godot).
"""
from world.assembly import footprint_centre, space_to_compile_inputs
from world.model import Entity, SpaceNode


def _space(**kw):
    base = dict(id="hall", seed=1, brief={}, footprint={}, entities=[], portals=[])
    base.update(kw)
    return SpaceNode(**base)


def test_footprint_centre():
    assert footprint_centre({"origin": [10, 0, 20], "size": [4, 3, 6]}) == (12.0, 1.5, 23.0)


def test_room_size_maps_w_d_h_from_footprint_size():
    node = _space(footprint={"origin": [0, 0, 0], "size": [4, 3, 6]})
    out = space_to_compile_inputs(node)
    assert out["room_size"] == {"w": 4.0, "d": 6.0, "h": 3.0}


def test_entity_world_pos_converted_to_room_local_centred():
    # footprint centre = (12, _, 23); an entity at the centre lands at (0, _, 0)
    node = _space(
        footprint={"origin": [10, 0, 20], "size": [4, 3, 6]},
        entities=[Entity(id="throne", type="chair", pos=(12, 0, 23),
                         properties={"material": "rough_granite"})],
    )
    m = space_to_compile_inputs(node)["manifest"]
    assert len(m) == 1
    assert m[0]["x"] == 0.0 and m[0]["z"] == 0.0
    assert m[0]["id"] == "throne"
    assert m[0]["category"] == "chair"      # Entity.type -> PlacedEntity.category
    assert m[0]["material"] == "rough_granite"


def test_entity_offset_from_centre_preserved():
    node = _space(
        footprint={"origin": [0, 0, 0], "size": [8, 3, 8]},  # centre (4,_,4)
        entities=[Entity(id="t", type="table", pos=(6, 0, 4), properties={})],
    )
    m = space_to_compile_inputs(node)["manifest"]
    assert m[0]["x"] == 2.0 and m[0]["z"] == 0.0   # 6-4=2, 4-4=0


def test_material_falls_back_to_brief_default_then_worn_oak():
    node = _space(
        footprint={"origin": [0, 0, 0], "size": [4, 3, 4]},
        brief={"default_material": "weathered_pine"},
        entities=[Entity(id="a", type="table", pos=(2, 0, 2), properties={})],
    )
    assert space_to_compile_inputs(node)["manifest"][0]["material"] == "weathered_pine"

    node2 = _space(
        footprint={"origin": [0, 0, 0], "size": [4, 3, 4]},
        entities=[Entity(id="a", type="table", pos=(2, 0, 2), properties={})],
    )
    assert space_to_compile_inputs(node2)["manifest"][0]["material"] == "worn_oak"


def test_theme_from_brief_and_empty_quest_specs():
    node = _space(footprint={"origin": [0, 0, 0], "size": [4, 3, 4]},
                  brief={"theme": "dungeon"})
    out = space_to_compile_inputs(node)
    assert out["theme"] == "dungeon"
    assert out["quest_specs"] == []


def test_no_entities_gives_empty_manifest():
    node = _space(footprint={"origin": [0, 0, 0], "size": [4, 3, 4]})
    assert space_to_compile_inputs(node)["manifest"] == []
