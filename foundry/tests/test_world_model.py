"""TDD tests for ``foundry.world.model`` — the dataclasses of the
persistent world model (unit 1 of sub-project a).

The data model — and ONLY the data model — lives here. Operations,
hashing, and persistence are tested in their own files.

Each test ENCODES a property the spec calls out, so the test suite
is itself a specification of what "the world data model" must be.
"""

from __future__ import annotations

import dataclasses
import hashlib

from world.model import Entity, Portal, SpaceNode, World, seed_from_id


# ── Helpers ───────────────────────────────────────────────────────────


def _ent(id: str = "throne_0", type: str = "throne",
         pos=(0.0, 0.0, 0.0), properties=None) -> Entity:
    return Entity(id=id, type=type, pos=pos, properties=properties or {})


def _portal(id: str = "p0", frm="A", to="B",
            pos=(0.0, 0.0, 0.0), size=(1.0, 2.0)) -> Portal:
    return Portal(id=id, from_space=frm, to_space=to,
                  position=pos, size=size)


def _space(id: str = "hall", seed: int | None = None,
           brief=None, footprint=None,
           entities=(), portals=(),
           gen_version: str = "v1") -> SpaceNode:
    if seed is None:
        seed = seed_from_id(id)
    if brief is None:
        brief = {"name": id.title()}
    if footprint is None:
        footprint = {"origin": [0.0, 0.0, 0.0], "size": [10.0, 4.0, 10.0]}
    return SpaceNode(
        id=id, seed=seed, brief=brief, footprint=footprint,
        entities=list(entities), portals=list(portals),
        gen_version=gen_version,
    )


# ── Brand-new dataclasses exist with the spec-declared fields ────────


def test_entity_fields_declared():
    e = _ent()
    assert e.id == "throne_0"
    assert e.type == "throne"
    assert e.pos == (0.0, 0.0, 0.0)
    assert e.properties == {}


def test_portal_fields_declared():
    p = _portal()
    assert p.id == "p0"
    assert p.from_space == "A"
    assert p.to_space == "B"
    assert p.position == (0.0, 0.0, 0.0)
    assert p.size == (1.0, 2.0)


def test_space_node_fields_declared():
    """SpaceNode MUST id/seed/brief/footprint/entities/portals/gen_version."""
    s = _space()
    assert s.id == "hall"
    assert isinstance(s.seed, int)
    assert s.brief == {"name": "Hall"}
    assert s.footprint == {"origin": [0.0, 0.0, 0.0], "size": [10.0, 4.0, 10.0]}
    assert s.entities == []
    assert s.portals == []
    assert s.gen_version == "v1"


def test_world_fields_declared():
    """World MUST nodes/op_log/portals/world_bible (the spec's canonical shape)."""
    w = World()
    assert w.nodes == {}
    assert w.op_log == []
    assert w.portals == {}
    assert w.world_bible == {"world": {}, "region": {}, "site": {}}


def test_world_has_default_world_bible_layers():
    """The World Bible is hierarchical world → region → site."""
    w = World()
    assert set(w.world_bible.keys()) == {"world", "region", "site"}


# ── dataclasses.replace works on every model class ───────────────────


def test_entity_replace_works():
    e = _ent()
    e2 = dataclasses.replace(e, pos=(1.0, 2.0, 3.0))
    assert e2.pos == (1.0, 2.0, 3.0)
    assert e2.id == e.id
    assert e2.type == e.type
    assert e2.properties == e.properties


def test_portal_replace_works():
    p = _portal()
    p2 = dataclasses.replace(p, size=(3.0, 4.0))
    assert p2.size == (3.0, 4.0)
    assert p2.id == p.id


def test_space_node_replace_works():
    s = _space()
    s2 = dataclasses.replace(s, entities=[_ent()])
    assert len(s2.entities) == 1
    assert s2.entities[0].id == "throne_0"
    # Original unchanged
    assert s.entities == []


# ── Equality: two equal-value Worlds compare equal ───────────────────


def test_world_equality_round_trip():
    w1 = World(nodes={"A": _space("A")},
               portals={}, op_log=[],
               world_bible={"world": {}, "region": {}, "site": {}})
    w2 = World(nodes={"A": _space("A")},
               portals={}, op_log=[],
               world_bible={"world": {}, "region": {}, "site": {}})
    assert w1 == w2


def test_world_inequality_when_nodes_differ():
    w1 = World(nodes={"A": _space("A")})
    w2 = World(nodes={"A": _space("A"),
                       "B": _space("B")})
    assert w1 != w2


# ── Seed derivation is deterministic acyclic per id ──────────────────


def test_seed_from_id_is_deterministic():
    assert seed_from_id("hall") == seed_from_id("hall")


def test_seed_from_id_is_different_per_id():
    assert seed_from_id("hall") != seed_from_id("keep")
    assert seed_from_id("A") != seed_from_id("B")


def test_seed_from_id_is_int():
    s = seed_from_id("hall")
    assert isinstance(s, int)
    # Capped at 64-bit unsigned so it fits cleanly into Godot's int64.
    assert 0 <= s < (1 << 64)


def test_seed_from_id_returns_same_across_calls():
    # Same Python, same Python version, same hash → same seed.
    seeds = {seed_from_id(f"space_{i}") for i in range(20)}
    # Re-running the same id always returns the same seed.
    for sid in [f"space_{i}" for i in range(5)]:
        assert seed_from_id(sid) == seed_from_id(sid)
    assert len(seeds) == 20  # all distinct across distinct ids
