"""World query layer — sub-project (a), unit 4 (Wall W2 prerequisite).

Read-only spatial/semantic queries over a ``World``. This is the substrate
the NL editor (sub-project b) needs BEFORE it proposes an edit:

* ``neighbors`` — spaces reachable from a space via portals.
* ``direction`` — the cardinal/vertical direction from one space to another
  (so "add a courtyard to the north" can be grounded / inverted).
* ``find_entities`` — resolve references ("the throne" → which entities).
* ``world_index`` — a COMPACT, LLM-consumable map of the whole world
  (ids, themes, centres, entity inventory, neighbours-with-directions) so
  the model never needs the full geometry in context.

All functions are PURE (no mutation). Direction convention (Godot-aligned):
``+X = east, -X = west, -Z = north, +Z = south, +Y = up, -Y = down`` — the
dominant axis of the centre-to-centre delta wins; a ~zero delta is "here".
"""

from __future__ import annotations

from world.assembly import footprint_centre
from world.model import Entity, World

_EPS = 1e-9


def neighbors(world: World, space_id: str) -> list[tuple[str, str]]:
    """``[(portal_id, other_space_id), …]`` for every portal touching
    ``space_id`` (deterministic order: sorted by portal id)."""
    out = []
    for pid in sorted(world.portals):
        p = world.portals[pid]
        if p.from_space == space_id:
            out.append((pid, p.to_space))
        elif p.to_space == space_id:
            out.append((pid, p.from_space))
    return out


def direction(world: World, from_id: str, to_id: str) -> str:
    """Dominant-axis direction from ``from_id`` to ``to_id`` (see module
    docstring for the convention). Returns 'here' if centres coincide, or
    'unknown' if either space is missing/malformed."""
    a, b = world.nodes.get(from_id), world.nodes.get(to_id)
    if a is None or b is None or not a.footprint or not b.footprint:
        return "unknown"
    ca, cb = footprint_centre(a.footprint), footprint_centre(b.footprint)
    dx, dy, dz = cb[0] - ca[0], cb[1] - ca[1], cb[2] - ca[2]
    if abs(dx) < _EPS and abs(dy) < _EPS and abs(dz) < _EPS:
        return "here"
    ax, ay, az = abs(dx), abs(dy), abs(dz)
    if ax >= ay and ax >= az:
        return "east" if dx > 0 else "west"
    if az >= ay:
        return "north" if dz < 0 else "south"
    return "up" if dy > 0 else "down"


def find_entities(
    world: World, *, type: str | None = None, space: str | None = None
) -> list[tuple[str, Entity]]:
    """All ``(space_id, Entity)`` matching the filters (both optional).
    Deterministic order: by space id, then the entity's order in the space."""
    out = []
    for sid in sorted(world.nodes):
        if space is not None and sid != space:
            continue
        for e in world.nodes[sid].entities:
            if type is not None and e.type != type:
                continue
            out.append((sid, e))
    return out


def space_summary(world: World, space_id: str) -> dict:
    """Compact summary of one space: id, theme, centre, size, entity
    inventory, and neighbours with directions."""
    node = world.nodes[space_id]
    centre = footprint_centre(node.footprint) if node.footprint else None
    size = list(node.footprint.get("size", [])) if node.footprint else []
    return {
        "id": node.id,
        "theme": node.brief.get("theme"),
        "centre": list(centre) if centre else None,
        "size": size,
        "entities": [{"id": e.id, "type": e.type} for e in node.entities],
        "neighbors": [
            {"portal": pid, "to": other, "direction": direction(world, space_id, other)}
            for pid, other in neighbors(world, space_id)
        ],
    }


def world_index(world: World) -> dict:
    """The compact, LLM-consumable map of the whole world — what the NL
    editor reads instead of the full geometry."""
    return {
        "spaces": [space_summary(world, sid) for sid in sorted(world.nodes)],
        "portal_count": len(world.portals),
    }
