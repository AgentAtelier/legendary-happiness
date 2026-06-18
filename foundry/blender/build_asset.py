"""Run INSIDE Blender:
    blender --background --python build_asset.py -- <spec_json> <out_glb>

Slice 2 builds the table from bmesh box primitives with edge bevels and a
stylized-PBR wood material. Five boxes (tabletop + 4 legs) are created in a
single bmesh, beveled, and exported as one GLB. Blender is Z-up; the glTF
exporter writes Y-up, so the GLB has height on Y, footprint on X/Z.
"""

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


def apply_bevel(mesh_data):
    """Apply a small uniform edge bevel so edges catch light.

    Offset ~0.015 m, 2 segments; bakes into the exported mesh.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    bmesh.ops.bevel(
        bm,
        geom=[e for e in bm.edges],
        offset=0.015,
        offset_type="OFFSET",
        segments=2,
        profile=0.5,
    )
    bm.to_mesh(mesh_data)
    bm.free()


def apply_material(mesh, material_name):
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.45, 0.28, 0.14, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.65
        bsdf.inputs["Metallic"].default_value = 0.0
    mesh.materials.append(mat)


def main():
    args = _argv()
    spec_path, out_glb = args[0], args[1]
    spec = json.load(open(spec_path, "r", encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = build_table(spec["params"])
    apply_bevel(mesh)
    apply_material(mesh, spec.get("material", "default"))

    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", use_selection=False
    )


main()
