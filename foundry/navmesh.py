"""foundry.navmesh — build-time walkable navmesh carving.

carve_walkable() returns the room's walkable floor polygon (inset by the wall
margin) MINUS each prop footprint (inflated by the agent radius), triangulated
for a Godot NavigationMesh. Pure Python + deterministic. First reusable
primitive of the level-design branch.

Phase 2.4: Resource caps — MAX_FOOTPRINTS and MAX_AREA_M2 prevent OOM-class
pathological inputs.
"""
from __future__ import annotations

import numpy as np
from mapbox_earcut import triangulate_float64
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from decisions import DecisionPoint, make_decision

Obstacle = tuple[float, float, float, float]  # (cx, cz, half_x, half_z)

# Phase 2.4: Resource caps
MAX_FOOTPRINTS = 256
MAX_AREA_M2 = 400


def carve_walkable(room_w, room_d, obstacles, agent_radius=0.3, wall_margin=1.2,
                   decisions_out: list[DecisionPoint] | None = None):
    # Phase 2.4: Resource caps — guard against pathological inputs.
    if len(obstacles) > MAX_FOOTPRINTS:
        dp = make_decision(
            "navmesh.too_dense", "build", "assumption",
            context={"reason": f"{len(obstacles)} footprints exceeds max {MAX_FOOTPRINTS}"},
            choices=[],
        )
        if decisions_out is not None:
            decisions_out.append(dp)
        return [], []

    inset_w = room_w / 2.0 - wall_margin
    inset_d = room_d / 2.0 - wall_margin
    if inset_w <= 0 or inset_d <= 0:
        return [], []
    base = box(-inset_w, -inset_d, inset_w, inset_d)

    if base.area > MAX_AREA_M2:
        dp = make_decision(
            "navmesh.too_dense", "build", "assumption",
            context={"reason": f"walkable area {base.area:.1f} m² exceeds max {MAX_AREA_M2}"},
            choices=[],
        )
        if decisions_out is not None:
            decisions_out.append(dp)
        return [], []

    rects = []
    for cx, cz, hx, hz in sorted(obstacles):  # sorted -> order-independent
        rects.append(box(cx - hx - agent_radius, cz - hz - agent_radius,
                         cx + hx + agent_radius, cz + hz + agent_radius))
    walkable = base.difference(unary_union(rects)) if rects else base

    if walkable.is_empty or walkable.area <= 1e-6:
        return [], []

    # Normalize to a list of polygons (difference may yield a MultiPolygon)
    polys_in = list(getattr(walkable, "geoms", [walkable]))

    vertices: list[tuple[float, float, float]] = []
    polygons: list[list[int]] = []
    for poly in polys_in:
        _triangulate_into(poly, vertices, polygons)
    return vertices, polygons


def _triangulate_into(poly: Polygon, vertices, polygons):
    base_idx = len(vertices)
    rings = [list(poly.exterior.coords)[:-1]]          # drop closing dup
    rings += [list(r.coords)[:-1] for r in poly.interiors]

    flat: list[tuple[float, float]] = []
    ring_ends: list[int] = []
    for ring in rings:
        flat.extend(ring)
        ring_ends.append(len(flat))
    verts2d = np.array(flat, dtype=np.float64)
    tris = triangulate_float64(verts2d, np.array(ring_ends, dtype=np.uint32))

    for (x, z) in flat:
        vertices.append((round(float(x), 4), 0.0, round(float(z), 4)))
    for i in range(0, len(tris), 3):
        polygons.append([base_idx + int(tris[i]),
                         base_idx + int(tris[i + 1]),
                         base_idx + int(tris[i + 2])])


def point_in_polygons(px, pz, vertices, polygons) -> bool:
    for tri in polygons:
        ax, _, az = vertices[tri[0]]
        bx, _, bz = vertices[tri[1]]
        cx, _, cz = vertices[tri[2]]
        d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
        if abs(d) < 1e-12:
            continue
        a = ((bz - cz) * (px - cx) + (cx - bx) * (pz - cz)) / d
        b = ((cz - az) * (px - cx) + (ax - cx) * (pz - cz)) / d
        c = 1 - a - b
        if -1e-9 <= a <= 1 + 1e-9 and -1e-9 <= b <= 1 + 1e-9 and -1e-9 <= c <= 1 + 1e-9:
            return True
    return False
