"""TDD tests for the LOCALITY property of the world model (W1).

Spec line:  "after ``move_entity`` in space A, ``node_content_hash`` of
every OTHER space is UNCHANGED; adding a new space does not change any
existing space's seed or hash."

This is Wall W1 (Local edit without global cascade). It is the spine of
World Engine sub-project (a): patches to a single space are LOCAL — they
do not re-cascade seeds, regen other spaces, or rewrite the world's
content address except via the unavoidable append to op_log.

These tests lock the property into a sharp regression: any future change
that "fixes a bug" by re-touching unrelated spaces (e.g. recomputing
seeds on add_portal, normalizing portals when add_entity runs, etc.)
will be caught by these tests.
"""

from __future__ import annotations

from world.hashing import node_content_hash
from world.operations import apply_op, replay

# ── Move-entity LOCALITY ─────────────────────────────────────────────


def test_move_entity_in_A_does_not_change_B_node_hash():
    """Wall W1: a move_entity in A leaves the content hash of B UNCHANGED."""
    base_ops = [
        _add_space("A"),
        _add_space("B"),
        _add_entity("A", "ta", pos=(1.0, 0.0, 1.0)),
        _add_entity("B", "tb", pos=(3.0, 0.0, 3.0)),
    ]
    w_before = replay(base_ops)
    hash_B_before = node_content_hash(w_before.nodes["B"])
    seed_B_before = w_before.nodes["B"].seed
    brief_B_before = dict(w_before.nodes["B"].brief)

    w_after = apply_op(w_before, _move_entity("A", "ta", (2.0, 0.0, 2.0)))

    assert node_content_hash(w_after.nodes["B"]) == hash_B_before, (
        "W1 LOCALITY VIOLATED: move_entity in A changed node_content_hash(B)"
    )
    assert w_after.nodes["B"].seed == seed_B_before, (
        "W1 LOCALITY VIOLATED: move_entity in A changed B's seed"
    )
    assert w_after.nodes["B"].brief == brief_B_before


def test_add_entity_in_A_does_not_change_B_node_hash():
    w_before = replay([_add_space("A"), _add_space("B")])
    hash_B_before = node_content_hash(w_before.nodes["B"])
    w_after = apply_op(w_before, _add_entity("A", "ta"))
    assert node_content_hash(w_after.nodes["B"]) == hash_B_before


def test_remove_entity_in_A_does_not_change_B_node_hash():
    w_before = replay([_add_space("A"), _add_space("B"),
                       _add_entity("A", "ta")])
    hash_B_before = node_content_hash(w_before.nodes["B"])
    w_after = apply_op(w_before, _remove_entity("A", "ta"))
    assert node_content_hash(w_after.nodes["B"]) == hash_B_before


def test_set_property_in_A_does_not_change_B_node_hash():
    w_before = replay([_add_space("A", brief={"name": "A name"}),
                       _add_space("B", brief={"name": "B name"}),
                       _add_entity("A", "ta")])
    hash_B_before = node_content_hash(w_before.nodes["B"])
    w_after = apply_op(w_before, _set_property_space_brief(
        "A", ("name",), "New A name"))
    assert node_content_hash(w_after.nodes["B"]) == hash_B_before


def test_add_portal_between_A_and_new_B_does_not_change_uninvolved_spaces():
    """A portal between A and a NEW B; a third uninvolved space C must
    remain BYTE-IDENTICAL (incl. seed + node_content_hash)."""
    ops_before = [_add_space("A"), _add_space("C")]
    w_before = replay(ops_before)
    hash_C_before = node_content_hash(w_before.nodes["C"])
    seed_C_before = w_before.nodes["C"].seed

    ops_after = ops_before + [_add_space("B"), _add_portal("p_AB", "A", "B")]
    w_after = replay(ops_after)

    assert node_content_hash(w_after.nodes["C"]) == hash_C_before, (
        "W1 LOCALITY VIOLATED: adding a portal changed an unrelated space's hash"
    )
    assert w_after.nodes["C"].seed == seed_C_before


# ── Add-space LOCALITY ───────────────────────────────────────────────


def test_add_space_does_not_change_existing_space_seed():
    w_before = replay([_add_space("A")])
    seed_A_before = w_before.nodes["A"].seed
    w_after = apply_op(w_before, _add_space("B"))
    assert w_after.nodes["A"].seed == seed_A_before


def test_add_space_does_not_change_existing_space_hash():
    w_before = replay([_add_space("A", brief={"name": "A"})])
    hash_A_before = node_content_hash(w_before.nodes["A"])
    w_after = apply_op(w_before, _add_space("B", brief={"name": "B"}))
    assert node_content_hash(w_after.nodes["A"]) == hash_A_before


def test_add_space_does_not_change_existing_space_brief():
    w_before = replay([_add_space("A", brief={"name": "A"})])
    brief_A_before = dict(w_before.nodes["A"].brief)
    w_after = apply_op(w_before, _add_space("B", brief={"name": "B"}))
    assert w_after.nodes["A"].brief == brief_A_before


# ── Combined scenario: W1 LOCALITY under a 4-op patch chain ──────────


def test_locality_under_chain_of_patches_on_one_space():
    """A long chain of ops all targeting A; B and C hashes stable."""
    ops_before = [
        _add_space("A", brief={"name": "A"}),
        _add_space("B", brief={"name": "B"}),
        _add_space("C", brief={"name": "C"}),
    ]
    w_before = replay(ops_before)
    h_A_before = node_content_hash(w_before.nodes["A"])
    h_B_before = node_content_hash(w_before.nodes["B"])
    h_C_before = node_content_hash(w_before.nodes["C"])

    # Apply a chain touching A only
    w = w_before
    w = apply_op(w, _add_entity("A", "t1", pos=(1, 0, 1)))
    w = apply_op(w, _add_entity("A", "t2", pos=(2, 0, 2)))
    w = apply_op(w, _move_entity("A", "t1", (3, 0, 3)))
    w = apply_op(w, _set_property_space_brief("A", ("name",), "Great A"))
    w = apply_op(w, _remove_entity("A", "t2"))

    # B and C are byte-identical
    assert node_content_hash(w.nodes["B"]) == h_B_before
    assert node_content_hash(w.nodes["C"]) == h_C_before
    # ... but A is different (the patch chain touched it).
    assert node_content_hash(w.nodes["A"]) != h_A_before


# ── Op-level helpers ─────────────────────────────────────────────────


def _add_space(id: str, brief=None, footprint=None, seed=None):
    op = {"op": "add_space", "id": id,
          "brief": brief or {"name": id.title()},
          "footprint": footprint or {"origin": [0, 0, 0],
                                       "size": [10, 4, 10]}}
    if seed is not None:
        op["seed"] = seed
    return op


def _add_portal(id: str, frm: str, to: str,
                pos=(0, 0, 0), size=(1, 2)):
    return {"op": "add_portal", "id": id,
            "from_space": frm, "to_space": to,
            "position": list(pos), "size": list(size)}


def _add_entity(space: str, id: str, pos=(0, 0, 0),
                type: str = "thing", properties=None):
    return {"op": "add_entity", "space": space,
            "entity": {"id": id, "type": type,
                        "pos": list(pos),
                        "properties": properties or {}}}


def _move_entity(space: str, entity_id: str, new_pos):
    return {"op": "move_entity", "space": space,
            "entity_id": entity_id, "new_pos": list(new_pos)}


def _set_property_space_brief(space: str, path: tuple, value):
    return {"op": "set_property", "target_kind": "space",
            "space": space, "path": list(path), "value": value}


def _remove_entity(space: str, entity_id: str):
    return {"op": "remove_entity", "space": space,
            "entity_id": entity_id}
