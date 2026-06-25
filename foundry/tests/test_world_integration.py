"""Integration test — multi-space world built by hand (unit 5).

Builds a small multi-space world (hall + courtyard + cellar) with portals,
entities, and assertions that prove the whole stack agrees:

- world_index has 3 spaces with correct neighbours+directions
- find_entities(type="throne") resolves to the hall
- overlapping add_space is rejected with space.overlap
- save_world→load_world round-trips

This is the "it all works together" proof.
"""

import tempfile
from pathlib import Path

import pytest
from world.model import World
from world.operations import WorldOpError
from world.persistence import load_world, save_world
from world.query import direction, find_entities, world_index
from world.validation import WorldValidationError, apply_op_checked


def _add_space(space_id: str, origin, size, theme=None) -> dict:
    return {
        "op": "add_space",
        "id": space_id,
        "brief": {"theme": theme} if theme else {},
        "footprint": {"origin": list(origin), "size": list(size)},
    }


def _add_portal(portal_id, from_space, to_space, position, size=(1.5, 2.0)) -> dict:
    return {
        "op": "add_portal",
        "id": portal_id,
        "from_space": from_space,
        "to_space": to_space,
        "position": list(position),
        "size": list(size),
    }


def _add_entity(space_id, entity_id, etype, pos, material="worn_oak") -> dict:
    return {
        "op": "add_entity",
        "space": space_id,
        "entity": {
            "id": entity_id,
            "type": etype,
            "pos": list(pos),
            "properties": {"material": material},
        },
    }


# ── Build the multi-space world ────────────────────────────────────────


def _build_test_world() -> World:
    """Build the world described in the task spec:
    - "hall" at origin 0,0,0, 8×4×8
    - "courtyard" to the NORTH at 0,0,-8 (adjacent face)
    - "cellar" BELOW at 0,-4,0
    - portals hall↔courtyard and hall↔cellar
    - throne in the hall + well in the courtyard
    """
    w = World()

    # Spaces
    w = apply_op_checked(w, _add_space("hall", (0, 0, 0), (8, 4, 8), theme="great hall"))
    w = apply_op_checked(w, _add_space("courtyard", (0, 0, -8), (8, 4, 8), theme="courtyard"))
    w = apply_op_checked(w, _add_space("cellar", (0, -4, 0), (8, 4, 8), theme="cellar"))

    # Portals
    # hall↔courtyard: shared face at z=0 (hall's south / courtyard's north)
    # The shared boundary is the face where hall z[0,8] meets courtyard z[-8,0]
    # Portal position should be on that shared face: (4, 2, 0)
    w = apply_op_checked(w, _add_portal("p_hall_court", "hall", "courtyard",
                                        (4.0, 2.0, 0.0)))

    # hall↔cellar: shared face at y=0 (hall's floor / cellar's ceiling)
    # Portal position on the shared face: (4, 0, 4)
    w = apply_op_checked(w, _add_portal("p_hall_cellar", "hall", "cellar",
                                        (4.0, 0.0, 4.0)))

    # Entities
    w = apply_op_checked(w, _add_entity("hall", "throne", "throne",
                                        (4.0, 0.0, 4.0), material="rough_granite"))
    w = apply_op_checked(w, _add_entity("courtyard", "well", "well",
                                        (4.0, 0.0, -4.0), material="rough_granite"))

    return w


# ── Tests ──────────────────────────────────────────────────────────────


def test_world_index_has_three_spaces():
    w = _build_test_world()
    idx = world_index(w)
    assert len(idx["spaces"]) == 3
    space_ids = {s["id"] for s in idx["spaces"]}
    assert space_ids == {"hall", "courtyard", "cellar"}


def test_neighbors_and_directions():
    w = _build_test_world()

    # hall ↔ courtyard (z-touching: hall at z[0,8], courtyard at z[-8,0])
    assert direction(w, "hall", "courtyard") == "north"  # -Z from hall centre
    assert direction(w, "courtyard", "hall") == "south"  # +Z from courtyard centre

    # hall ↔ cellar (y-touching: hall at y[0,4], cellar at y[-4,0])
    assert direction(w, "hall", "cellar") == "down"  # -Y from hall centre
    assert direction(w, "cellar", "hall") == "up"    # +Y from cellar centre

    # Verify neighbours in the index
    idx = world_index(w)
    hall_entry = next(s for s in idx["spaces"] if s["id"] == "hall")
    hall_neighbor_dirs = {n["direction"] for n in hall_entry["neighbors"]}
    assert "north" in hall_neighbor_dirs
    assert "down" in hall_neighbor_dirs
    assert len(hall_entry["neighbors"]) == 2


def test_find_entities_throne_in_hall():
    w = _build_test_world()
    results = find_entities(w, type="throne")
    assert len(results) == 1
    space_id, entity = results[0]
    assert space_id == "hall"
    assert entity.id == "throne"
    assert entity.type == "throne"
    assert entity.properties["material"] == "rough_granite"


def test_find_entities_well_in_courtyard():
    w = _build_test_world()
    results = find_entities(w, type="well")
    assert len(results) == 1
    space_id, entity = results[0]
    assert space_id == "courtyard"
    assert entity.id == "well"


def test_overlapping_add_space_rejected():
    w = _build_test_world()
    # Try to add a space that overlaps the hall
    with pytest.raises(WorldValidationError) as exc:
        apply_op_checked(w, _add_space("overlap", (2, 1, 2), (4, 3, 4)))
    assert exc.value.violations[0].code == "space.overlap"


def test_overlap_error_is_world_op_error():
    """Overlap rejection is still catchable as WorldOpError."""
    w = _build_test_world()
    with pytest.raises(WorldOpError):
        apply_op_checked(w, _add_space("overlap", (2, 1, 2), (4, 3, 4)))


def test_save_world_load_world_round_trip():
    """save_world → load_world preserves the materialized state."""
    w = _build_test_world()
    with tempfile.TemporaryDirectory() as tmpdir:
        save_world(w, tmpdir)
        w2 = load_world(tmpdir)

    # Same number of spaces
    assert set(w2.nodes) == set(w.nodes)

    # Same number of portals
    assert set(w2.portals) == set(w.portals)

    # Same entities per space
    for sid in w.nodes:
        orig_ids = {e.id for e in w.nodes[sid].entities}
        loaded_ids = {e.id for e in w2.nodes[sid].entities}
        assert orig_ids == loaded_ids

    # op_logs match
    assert len(w2.op_log) == len(w.op_log)

    # Portals are bidirectional (each space records the portal)
    for pid, portal in w2.portals.items():
        assert pid in w2.nodes[portal.from_space].portals
        assert pid in w2.nodes[portal.to_space].portals
