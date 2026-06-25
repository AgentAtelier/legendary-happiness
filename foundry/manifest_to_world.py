"""manifest → world bridge — sub-project (a), unit 5.

Turns a placed-entity manifest (from the existing single-room pipeline)
into the seed of a growable World, so a single-prompt scene becomes the
start of a world that can later gain adjacent/stacked spaces via portals.

This is the INVERSE of ``world.assembly.space_to_compile_inputs``:
round-tripping a SpaceNode through both should preserve entity ids, types,
and positions.  Because ``space_to_compile_inputs`` centres x/z on the
footprint centre, this bridge does the same in the reverse direction.

Public API
----------

* ``manifest_to_ops(manifest, room_size, theme, *, space_id, origin)``
  → list[dict] — produce the sequence of world ops (add_space + add_entity
  per manifest item).

* ``manifest_to_world(manifest, room_size, theme, *, space_id, origin)``
  → World — fold the ops via ``apply_op_checked`` (gate-valid).
"""

from __future__ import annotations

from world.model import World
from world.validation import apply_op_checked


def manifest_to_ops(
    manifest: list[dict],
    room_size: dict,
    theme: str,
    *,
    space_id: str = "root",
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[dict]:
    """Convert a placed-entity manifest + room_size + theme into a list of
    world ops (add_space + one add_entity per manifest item).

    Args:
        manifest: List of placed-entity dicts with keys ``id``, ``category``,
                  ``material``, ``x``, ``y``, ``z``.
        room_size: ``{"w": ..., "d": ..., "h": ...}``.
        theme: Brief theme string (``"dungeon"``, ``"hall"``, etc.).
        space_id: Id for the generated space (default ``"root"``).
        origin: World-space origin of the space footprint (default (0,0,0)).

    Returns:
        ``list[dict]`` — one ``add_space`` + one ``add_entity`` per
        manifest entry, suitable for folding via
        ``world.validation.apply_op_checked``.
    """
    ops: list[dict] = []

    w = float(room_size["w"])
    h = float(room_size["h"])
    d = float(room_size["d"])

    # Centre of the footprint — entity positions are offset from the
    # centre (matching the INVERSE of space_to_compile_inputs, which
    # subtracts the centre to produce the manifest).
    cx = origin[0] + w / 2.0
    cz = origin[2] + d / 2.0

    ops.append({
        "op": "add_space",
        "id": space_id,
        "brief": {"theme": theme},
        "footprint": {
            "origin": list(origin),
            "size": [w, h, d],
        },
    })

    for entry in manifest:
        eid = entry["id"]
        category = entry["category"]
        material = entry.get("material", "worn_oak")
        x = float(entry.get("x", 0.0))
        y = float(entry.get("y", 0.0))
        z = float(entry.get("z", 0.0))

        ops.append({
            "op": "add_entity",
            "space": space_id,
            "entity": {
                "id": eid,
                "type": category,
                "pos": [cx + x, y, cz + z],
                "properties": {"material": material},
            },
        })

    return ops


def manifest_to_world(
    manifest: list[dict],
    room_size: dict,
    theme: str,
    *,
    space_id: str = "root",
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> World:
    """Build a gate-valid World from a manifest by folding
    ``manifest_to_ops`` through ``apply_op_checked``.

    Every entity will pass the W3 gate (inside the footprint) when the
    manifest x/z are within [-w/2, w/2] and [-d/2, d/2] respectively.

    Args:
        manifest: List of placed-entity dicts with keys ``id``, ``category``,
                  ``material``, ``x``, ``y``, ``z``.
        room_size: ``{"w": ..., "d": ..., "h": ...}``.
        theme: Brief theme string.
        space_id: Id for the generated space (default ``"root"``).
        origin: World-space origin of the space footprint (default (0,0,0)).

    Returns:
        A new ``World`` whose single space contains every manifest entity,
        and whose op_log records the transformation.
    """
    ops = manifest_to_ops(
        manifest, room_size, theme, space_id=space_id, origin=origin
    )
    world = World()
    for op in ops:
        world = apply_op_checked(world, op)
    return world
