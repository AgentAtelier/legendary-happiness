"""foundry.blender.kitbash — composite prop assembly from sub-parts.

WS-3.3: procedural-breadth kitbash system.  Combines procedural sub-parts into
composite props (e.g. table with ornate legs, chest with handles, candelabra).

Architecture:
  1. A global *KitbashLibrary* registry stores named sub-part builder functions.
  2. ``compose(spec)`` reads a kitbash spec, calls sub-part builders, and merges
     the results into a single mesh.
  3. Integration point: ``build_geometry(spec)`` in build_asset.py can dispatch
     to ``compose`` when the generator is ``"kitbash"``.

Usage (inside Blender):
    from kitbash import kitbash_library, compose
    kitbash_library.register("leg_turned", _build_turned_leg)
    mesh = compose({
        "parts": [
            {"part": "table_top", "pos": (0, 0.75, 0)},
            {"part": "leg_turned", "pos": (-0.4, 0.35, 0.4)},
        ],
        "merge": True,
    })
"""

import hashlib as _hashlib

try:
    import bmesh as _bmesh
    import bpy
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


class KitbashLibrary:
    """Registry of named sub-part builders for kitbash composition.

    Sub-parts are builder functions that accept ``(params, seed)`` and return
    a ``(mesh, offset_y)`` tuple, where *offset_y* is the Y-coordinate of the
    part's top surface (for stacking).
    """

    def __init__(self):
        self._parts: dict[str, callable] = {}

    def register(self, name: str, builder):
        """Register a sub-part builder.

        Args:
            name: unique part name (e.g. "leg_turned", "top_round").
            builder: callable(params, seed) -> (bpy.types.Mesh, float).
        """
        self._parts[name] = builder

    def get(self, name: str):
        """Return the builder for *name*, or raise KeyError."""
        if name not in self._parts:
            raise KeyError(f"Kitbash part {name!r} not registered")
        return self._parts[name]

    def list_parts(self) -> list[str]:
        """Return sorted list of registered part names."""
        return sorted(self._parts.keys())


# Global singleton
kitbash_library = KitbashLibrary()


# ── built-in sub-parts ─────────────────────────────────────


def _builtin_turned_leg(params, seed):
    """A turned-wood leg: stacked cylinders."""
    w = params.get("width", 0.08)
    h = params.get("height", 0.6)
    mesh = bpy.data.meshes.new("kb_leg")
    obj = bpy.data.objects.new("kb_leg", mesh)
    bpy.context.collection.objects.link(obj)
    bm = _bmesh.new()
    # Base foot
    _add_cylinder(bm, 0.0, 0.0, h * 0.03, w * 0.9, h * 0.06, segments=10)
    # Tapered shaft
    _add_cylinder(bm, 0.0, 0.0, h * 0.06 + h * 0.35, w * 0.35, h * 0.7, segments=10)
    # Top ring
    _add_cylinder(bm, 0.0, 0.0, h * 0.06 + h * 0.7 + h * 0.06, w * 0.7, h * 0.12, segments=10)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, h


def _builtin_round_top(params, seed):
    """A round table-top or seat."""
    r = params.get("radius", 0.5)
    t = params.get("thickness", 0.05)
    mesh = bpy.data.meshes.new("kb_top")
    obj = bpy.data.objects.new("kb_top", mesh)
    bpy.context.collection.objects.link(obj)
    bm = _bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, t / 2.0, r, t, segments=24)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, t


def _builtin_square_top(params, seed):
    """A square table-top."""
    w = params.get("width", 0.8)
    d = params.get("depth", 0.8)
    t = params.get("thickness", 0.05)
    mesh = bpy.data.meshes.new("kb_sq_top")
    obj = bpy.data.objects.new("kb_sq_top", mesh)
    bpy.context.collection.objects.link(obj)
    bm = _bmesh.new()
    _add_box(bm, 0.0, 0.0, t / 2.0, w, d, t)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, t


def _builtin_handle_loop(params, seed):
    """A loop handle (for chests, drawers)."""
    r = params.get("radius", 0.06)
    mesh = bpy.data.meshes.new("kb_handle")
    obj = bpy.data.objects.new("kb_handle", mesh)
    bpy.context.collection.objects.link(obj)
    bm = _bmesh.new()
    # Simple torus approximation: two concentric rings
    _add_cylinder(bm, 0.0, 0.0, 0.0, r, r * 0.15, segments=8)
    bm.to_mesh(mesh)
    bm.free()
    return mesh, r * 0.3


def _builtin_cross_brace(params, seed):
    """An X-shaped cross-brace (for table/chairs)."""
    w = params.get("width", 0.6)
    d = params.get("depth", 0.6)
    t = params.get("thickness", 0.03)
    h = params.get("height", 0.35)
    mesh = bpy.data.meshes.new("kb_brace")
    obj = bpy.data.objects.new("kb_brace", mesh)
    bpy.context.collection.objects.link(obj)
    bm = _bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, t, d * 0.9, h)  # one diagonal
    _add_box(bm, 0.0, 0.0, h / 2.0, w * 0.9, t, h)  # cross piece
    bm.to_mesh(mesh)
    bm.free()
    return mesh, h


# Register built-in parts
if _HAS_BPY:
    kitbash_library.register("leg_turned", _builtin_turned_leg)
    kitbash_library.register("top_round", _builtin_round_top)
    kitbash_library.register("top_square", _builtin_square_top)
    kitbash_library.register("handle_loop", _builtin_handle_loop)
    kitbash_library.register("cross_brace", _builtin_cross_brace)


# ── helper geometry ────────────────────────────────────────

def _add_box(bm, cx, cy, cz, sx, sy, sz):
    """Add a unit cube scaled and translated."""
    ret = _bmesh.ops.create_cube(bm, size=1.0)
    scale_mat = ((sx, 0.0, 0.0, 0.0),
                  (0.0, sy, 0.0, 0.0),
                  (0.0, 0.0, sz, 0.0),
                  (cx,  cy,  cz,  1.0))
    _bmesh.ops.transform(bm, verts=ret["verts"], matrix=scale_mat)


def _add_cylinder(bm, cx, cy, cz, radius, height, segments=16):
    """Add a cylinder centred at (cx, cy, cz)."""
    ret = _bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                                  segments=segments, radius1=radius,
                                  radius2=radius, depth=height)
    # create_cone puts base at z=0, top at z=height. Shift to centre.
    offset = cz - height / 2.0
    for v in ret["verts"]:
        v.co.x += cx
        v.co.y += cy
        v.co.z += offset


# ── composition ────────────────────────────────────────────

def compose(spec: dict, seed: int = 0) -> "bpy.types.Mesh":
    """Assemble a composite prop from a kitbash spec.

    *spec* structure::

        {
            "parts": [
                {"part": "leg_turned",   "params": {...}, "pos": ( x,  y,  z)},
                {"part": "top_round",    "params": {...}, "pos": ( x,  y,  z)},
            ],
            "merge": True,   # whether to merge vertices after assembly
        }

    Each part's builder is called with ``(params, seed)`` to produce a mesh.
    That mesh is then transformed to *pos* and joined into the composite.

    Args:
        spec: kitbash spec dict.
        seed: deterministic seed.

    Returns:
        A single merged mesh, or raises ValueError on unknown parts.
    """
    if not _HAS_BPY:
        raise RuntimeError("kitbash.compose requires Blender (bpy)")

    parts_spec = spec.get("parts", [])
    if not parts_spec:
        raise ValueError("kitbash spec must contain at least one part")

    do_merge = spec.get("merge", True)

    # Build each sub-part
    sub_objects = []
    for i, ps in enumerate(parts_spec):
        part_name = ps["part"]
        params = ps.get("params", {})
        pos = ps.get("pos", (0.0, 0.0, 0.0))
        builder = kitbash_library.get(part_name)
        sub_seed = int(_hashlib.md5(f"{seed}_{i}_{part_name}".encode()).hexdigest(), 16) % (2**31)
        sub_mesh, _ = builder(params, sub_seed)
        # Move the sub-object to its position
        sub_obj = bpy.data.objects.get(sub_mesh.name)
        if sub_obj:
            sub_obj.location = pos
            sub_objects.append(sub_obj)

    if not sub_objects:
        raise RuntimeError("No sub-parts were built")

    # Join all sub-objects into one
    bpy.context.view_layer.objects.active = sub_objects[0]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in sub_objects:
        obj.select_set(True)
    bpy.ops.object.join()
    result_obj = bpy.context.view_layer.objects.active
    result_mesh = result_obj.data

    # Optionally merge by distance
    if do_merge:
        bm = _bmesh.new()
        bm.from_mesh(result_mesh)
        _bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        bm.to_mesh(result_mesh)
        bm.free()

    return result_mesh
