"""World → scene_compiler adapter — sub-project (a), unit 3 (core).

Unit 3 assembles a World-DAG into Godot scenes. Rather than emit ``.tscn``
afresh (risky and unverifiable without a live Godot), it REUSES the
existing, Godot-verified ``scene_compiler.compile_scene`` per space: each
``SpaceNode`` is translated into compile_scene's inputs, so the proven
indoor-room emission does the work and only the multi-space composition is
new.

Coordinate convention — grounded in ``scene_compiler`` (not guessed): props
are placed at their manifest ``x``/``z`` directly as Godot transforms in a
room centred on the origin (``room_size`` uses keys ``w``/``d``/``h``). A
``SpaceNode``'s entities carry WORLD positions, so the adapter converts
world → room-local-centred: ``local = world − footprint_centre``.

This module is the pure-Python core (fully unit-testable). The actual Godot
LOAD of an assembled scene is verified by the orchestrator when the stack is
stable (it needs real Godot); that is the only un-covered step.
"""

from __future__ import annotations

from typing import Any

from world.model import SpaceNode


def footprint_centre(footprint: dict) -> tuple[float, float, float]:
    """World-space centre of a footprint AABB ``{origin, size}``."""
    o, s = footprint["origin"], footprint["size"]
    return (o[0] + s[0] / 2.0, o[1] + s[1] / 2.0, o[2] + s[2] / 2.0)


def space_to_compile_inputs(node: SpaceNode) -> dict[str, Any]:
    """Translate one ``SpaceNode`` into kwargs for
    ``scene_compiler.compile_scene``.

    Returns ``{quest_specs, manifest, room_size, theme}``. Entity WORLD
    positions are converted to room-local-centred coords. Material falls
    back to the brief's ``default_material`` then ``"worn_oak"``.
    """
    fp = node.footprint
    cx, _cy, cz = footprint_centre(fp)
    size = fp["size"]
    room_size = {"w": float(size[0]), "d": float(size[2]), "h": float(size[1])}
    default_mat = node.brief.get("default_material", "worn_oak")
    manifest = [
        {
            "id": e.id,
            "category": e.type,
            "material": e.properties.get("material", default_mat),
            "x": float(e.pos[0]) - cx,
            "y": float(e.pos[1]),
            "z": float(e.pos[2]) - cz,
        }
        for e in node.entities
    ]
    return {
        "quest_specs": [],
        "manifest": manifest,
        "room_size": room_size,
        "theme": node.brief.get("theme"),
    }
