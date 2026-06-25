"""World operations — v1 vocabulary (sub-project a, unit 1).

The world is the FOLD of an append-only operation log.  ``apply_op``
returns a NEW world (pure); ``replay`` folds ``apply_op`` over an empty
world to reconstruct state from a saved op_log.

Op vocabulary
-------------

Every op is a dict. The first key is ``op``, the rest are op-specific.
Unknown op or missing referent raises ``WorldOpError``.

* ``add_space`` — ``id, brief, footprint, seed? (default derived), gen_version? (default ``"v1"``)``
* ``add_portal`` — ``id, from_space, to_space, position, size``
* ``add_entity``  — ``space, entity:{id, type, pos, properties}``
* ``move_entity`` — ``space, entity_id, new_pos``
* ``set_property`` — ``target_kind: space|entity, space, entity_id?, path, value``
* ``remove_entity`` — ``space, entity_id``

Referential integrity (unit 1 scope)
-----------------------------------

* ``add_space``: rejects duplicate ``id``.
* ``add_portal``: rejects missing ``from_space``/``to_space``.
* ``add_portal``: rejects duplicate ``id``.
* ``add_entity``: rejects missing ``space`` and duplicate entity id in same space.
* ``move_entity``/``remove_entity``: reject missing space or missing entity.
* ``set_property``: rejects missing space, missing entity (entity mode), empty path.

Spatial bounds-checking (footprint intersection, portal-in-shell,
entity-out-of-footprint) is **unit 2** (the W3 validation gate).  This
unit is the spine: referential integrity + PURE applier + deterministic
replay + LOCALITY-appliance.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from world.model import Entity, Portal, SpaceNode, World, seed_from_id

# ── Errors ────────────────────────────────────────────────────────────


class WorldOpError(Exception):
    """Raised when an op is malformed, has an unknown ``op`` field, or
    refers to a space / entity / portal that does not exist.

    This is the v1 (referential) layer.  Unit 2 will surface spatial
    failures with this same exception type so callers can handle them
    uniformly without subclassing.
    """


# ── Public entry point ───────────────────────────────────────────────


# A small dispatch table — keeps ``apply_op`` cheap, makes the vocabulary
# auditable, and lets unit 2 add new ops without rewriting the applier.
_HANDLERS: dict[str, Callable[[World, dict], World]] = {}


def apply_op(world: World, op: dict) -> World:
    """Apply ``op`` to ``world``; return a NEW world (input untouched).

    Pure:
      * the input world's attributes are NOT mutated;
      * the op log is appended (an immutable snapshot of the op dict);
      * unknown ``op`` or missing referent → ``WorldOpError``.

    Every handler uses ``dataclasses.replace`` and dict-spread; nothing
    reuses the input's mutable containers.
    """
    if not isinstance(op, dict):
        raise WorldOpError(f"op must be a dict, got {type(op).__name__}")
    op_name = op.get("op")
    if not isinstance(op_name, str) or not op_name:
        raise WorldOpError(f"op missing 'op' key: {op!r}")
    handler = _HANDLERS.get(op_name)
    if handler is None:
        raise WorldOpError(f"unknown op: {op_name!r}")
    return handler(world, op)


def replay(ops: list[dict]) -> World:
    """Fold ``apply_op`` over an empty World.  Returns the final World.

    ``ops`` is the canonical list-of-dicts content of op_log.json. The
    returned world's ``op_log`` matches the input.
    """
    world = World()
    for op in ops:
        world = apply_op(world, op)
    return world


# ── Helpers ────────────────────────────────────────────────────────────


def _append(world: World, op: dict) -> World:
    """Append the op verbatim to op_log.  The op dict is held by
    reference — callers must treat it as immutable."""
    return dataclasses.replace(world, op_log=[*world.op_log, op])


def _replace_node(world: World, sid: str, new_node: SpaceNode) -> World:
    """Replace a single node in ``world.nodes`` (LOCALITY-preserving:
    other space nodes stay bit-identical)."""
    return dataclasses.replace(
        world, nodes={**world.nodes, sid: new_node}
    )


def _set_in_dict(d: dict, path: list, value: Any) -> dict:
    """Pure: navigate-or-create nested dicts along ``path``, set leaf
    ``value``.  Returns a NEW dict; input is untouched.

    Intermediate dicts are created as needed; missing leaves are
    inserted; existing leaves are overwritten.  Empty ``path`` is
    rejected at the caller — there is no meaningful "set the root".
    """
    if not path:
        raise WorldOpError("set_property path must be non-empty")
    head, *rest = path
    if not rest:
        return {**d, head: value}
    sub = d.get(head)
    if not isinstance(sub, dict):
        sub_new: dict = {}
    else:
        sub_new = sub
    return {**d, head: _set_in_dict(sub_new, rest, value)}


# ── Op handlers ────────────────────────────────────────────────────────


def _do_add_space(world: World, op: dict) -> World:
    sid = op["id"]
    if sid in world.nodes:
        raise WorldOpError(f"space already exists: {sid!r}")
    seed_value = op.get("seed")
    if seed_value is None:
        seed_value = seed_from_id(sid)
    elif not isinstance(seed_value, int) or isinstance(seed_value, bool):
        raise WorldOpError("add_space.seed must be an int")
    node = SpaceNode(
        id=sid,
        seed=seed_value,
        brief=dict(op["brief"]),
        footprint=dict(op["footprint"]),
        entities=[],
        portals=[],
        gen_version=op.get("gen_version", "v1"),
    )
    return _append(_replace_node(world, sid, node), op)


def _do_add_portal(world: World, op: dict) -> World:
    pid = op["id"]
    if pid in world.portals:
        raise WorldOpError(f"portal already exists: {pid!r}")
    frm = op["from_space"]
    to = op["to_space"]
    if frm not in world.nodes:
        raise WorldOpError(f"from_space not found: {frm!r}")
    if to not in world.nodes:
        raise WorldOpError(f"to_space not found: {to!r}")
    portal = Portal(
        id=pid,
        from_space=frm,
        to_space=to,
        position=tuple(op["position"]),
        size=tuple(op["size"]),
    )
    new_portals = {**world.portals, pid: portal}
    # Append the portal id to BOTH spaces' portal lists — a portal is
    # intrinsic to both endpoints.
    new_nodes = {
        sid: (dataclasses.replace(n, portals=[*n.portals, pid])
              if sid in (frm, to) else n)
        for sid, n in world.nodes.items()
    }
    return _append(
        dataclasses.replace(world, portals=new_portals, nodes=new_nodes),
        op,
    )


def _do_add_entity(world: World, op: dict) -> World:
    space_id = op["space"]
    space = world.nodes.get(space_id)
    if space is None:
        raise WorldOpError(f"space not found: {space_id!r}")
    ent_dict = op["entity"]
    eid = ent_dict["id"]
    if any(e.id == eid for e in space.entities):
        raise WorldOpError(
            f"entity already exists in space {space_id!r}: {eid!r}"
        )
    new_entity = Entity(
        id=eid,
        type=ent_dict["type"],
        pos=tuple(ent_dict["pos"]),
        properties=dict(ent_dict.get("properties") or {}),
    )
    new_space = dataclasses.replace(
        space, entities=[*space.entities, new_entity]
    )
    return _append(_replace_node(world, space_id, new_space), op)


def _do_move_entity(world: World, op: dict) -> World:
    space_id = op["space"]
    space = world.nodes.get(space_id)
    if space is None:
        raise WorldOpError(f"space not found: {space_id!r}")
    eid = op["entity_id"]
    new_pos = tuple(op["new_pos"])
    new_entities: list[Entity] = []
    found = False
    for e in space.entities:
        if e.id == eid:
            new_entities.append(dataclasses.replace(e, pos=new_pos))
            found = True
        else:
            new_entities.append(e)
    if not found:
        raise WorldOpError(
            f"entity not found in space {space_id!r}: {eid!r}"
        )
    new_space = dataclasses.replace(space, entities=new_entities)
    return _append(_replace_node(world, space_id, new_space), op)


def _do_remove_entity(world: World, op: dict) -> World:
    space_id = op["space"]
    space = world.nodes.get(space_id)
    if space is None:
        raise WorldOpError(f"space not found: {space_id!r}")
    eid = op["entity_id"]
    new_entities: list[Entity] = []
    found = False
    for e in space.entities:
        if e.id == eid:
            found = True
        else:
            new_entities.append(e)
    if not found:
        raise WorldOpError(
            f"entity not found in space {space_id!r}: {eid!r}"
        )
    new_space = dataclasses.replace(space, entities=new_entities)
    return _append(_replace_node(world, space_id, new_space), op)


def _do_set_property(world: World, op: dict) -> World:
    space_id = op["space"]
    space = world.nodes.get(space_id)
    if space is None:
        raise WorldOpError(f"space not found: {space_id!r}")
    target_kind = op.get("target_kind")
    if target_kind not in ("space", "entity"):
        raise WorldOpError(
            f"set_property target_kind must be 'space' or 'entity', "
            f"got {target_kind!r}"
        )
    path = op.get("path")
    if not isinstance(path, (list, tuple)) or not path:
        raise WorldOpError(
            "set_property path must be a non-empty list of keys"
        )
    value = op["value"]
    if target_kind == "space":
        new_brief = _set_in_dict(space.brief, list(path), value)
        new_space = dataclasses.replace(space, brief=new_brief)
    else:  # target_kind == "entity"
        eid = op.get("entity_id")
        if eid is None:
            raise WorldOpError(
                "set_property target_kind='entity' requires entity_id"
            )
        # Find the entity (raises if missing)
        idx = next(
            (i for i, e in enumerate(space.entities) if e.id == eid),
            None,
        )
        if idx is None:
            raise WorldOpError(
                f"entity not found in space {space_id!r}: {eid!r}"
            )
        target = space.entities[idx]
        new_props = _set_in_dict(target.properties, list(path), value)
        new_target = dataclasses.replace(target, properties=new_props)
        new_entities = list(space.entities)
        new_entities[idx] = new_target
        new_space = dataclasses.replace(space, entities=new_entities)
    return _append(_replace_node(world, space_id, new_space), op)


# Register handlers in the dispatch table (kept here so the vocabulary
# is auditable in one place).
_HANDLERS["add_space"] = _do_add_space
_HANDLERS["add_portal"] = _do_add_portal
_HANDLERS["add_entity"] = _do_add_entity
_HANDLERS["move_entity"] = _do_move_entity
_HANDLERS["set_property"] = _do_set_property
_HANDLERS["remove_entity"] = _do_remove_entity
