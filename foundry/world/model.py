"""World model dataclasses (sub-project a, unit 1).

A world is the fold of an append-only operation log (see ``world.operations``).
The model here defines the structure that operations fold into:

    World  ─ nodes: dict[str, SpaceNode]
           ─ portals: dict[str, Portal]
           ─ op_log: list[dict]
           ─ world_bible: {world, region, site}

    SpaceNode  ─ id, seed, brief, footprint
                  entities, portals (ref ids), gen_version

    Portal     ─ id, from_space, to_space, position(s), size(s)

    Entity     ─ id, type, pos, properties

Determinism — every dataclass is replaceable via ``dataclasses.replace``
and is named such that ``A == B`` is content-address equality.  No
attribute is mutated in place after construction; the applier always
constructs new top-level containers.

NOT frozen: ``Entity``, ``Portal``, ``SpaceNode``, ``World`` are unfrozen
because Entity has a ``properties`` dict (mutable for tree-set), and the
whole world-model is replace-rewritten, never mutated.  The contract
"do not mutate; use dataclasses.replace" is enforced by all callers in
``world/operations.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

# ── Seed derivation ────────────────────────────────────────────────────


def seed_from_id(space_id: str) -> int:
    """Deterministic 64-bit seed for a space id.

    Same id → same seed across processes (sha256 is deterministic).
    Caps at 64-bit unsigned so it fits cleanly into Godot's int64.

    This is the per-node seed isolation that anchors Wall W1: every
    space has its OWN seed so a change in one space cannot ripple its
    determinism into another.
    """
    digest = hashlib.sha256(space_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


# ── Entity / Portal ────────────────────────────────────────────────────


@dataclass
class Entity:
    """One placed thing inside a SpaceNode (id, type, position, props)."""

    id: str
    type: str
    pos: tuple[float, float, float]
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Portal:
    """An edge between two SpaceNodes — bidirectional, recorded in both
    spaces' ``portals`` lists so each space can discover it locally."""

    id: str
    from_space: str
    to_space: str
    position: tuple[float, float, float]
    size: tuple[float, float]


# ── SpaceNode ──────────────────────────────────────────────────────────


@dataclass
class SpaceNode:
    """One node of the World-DAG.

    ``brief`` is the structured intent (mirrors the existing Forge Brief —
    same shape, same generator).  ``footprint`` is the space's AABB in
    world coordinates (``{"origin":[x,y,z], "size":[w,h,d]}``).

    ``portals`` is a list of portal ids (the actual portals live in
    ``World.portals``); every portal has both its ``from_space`` AND
    ``to_space`` ids in their respective lists so each space can
    inventory its connections from a single read.

    ``seed`` is a 64-bit int, derived from ``id`` when ``add_space`` is
    called without an explicit seed.  ``gen_version`` is the generator
    version pin (unit 3 will use this for replay).
    """

    id: str
    seed: int
    brief: dict[str, Any] = field(default_factory=dict)
    footprint: dict[str, list[float]] = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    portals: list[str] = field(default_factory=list)
    gen_version: str = "v1"


# ── World ──────────────────────────────────────────────────────────────


def _default_world_bible() -> dict[str, dict]:
    """The hierarchical World Bible (Cohesion Contract root — sub-project c).

    Three nested layers: ``world`` -> ``region`` -> ``site``.  Empty by
    default; downstream op-flows and validators populate them.  This
    factory returns a fresh dict on every call so no two Worlds share
    the same default object.
    """
    return {"world": {}, "region": {}, "site": {}}


@dataclass
class World:
    """The persistent world state — the fold of its op_log.

    The durable truth is the op_log (replayable from the file); ``nodes``,
    ``portals`` and ``world_bible`` are the materialized state derived
    by folding that log via ``apply_op``.  Both views agree because
    ``apply_op`` is PURE and deterministic.
    """

    nodes: dict[str, SpaceNode] = field(default_factory=dict)
    op_log: list[dict] = field(default_factory=list)
    portals: dict[str, Portal] = field(default_factory=dict)
    world_bible: dict[str, dict] = field(default_factory=_default_world_bible)
