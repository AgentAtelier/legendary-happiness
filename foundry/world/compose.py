"""Multi-space composition — sub-project (a), unit 3 end-to-end.

Turns a whole ``World`` into a walkable Godot scene by reusing the proven
per-space ``scene_compiler`` path and instancing each space at its footprint
origin (see the design spec
``docs/superpowers/specs/2026-06-25-world-unit3-multispace-assembly.md``).

This module starts with the de-risking kernel: **portal → wall-opening
geometry** — for each portal touching a space, which FACE of that space's
shell it opens, and the opening rect. The shell generator consumes this to
leave a walkable gap (v1), so adjacent spaces actually connect. Pure geometry,
fully unit-testable; the Blender shell-cut + Godot load are verified with the
stack.

Face convention matches ``world.query`` (Godot-aligned): the face whose outward
normal points +X is "east", -X "west", -Z "north", +Z "south", +Y "up"
(ceiling), -Y "down" (floor).
"""

from __future__ import annotations

import tscn_writer as tw
from world.assembly import footprint_centre
from world.model import World
from world.query import neighbors
from world.validation import EPS, aabb

_IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)

# axis index -> (face at the MAX side, face at the MIN side)
_AXIS_FACES = {0: ("east", "west"), 1: ("up", "down"), 2: ("south", "north")}


def _shared_face(s, n, eps: float = EPS) -> str | None:
    """The face of AABB ``s`` that touches AABB ``n``. ``None`` if they don't
    share exactly one face (not face-adjacent)."""
    (slo, shi), (nlo, nhi) = s, n
    hits = []
    for axis in range(3):
        max_face, min_face = _AXIS_FACES[axis]
        if abs(shi[axis] - nlo[axis]) <= eps:   # s's MAX face meets n
            hits.append(max_face)
        elif abs(slo[axis] - nhi[axis]) <= eps:  # s's MIN face meets n
            hits.append(min_face)
    return hits[0] if len(hits) == 1 else None


def space_openings(world: World, space_id: str) -> list[dict]:
    """For every portal touching ``space_id``, the opening to cut in that
    space's shell: ``{portal, to, face, center, size}`` (deterministic order,
    by portal id). ``center`` is the portal's world position; ``size`` its
    ``(w, h)``. Spaces with malformed footprints / non-adjacent neighbours are
    skipped (the validation gate already rejects those on add_portal)."""
    node = world.nodes.get(space_id)
    if node is None:
        return []
    s = aabb(node.footprint)
    if s is None:
        return []
    out = []
    for pid, other in neighbors(world, space_id):
        on = world.nodes.get(other)
        nb = aabb(on.footprint) if on is not None else None
        if nb is None:
            continue
        face = _shared_face(s, nb)
        if face is None:
            continue
        portal = world.portals[pid]
        out.append({
            "portal": pid,
            "to": other,
            "face": face,
            "center": list(portal.position),
            "size": list(portal.size),
        })
    return out


def build_world_tscn(
    world: World, scene_paths: dict[str, str], *, spawn_space: str | None = None
) -> str:
    """The parent ``world.tscn``: instance each space's PackedScene at its
    footprint CENTRE (the per-space scene is centred on its own origin, so
    translating by the centre lands it correctly in world space) + a
    ``PlayerSpawn`` marker at the spawn space's centre.

    ``scene_paths`` maps ``space_id -> "res://…"`` for the per-space scenes
    (produced by the stack-gated compile step). This kernel is PURE and
    deterministic — given the same world + paths it returns byte-identical
    text — so it is fully testable without Godot. Spaces sorted by id.
    """
    spaces = [sid for sid in sorted(world.nodes) if sid in scene_paths]
    if not spaces:
        raise ValueError("build_world_tscn: no spaces with scene paths")
    spawn = spawn_space if spawn_space in spaces else spaces[0]

    lines = [f"[gd_scene load_steps={len(spaces) + 1} format=3]", ""]
    ext_ids = {sid: f"{i}_{sid}" for i, sid in enumerate(spaces, start=1)}
    for sid in spaces:
        lines.append(tw.ext_resource("PackedScene", scene_paths[sid], ext_ids[sid]))
    lines += ["", '[node name="World" type="Node3D"]', ""]
    for sid in spaces:
        lines.append(tw.node_header(sid, parent=".", instance=ext_ids[sid]))
        lines.append(f"transform = {tw.transform3d(_IDENTITY, footprint_centre(world.nodes[sid].footprint))}")
        lines.append("")
    lines.append(tw.node_header("PlayerSpawn", type="Marker3D", parent="."))
    lines.append(f"transform = {tw.transform3d(_IDENTITY, footprint_centre(world.nodes[spawn].footprint))}")
    lines.append("")
    return "\n".join(lines)
