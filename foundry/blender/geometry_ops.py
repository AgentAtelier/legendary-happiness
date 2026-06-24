"""foundry.blender.geometry_ops — composable geometry operations for richer silhouettes.

WS-3.3: procedural-breadth second-gen geometry.  Each op accepts a Blender mesh
and returns the modified mesh, making them chainable.  All ops are deterministic
given a seed.

Operations:
  bevel           — edge bevel (light-catch, silhouette softening)
  solidify        — add thickness to thin geometry
  array           — repeat geometry along an axis
  greeble         — add small surface protrusions for detail
  parametric_var  — seeded scale/twist deformation

Usage (inside Blender):
    from geometry_ops import bevel, solidify, greeble
    mesh = build_geometry(spec)
    mesh = bevel(mesh, width=0.01)
    mesh = solidify(mesh, thickness=0.02)
    mesh = greeble(mesh, density=0.2, seed=42)
"""

import math as _math
import random as _random

try:
    import bmesh as _bmesh
    import bpy
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


# ── helpers ────────────────────────────────────────────────

def _mesh_bounds(mesh_data):
    """Return (min_x, max_x, min_y, max_y, min_z, max_z) for a mesh."""
    verts = mesh_data.vertices
    if not verts:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _smallest_extent(mesh_data):
    """Smallest axis-aligned dimension of the mesh."""
    mnx, mxx, mny, mxy, mnz, mxz = _mesh_bounds(mesh_data)
    return min(mxx - mnx, mxy - mny, mxz - mnz)


def _rng(seed):
    """Deterministic RNG from a seed value."""
    return _random.Random(f"geometry_ops_{seed}")


# ── operations ─────────────────────────────────────────────

def bevel(mesh_data, width=0.015, segments=2, seed=0):
    """Apply a uniform edge bevel.

    The *width* is clamped to 40% of the smallest mesh extent to prevent
    collapsing thin geometry (same safety as ``apply_bevel`` in build_asset).

    Args:
        mesh_data: Blender mesh to modify in-place.
        width: bevel offset in metres (default 0.015).
        segments: number of bevel segments (default 2).
        seed: deterministic seed (unused for bevel; present for consistency).

    Returns:
        The modified *mesh_data* for chaining.
    """
    if not _HAS_BPY:
        return mesh_data
    smallest = _smallest_extent(mesh_data)
    offset = min(width, smallest * 0.4) if smallest > 0.0 else width
    bm = _bmesh.new()
    bm.from_mesh(mesh_data)
    _bmesh.ops.bevel(bm, geom=bm.edges[:], offset=offset,
                     offset_type="OFFSET", segments=segments)
    bm.to_mesh(mesh_data)
    bm.free()
    return mesh_data


def solidify(mesh_data, thickness=0.02, seed=0):
    """Add thickness to a mesh via the Solidify modifier.

    Args:
        mesh_data: Blender mesh to modify in-place.
        thickness: wall thickness in metres (default 0.02). Can be negative
                   to thicken inward.
        seed: deterministic seed (reserved for future noise-based variation).

    Returns:
        The modified *mesh_data* for chaining.
    """
    if not _HAS_BPY:
        return mesh_data
    # Use bpy.context to get the active object
    obj = _find_object_for_mesh(mesh_data)
    if obj is None:
        return mesh_data
    mod = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    mod.thickness = thickness
    mod.offset = 0.0  # centred
    if _HAS_BPY:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return mesh_data


def array(mesh_data, count=3, offset=(1.0, 0.0, 0.0), seed=0):
    """Repeat geometry along a vector via the Array modifier.

    Args:
        mesh_data: Blender mesh to modify in-place.
        count: number of copies (default 3).
        offset: (x, y, z) offset between copies.
        seed: deterministic seed (reserved for future jitter).

    Returns:
        The modified *mesh_data* for chaining.
    """
    if not _HAS_BPY:
        return mesh_data
    obj = _find_object_for_mesh(mesh_data)
    if obj is None:
        return mesh_data
    mod = obj.modifiers.new(name="Array", type="ARRAY")
    mod.count = max(1, count)
    mod.relative_offset_displace = offset
    if _HAS_BPY:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return mesh_data


def greeble(mesh_data, density=0.2, scale=0.03, seed=0):
    """Add small surface protrusions (greebles) to a mesh.

    Picks random faces (seeded) and extrudes them slightly outward.
    Gives flat surfaces a manufactured/sci-fi/rich look.

    Args:
        mesh_data: Blender mesh to modify in-place.
        density: fraction of faces to greeble (0.0–1.0, default 0.2).
        scale: extrusion distance in metres (default 0.03).
        seed: deterministic seed.

    Returns:
        The modified *mesh_data* for chaining.
    """
    if not _HAS_BPY:
        return mesh_data
    rng = _rng(seed)
    bm = _bmesh.new()
    bm.from_mesh(mesh_data)
    bm.faces.ensure_lookup_table()
    faces = list(bm.faces)
    if not faces:
        bm.to_mesh(mesh_data)
        bm.free()
        return mesh_data
    # Pick a random subset
    k = max(1, int(len(faces) * density))
    selected = rng.sample(faces, min(k, len(faces)))
    # Extrude individual faces
    for face in selected:
        normal = face.normal.copy()
        ret = _bmesh.ops.extrude_face_region(bm, geom=[face])
        extruded_verts = [g for g in ret["geom"] if isinstance(g, _bmesh.types.BMVert)]
        for v in extruded_verts:
            v.co += normal * scale
    bm.to_mesh(mesh_data)
    bm.free()
    return mesh_data


def parametric_variation(mesh_data, scale_range=(0.9, 1.1), twist=0.0, seed=0):
    """Apply seeded scale and twist deformation.

    Randomly scales each axis independently within *scale_range*, and applies
    a Z-axis twist rotation (useful for barrel/candle organic variation).

    Args:
        mesh_data: Blender mesh to modify in-place.
        scale_range: (min, max) per-axis scale factor.
        twist: max twist angle in radians around Z axis.
        seed: deterministic seed.

    Returns:
        The modified *mesh_data* for chaining.
    """
    if not _HAS_BPY:
        return mesh_data
    rng = _rng(seed)
    sx = rng.uniform(*scale_range)
    sy = rng.uniform(*scale_range)
    sz = rng.uniform(*scale_range)
    tw = twist * rng.uniform(-1.0, 1.0)
    bm = _bmesh.new()
    bm.from_mesh(mesh_data)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        # Scale
        v.co.x *= sx
        v.co.y *= sy
        v.co.z *= sz
        # Twist around Z
        if tw != 0.0:
            angle = tw * (v.co.z / max(1.0, max(abs(v.co.z), 0.01)))
            # Simple twist: rotate X,Y around Z
            cos_a = _math.cos(angle)
            sin_a = _math.sin(angle)
            x = v.co.x * cos_a - v.co.y * sin_a
            y = v.co.x * sin_a + v.co.y * cos_a
            v.co.x = x
            v.co.y = y
    bm.to_mesh(mesh_data)
    bm.free()
    return mesh_data


def _find_object_for_mesh(mesh_data):
    """Find the Blender object that owns *mesh_data*."""
    if not _HAS_BPY:
        return None
    for obj in bpy.data.objects:
        if obj.data == mesh_data:
            return obj
    return None


# ── composable pipeline ────────────────────────────────────

def apply_ops(mesh_data, ops_spec, seed=0):
    """Apply a list of operations from a spec.

    *ops_spec* is a list of dicts, each with an ``"op"`` key and kwargs.
    Example::

        apply_ops(mesh, [
            {"op": "bevel", "width": 0.01},
            {"op": "solidify", "thickness": 0.015},
            {"op": "greeble", "density": 0.15, "seed": 42},
        ], seed=1)

    Args:
        mesh_data: Blender mesh to modify in-place.
        ops_spec: list of operation dicts.
        seed: base seed for all operations.

    Returns:
        The modified *mesh_data* for chaining.
    """
    _ops = {
        "bevel": bevel,
        "solidify": solidify,
        "array": array,
        "greeble": greeble,
        "parametric_variation": parametric_variation,
    }
    rng = _rng(seed)
    for i, spec in enumerate(ops_spec):
        spec = dict(spec)  # shallow copy to avoid mutating caller's dict
        op_name = spec.pop("op", None)
        if op_name not in _ops:
            raise ValueError(f"Unknown geometry op {op_name!r}")
        fn = _ops[op_name]
        # Derive sub-seed deterministically from the base seed and index
        sub_seed = spec.pop("seed", rng.randint(0, 2**31))
        mesh_data = fn(mesh_data, seed=sub_seed, **spec)
    return mesh_data
