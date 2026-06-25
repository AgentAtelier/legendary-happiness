"""TDD tests for ``foundry.world.operations`` — the v1 op vocabulary + apply_op + replay.

Spec-locked properties (the test ENCODES them):

  1. apply_op is PURE: input world is not mutated.
  2. Op vocabulary v1: add_space, add_portal, add_entity, move_entity,
     set_property, remove_entity.  Each with the spec-declared shape.
  3. Referential integrity: add_portal to/from a nonexistent space
     raises ``WorldOpError``.  So does an unknown ``op`` value, a
     nonexistent entity, and a path-set on a nonexistent space.
  4. append to op_log: every successful apply_op appends its op.
  5. replay(op_log) folds apply_op over an empty world.
"""

from __future__ import annotations

import pytest

from world.model import SpaceNode, World, seed_from_id
from world.operations import WorldOpError, apply_op, replay


# ── Op builders ──────────────────────────────────────────────────────


def _op_add_space(id: str = "hall", brief=None, footprint=None,
                  seed=None, gen_version: str = "v1") -> dict:
    if brief is None:
        brief = {"name": id.title()}
    if footprint is None:
        footprint = {"origin": [0.0, 0.0, 0.0], "size": [10.0, 4.0, 10.0]}
    op = {"op": "add_space", "id": id,
          "brief": brief, "footprint": footprint,
          "gen_version": gen_version}
    if seed is not None:
        op["seed"] = seed
    return op


def _op_add_portal(id: str = "p1", frm="A", to="B",
                   position=(0.0, 0.0, 0.0),
                   size=(1.0, 2.0)) -> dict:
    return {"op": "add_portal", "id": id,
            "from_space": frm, "to_space": to,
            "position": list(position), "size": list(size)}


def _op_add_entity(space="hall", id="candle_0",
                   type="candle", pos=(0.0, 0.0, 0.0),
                   properties=None) -> dict:
    return {"op": "add_entity",
            "space": space,
            "entity": {"id": id, "type": type,
                       "pos": list(pos),
                       "properties": properties or {}}}


def _op_move_entity(space="hall", entity_id="candle_0",
                    new_pos=(1.0, 0.0, 1.0)) -> dict:
    return {"op": "move_entity", "space": space,
            "entity_id": entity_id, "new_pos": list(new_pos)}


def _op_set_property(target_kind="entity", space="hall",
                     entity_id="candle_0",
                     path=("lit", "since"), value=1) -> dict:
    op = {"op": "set_property",
          "target_kind": target_kind,
          "space": space, "path": list(path), "value": value}
    if entity_id is not None:
        op["entity_id"] = entity_id
    return op


def _op_remove_entity(space="hall", entity_id="candle_0") -> dict:
    return {"op": "remove_entity", "space": space,
            "entity_id": entity_id}


# ── 1. apply_op is PURE ──────────────────────────────────────────────


def test_apply_op_does_not_mutate_input_nodes_dict():
    """The input World's nodes dict must NOT gain new keys after a call."""
    world = World()
    add_op = _op_add_space("hall")
    snap_nodes = dict(world.nodes)            # snapshot

    apply_op(world, add_op)

    assert dict(world.nodes) == snap_nodes    # reference equal, content equal
    assert "hall" not in world.nodes


def test_apply_op_does_not_mutate_input_op_log_list():
    """The input World's op_log list must NOT gain entries after a call."""
    world = World()
    add_op = _op_add_space("hall")
    snap_log = list(world.op_log)

    apply_op(world, add_op)

    assert list(world.op_log) == snap_log
    assert len(world.op_log) == 0


def test_apply_op_returns_new_world_object():
    """apply_op returns a NEW World (not the input)."""
    world = World()
    new_world = apply_op(world, _op_add_space("hall"))
    assert new_world is not world


def test_apply_op_sets_log_on_returned_world():
    """The returned world has the new op appended (the input does not)."""
    world = World()
    add_op = _op_add_space("hall")
    new_world = apply_op(world, add_op)
    # Input unchanged
    assert len(world.op_log) == 0
    # Output has it
    assert len(new_world.op_log) == 1
    assert new_world.op_log[0] == add_op


# ── 2. add_space ─────────────────────────────────────────────────────


def test_add_space_creates_node():
    w = apply_op(World(), _op_add_space("hall"))
    assert "hall" in w.nodes
    n = w.nodes["hall"]
    assert n.id == "hall"
    assert n.brief == {"name": "Hall"}
    assert n.footprint == {"origin": [0.0, 0.0, 0.0],
                            "size": [10.0, 4.0, 10.0]}


def test_add_space_default_seed_is_deterministic_per_id():
    w1 = apply_op(World(), _op_add_space("hall"))
    w2 = apply_op(World(), _op_add_space("hall"))
    assert w1.nodes["hall"].seed == w2.nodes["hall"].seed
    assert w1.nodes["hall"].seed == seed_from_id("hall")


def test_add_space_default_seed_differs_per_id():
    w = apply_op(apply_op(World(), _op_add_space("hall")),
                  _op_add_space("keep"))
    assert w.nodes["hall"].seed != w.nodes["keep"].seed


def test_add_space_explicit_seed_overrides_default():
    w = apply_op(World(), _op_add_space("hall", seed=12345))
    assert w.nodes["hall"].seed == 12345


def test_add_space_duplicate_id_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_space("hall"))


def test_add_space_empty_entities_and_portals():
    w = apply_op(World(), _op_add_space("hall"))
    assert w.nodes["hall"].entities == []
    assert w.nodes["hall"].portals == []


def test_add_space_records_gen_version():
    w = apply_op(World(), _op_add_space("hall", gen_version="v2-procedural"))
    assert w.nodes["hall"].gen_version == "v2-procedural"


# ── 3. add_portal + bidirectional portal listing ─────────────────────


def test_add_portal_valid_references():
    w = apply_op(apply_op(World(), _op_add_space("A")),
                  _op_add_space("B"))
    w2 = apply_op(w, _op_add_portal("p1", frm="A", to="B"))
    assert "p1" in w2.portals
    p = w2.portals["p1"]
    assert p.from_space == "A"
    assert p.to_space == "B"


def test_add_portal_appended_to_both_spaces_lists():
    """A portal is between two spaces — both must list it (W1 LOCALITY
    needs portals easily discoverable from any space)."""
    w = apply_op(apply_op(World(), _op_add_space("A")),
                  _op_add_space("B"))
    w2 = apply_op(w, _op_add_portal("p1", frm="A", to="B"))
    assert "p1" in w2.nodes["A"].portals
    assert "p1" in w2.nodes["B"].portals


def test_add_portal_missing_from_space_raises():
    w = apply_op(World(), _op_add_space("A"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_portal("p1", frm="A", to="GHOST"))


def test_add_portal_missing_to_space_raises():
    w = apply_op(World(), _op_add_space("A"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_portal("p1", frm="GHOST", to="A"))


def test_add_portal_duplicate_id_raises():
    w = apply_op(apply_op(World(), _op_add_space("A")),
                  _op_add_space("B"))
    w = apply_op(w, _op_add_portal("p1", frm="A", to="B"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_portal("p1", frm="A", to="B"))


# ── 4. add_entity ────────────────────────────────────────────────────


def test_add_entity_appends_to_space_entity_list():
    w = apply_op(World(), _op_add_space("hall"))
    w2 = apply_op(w, _op_add_entity("hall", "candle_0",
                                      type="candle", pos=(1.0, 0.0, 1.0)))
    ents = w2.nodes["hall"].entities
    assert len(ents) == 1
    assert ents[0].id == "candle_0"
    assert ents[0].type == "candle"
    assert ents[0].pos == (1.0, 0.0, 1.0)


def test_add_entity_missing_space_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_entity("GHOST", "candle_0"))


def test_add_entity_duplicate_id_in_same_space_raises():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "candle_0"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_add_entity("hall", "candle_0"))


def test_add_entity_keeps_other_spaces_unchanged():
    w = apply_op(apply_op(World(), _op_add_space("A")),
                  _op_add_space("B"))
    w2 = apply_op(w, _op_add_entity("A", "candle_0"))
    assert w2.nodes["B"].entities == []  # LOCALITY: not touched


# ── 5. move_entity (LOCALITY: only the moved space changes) ──────────


def test_move_entity_updates_pos_for_target_entity():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "candle_0",
                                    pos=(1.0, 0.0, 1.0)))
    w2 = apply_op(w, _op_move_entity("hall", "candle_0",
                                       new_pos=(5.0, 0.0, 5.0)))
    moved = next(e for e in w2.nodes["hall"].entities
                 if e.id == "candle_0")
    assert moved.pos == (5.0, 0.0, 5.0)


def test_move_entity_missing_space_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_move_entity("GHOST", "candle_0", (1.0, 0.0, 1.0)))


def test_move_entity_missing_entity_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_move_entity("hall", "ghost", (1.0, 0.0, 1.0)))


def test_move_entity_replaces_only_target_space_node():
    """Crucial LOCALITY invariant: the from/to dict has a NEW entry ONLY
    for the affected space; all other spaces share identity with input."""
    w = apply_op(apply_op(World(), _op_add_space("A")),
                  _op_add_space("B"))
    w = apply_op(w, _op_add_entity("A", "ta",
                                    pos=(1.0, 0.0, 1.0)))
    w = apply_op(w, _op_add_entity("B", "tb",
                                    pos=(1.0, 0.0, 1.0)))
    w2 = apply_op(w, _op_move_entity("A", "ta", (2.0, 0.0, 2.0)))
    # Other space's node is NOT touched
    assert w2.nodes["B"] is w.nodes["B"]


# ── 6. set_property ──────────────────────────────────────────────────


def test_set_property_creates_nested_dict_leaf_on_entity():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "candle_0",
                                    pos=(1.0, 0.0, 1.0),
                                    properties={"lit": {}}))
    w2 = apply_op(w, _op_set_property("entity", "hall", "candle_0",
                                        ("lit", "since"), 42))
    ent = next(e for e in w2.nodes["hall"].entities
                if e.id == "candle_0")
    assert ent.properties["lit"]["since"] == 42


def test_set_property_overwrites_existing_leaf():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "candle_0",
                                    pos=(0, 0, 0),
                                    properties={"lit": {"since": 1}}))
    w2 = apply_op(w, _op_set_property("entity", "hall", "candle_0",
                                        ("lit", "since"), 99))
    ent = next(e for e in w2.nodes["hall"].entities
                if e.id == "candle_0")
    assert ent.properties["lit"]["since"] == 99


def test_set_property_navigates_space_brief_dict():
    w = apply_op(World(), _op_add_space("hall",
                                          brief={"name": "Hall"}))
    w2 = apply_op(w, _op_set_property("space", "hall", None,
                                        ("name",), "Great Hall"))
    assert w2.nodes["hall"].brief["name"] == "Great Hall"


def test_set_property_creates_intermediate_dicts():
    w = apply_op(World(), _op_add_space("hall", brief={}))
    w2 = apply_op(w, _op_set_property("space", "hall", None,
                                        ("nested", "deep", "k"), "v"))
    assert w2.nodes["hall"].brief["nested"]["deep"]["k"] == "v"


def test_set_property_unknown_entity_raises():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "candle_0"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_set_property("entity", "hall", "ghost",
                                       ("k",), "v"))


def test_set_property_unknown_space_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_set_property("space", "ghost", None,
                                       ("k",), "v"))


# ── 7. remove_entity ─────────────────────────────────────────────────


def test_remove_entity_filters_out_target():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "a"))
    w = apply_op(w, _op_add_entity("hall", "b"))
    w2 = apply_op(w, _op_remove_entity("hall", "a"))
    ids = [e.id for e in w2.nodes["hall"].entities]
    assert ids == ["b"]


def test_remove_entity_missing_entity_raises():
    w = apply_op(World(), _op_add_space("hall"))
    w = apply_op(w, _op_add_entity("hall", "a"))
    with pytest.raises(WorldOpError):
        apply_op(w, _op_remove_entity("hall", "ghost"))


# ── 8. Unknown op / shape ───────────────────────────────────────────


def test_unknown_op_raises():
    w = apply_op(World(), _op_add_space("hall"))
    with pytest.raises(WorldOpError):
        apply_op(w, {"op": "delete_everything"})


def test_missing_op_field_raises():
    with pytest.raises(WorldOpError):
        apply_op(World(), {"id": "x"})  # no "op" key


# ── 9. replay folds apply_op over an empty world ─────────────────────


def test_replay_empty_log_returns_empty_world():
    assert replay([]) == World()


def test_replay_single_add_space():
    w = replay([_op_add_space("hall")])
    assert "hall" in w.nodes
    assert len(w.op_log) == 1


def test_replay_full_vocabulary_sequence():
    ops = [
        _op_add_space("hall"),
        _op_add_space("antechamber"),
        _op_add_portal("p_h_a", frm="hall", to="antechamber"),
        _op_add_entity("hall", "candle_0", pos=(1.0, 0.0, 1.0)),
        _op_move_entity("hall", "candle_0", (2.0, 0.0, 2.0)),
        _op_set_property("entity", "hall", "candle_0",
                          ("lit", "since"), 7),
        _op_remove_entity("hall", "candle_0"),
    ]
    w = replay(ops)
    assert set(w.nodes) == {"hall", "antechamber"}
    assert "p_h_a" in w.portals
    assert "p_h_a" in w.nodes["hall"].portals
    assert "p_h_a" in w.nodes["antechamber"].portals
    # candle_0 was added then removed
    assert w.nodes["hall"].entities == []
    # Op log preserved verbatim
    assert w.op_log == ops


def test_replay_keep_pure():
    """replay must NOT mutate the input op_log list."""
    ops = [_op_add_space("hall"), _op_add_space("keep")]
    snap = list(ops)
    replay(ops)
    assert list(ops) == snap
