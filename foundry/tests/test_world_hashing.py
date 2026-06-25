"""TDD tests for ``foundry.world.hashing`` + replay byte-identical.

Property: the world is the fold of an append-only operation log. So
two different processes that have the same op_log MUST produce the same
hash — that's what makes replay across machines / restarts trustworthy.

Properties this test ENCODES:

  1. ``canonical_json`` is sort-key stable (independent of insertion order).
  2. ``world_state_hash`` is sha256 over canonical_json(op_log) — content
     address of the whole world.
  3. ``node_content_hash`` is sha256 over canonical(brief+seed+gen_version+
     entities+portals) — content address of one space (used by unit-2's
     per-node regen cache + W1 LOCALITY tests).
  4. replay(ops) twice gives byte-identical snapshots deterministically.
  5. node_content_hash is stable across two replays of the same op_log.
"""

from __future__ import annotations

import hashlib
import json

from world.hashing import canonical_json, node_content_hash, world_state_hash
from world.model import Entity, Portal, SpaceNode, World
from world.operations import replay


# ── canonical_json: sort-key stability ───────────────────────────────


def test_canonical_json_sorts_top_level_keys():
    """Two dicts with same content but different insertion order → identical
    canonical form."""
    a = canonical_json({"z": 1, "a": 2, "m": 3})
    b = canonical_json({"m": 3, "a": 2, "z": 1})
    c = canonical_json({"a": 2, "m": 3, "z": 1})
    assert a == b == c


def test_canonical_json_sorts_nested_keys():
    a = canonical_json({"outer": {"z": 1, "a": 2}})
    b = canonical_json({"outer": {"a": 2, "z": 1}})
    assert a == b


def test_canonical_json_serializes_tuples_as_arrays():
    """Position tuples serialize as JSON arrays — order matters, content stable."""
    assert canonical_json([1, 2, 3]) == "[1,2,3]"
    assert canonical_json((1, 2, 3)) == "[1,2,3]"


def test_canonical_json_emits_no_spaces():
    """Compact JSON: no insignificant whitespace (so hashes are tight)."""
    out = canonical_json({"a": 1, "b": 2})
    assert " " not in out


def test_canonical_json_round_trip_via_load():
    """canonical_json output is valid JSON."""
    obj = {"op": "add_space", "id": "hall",
           "brief": {"name": "Hall"}, "footprint": {"origin": [0, 0, 0]}}
    parsed = json.loads(canonical_json(obj))
    assert parsed == obj


# ── world_state_hash: sha256(canonical_json(op_log)) ─────────────────


def test_world_state_hash_uses_only_op_log():
    """An empty world hashes to the hash of an empty list — nodes/portals/
    world_bible don't pollute the content address."""
    h_empty = world_state_hash(World())
    h_same_empty = world_state_hash(
        World(nodes={"X": SpaceNode(id="X", seed=0, brief={},
                                     footprint={"origin": [0, 0, 0],
                                                 "size": [1, 1, 1]},
                                     entities=[], portals=[],
                                     gen_version="v1")},
              portals={}, op_log=[], world_bible={})
    )
    assert h_empty == h_same_empty


def test_world_state_hash_depends_only_on_op_log_content():
    """Two worlds with same op_log → same hash (even if constructed from
    different starting states)."""
    op = {"op": "add_space", "id": "hall",
          "brief": {"name": "Hall"},
          "footprint": {"origin": [0, 0, 0], "size": [10, 4, 10]}}
    a = World(op_log=[op])
    b = World(op_log=[op], world_bible={"world": {"theme": "x"}})
    assert world_state_hash(a) == world_state_hash(b)


def test_world_state_hash_format_is_sha256_hex():
    h = world_state_hash(World())
    hex_obj = hashlib.sha256(b"[]").hexdigest()
    assert h == hex_obj
    assert len(h) == 64  # sha256 hex


def test_world_state_hash_changes_when_op_log_grows():
    h0 = world_state_hash(World(op_log=[]))
    h1 = world_state_hash(World(op_log=[{"op": "add_space",
                                          "id": "x",
                                          "brief": {}, "footprint":
                                          {"origin": [0, 0, 0],
                                           "size": [1, 1, 1]}}]))
    assert h0 != h1


# ── node_content_hash ────────────────────────────────────────────────


def test_node_content_hash_depends_on_brief_seed_gen_version():
    """Three inputs into the hash — changing each one must change the hash."""
    base = SpaceNode(id="hall", seed=42, brief={"name": "Hall"},
                      footprint={"origin": [0, 0, 0], "size": [10, 4, 10]},
                      entities=[], portals=[], gen_version="v1")
    h_base = node_content_hash(base)
    # changing brief
    assert node_content_hash(
        dataclasses_replace_id(base, brief={"name": "Other"})
    ) != h_base
    # changing seed
    assert node_content_hash(
        dataclasses_replace_id(base, seed=99)
    ) != h_base
    # changing gen_version
    assert node_content_hash(
        dataclasses_replace_id(base, gen_version="v2")
    ) != h_base


def test_node_content_hash_independent_of_id_field():
    """The id is metadata; the content hash is id-independent so that
    different ids with the same content hash-collide (spawned duplicates
    can dedupe). For unit 1 we're content-addressing the (brief,seed,
    gen_version,entities,portals) tuple."""
    a = SpaceNode(id="A", seed=42, brief={"name": "Hall"},
                   footprint={"origin": [0, 0, 0], "size": [10, 4, 10]},
                   entities=[], portals=[], gen_version="v1")
    b = SpaceNode(id="B", seed=42, brief={"name": "Hall"},
                   footprint={"origin": [0, 0, 0], "size": [10, 4, 10]},
                   entities=[], portals=[], gen_version="v1")
    assert node_content_hash(a) == node_content_hash(b)


def test_node_content_hash_changes_when_entity_added():
    s_no = SpaceNode(id="hall", seed=42, brief={"name": "Hall"},
                      footprint={"origin": [0, 0, 0], "size": [10, 4, 10]},
                      entities=[], portals=[], gen_version="v1")
    s_one = dataclasses_replace_id(
        s_no, entities=[Entity(id="t", type="table", pos=(0, 0, 0),
                                 properties={})],
    )
    assert node_content_hash(s_no) != node_content_hash(s_one)


def test_node_content_hash_changes_when_entity_moved():
    s0 = SpaceNode(id="hall", seed=42, brief={"name": "Hall"},
                    footprint={"origin": [0, 0, 0], "size": [10, 4, 10]},
                    entities=[Entity(id="t", type="table",
                                      pos=(1.0, 0.0, 1.0), properties={})],
                    portals=[], gen_version="v1")
    s1 = dataclasses_replace_id(
        s0,
        entities=[Entity(id="t", type="table", pos=(2.0, 0.0, 2.0),
                           properties={})],
    )
    assert node_content_hash(s0) != node_content_hash(s1)


def test_node_content_hash_format_is_sha256_hex():
    h = node_content_hash(SpaceNode(id="x", seed=0, brief={},
                                       footprint={"origin": [0, 0, 0],
                                                   "size": [1, 1, 1]},
                                       entities=[], portals=[],
                                       gen_version="v1"))
    assert len(h) == 64


# Helper (dataclasses.replace inline so we can keep one helper above)
import dataclasses as _dc


def dataclasses_replace_id(node, **kwargs):
    return _dc.replace(node, **kwargs)


# ── Byte-identical replay: replay(ops) twice == replay(ops) twice ────


def test_replay_byte_identical_snapshot():
    """Two replays of the same op_log produce Worlds whose canonical JSON
    is byte-identical."""
    ops = [
        {"op": "add_space", "id": "hall",
          "brief": {"name": "Hall", "tags": ["keep"]},
          "footprint": {"origin": [0, 0, 0], "size": [10, 4, 10]}},
        {"op": "add_space", "id": "keep",
          "brief": {"name": "Keep"},
          "footprint": {"origin": [20, 0, 0], "size": [12, 6, 12]}},
        {"op": "add_portal", "id": "p_hk", "from_space": "hall",
          "to_space": "keep", "position": [10, 0, 0], "size": [1, 2]},
        {"op": "add_entity", "space": "hall",
          "entity": {"id": "t1", "type": "table",
                      "pos": [1, 0, 1], "properties": {"wood": "oak"}}},
        {"op": "move_entity", "space": "hall", "entity_id": "t1",
          "new_pos": [2, 0, 2]},
        {"op": "set_property", "target_kind": "entity", "space": "hall",
          "entity_id": "t1", "path": ["wear"], "value": 0.8},
        {"op": "remove_entity", "space": "hall", "entity_id": "t1"},
    ]
    w1 = replay(ops)
    w2 = replay(ops)
    assert canonical_json({"nodes": _snapshot_nodes(w1),
                            "portals": _snapshot_portals(w1),
                            "op_log": w1.op_log,
                            "world_bible": w1.world_bible}) == \
           canonical_json({"nodes": _snapshot_nodes(w2),
                            "portals": _snapshot_portals(w2),
                            "op_log": w2.op_log,
                            "world_bible": w2.world_bible})


def _snapshot_nodes(world):
    return {sid: {"id": n.id, "seed": n.seed, "brief": n.brief,
                   "footprint": n.footprint,
                   "entities": [{"id": e.id, "type": e.type,
                                  "pos": e.pos,
                                  "properties": e.properties}
                                  for e in n.entities],
                   "portals": list(n.portals),
                   "gen_version": n.gen_version}
            for sid, n in world.nodes.items()}


def _snapshot_portals(world):
    return {pid: {"id": p.id, "from_space": p.from_space,
                    "to_space": p.to_space,
                    "position": p.position, "size": p.size}
            for pid, p in world.portals.items()}


def test_replay_world_state_hash_stable_across_replays():
    """Two replays of the same op_log give the same world_state_hash."""
    ops = [{"op": "add_space", "id": "hall",
             "brief": {"name": "Hall"},
             "footprint": {"origin": [0, 0, 0],
                            "size": [10, 4, 10]}}]
    w1 = replay(ops)
    w2 = replay(ops)
    assert world_state_hash(w1) == world_state_hash(w2)
