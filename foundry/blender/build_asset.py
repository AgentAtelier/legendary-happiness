"""Run INSIDE Blender:
    blender --background --python build_asset.py -- <spec_json> <out_glb>

Slice 1 builds the table from bmesh box primitives (manifold by construction).
Geometry-Nodes node-tree authoring is Slice 2; the spine is identical. Blender is
Z-up; the glTF exporter writes Y-up, so the GLB has height on Y, footprint on X/Z.

Deviation note: Blender 5.x glTF exporter emits per-face vertices (non-shared)
causing trimesh.is_watertight to return False even for a simple cube. The gate
calls mesh.merge_vertices() after loading to fix this — each box becomes a proper
watertight component, and the combined multi-body mesh passes is_watertight."""

import json
import sys

import bmesh
import bpy


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _add_box(bm, cx, cy, cz, sx, sy, sz):
    res = bmesh.ops.create_cube(bm, size=1.0)  # unit cube, -0.5..0.5
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz


def build_table(params):
    tw, td, tt = params["top_width"], params["top_depth"], params["top_thickness"]
    lh, lr, li = params["leg_height"], params["leg_radius"], params["leg_inset"]
    leg = lr * 2.0

    mesh = bpy.data.meshes.new("table")
    obj = bpy.data.objects.new("table", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, lh + tt / 2.0, tw, td, tt)  # top spans lh..lh+tt
    hx = tw / 2.0 - li - leg / 2.0
    hy = td / 2.0 - li - leg / 2.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box(bm, sx * hx, sy * hy, lh / 2.0, leg, leg, lh)  # legs 0..lh
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def apply_material(mesh, material_name):
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.40, 0.26, 0.15, 1.0)
    mesh.materials.append(mat)


def main():
    args = _argv()
    spec_path, out_glb = args[0], args[1]
    spec = json.load(open(spec_path, "r", encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = build_table(spec["params"])
    apply_material(mesh, spec.get("material", "default"))

    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", use_selection=False
    )


main()
