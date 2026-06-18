"""Run INSIDE Blender:
    blender --background --python build_asset.py -- <spec_json> <out_glb>

Slice 3 adds UV unwrapping, a procedural wood material with shader nodes, and
Cycles-CPU baking of the base color to an embedded image texture so the glTF
exporter writes a baseColorTexture. Blender is Z-up; the glTF exporter writes
Y-up, so the GLB has height on Y, footprint on X/Z.
"""

import json
import os
import sys

import bmesh
import bpy

# Allow importing from the foundry package directory (materials.py).
_foundry_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from materials import MATERIAL_PALETTE


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _add_box(bm, cx, cy, cz, sx, sy, sz):
    res = bmesh.ops.create_cube(bm, size=1.0)  # unit cube, -0.5..0.5
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz


def _build_table_geometry(params):
    """Build the table mesh from params. Returns a Blender mesh data block."""
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


def _build_chair_geometry(params):
    """Build the chair mesh from params. Returns a Blender mesh data block.

    Chair layout (Z-up, X=width, Y=depth):
    - Seat box centered above the legs
    - Four legs at the corners from floor to seat bottom
    - Backrest box behind the seat, sitting on top of the seat
    """
    sw, sd, st = params["seat_width"], params["seat_depth"], params["seat_thickness"]
    lh, lr, li = params["leg_height"], params["leg_radius"], params["leg_inset"]
    bh = params["back_height"]
    leg = lr * 2.0
    back_thickness = 0.04  # fixed backrest thickness

    mesh = bpy.data.meshes.new("chair")
    obj = bpy.data.objects.new("chair", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # ── Seat ─────────────────────────────────────────────────────
    _add_box(bm, 0.0, 0.0, lh + st / 2.0, sw, sd, st)

    # ── Four legs ────────────────────────────────────────────────
    hx = sw / 2.0 - li - leg / 2.0
    hy = sd / 2.0 - li - leg / 2.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box(bm, sx * hx, sy * hy, lh / 2.0, leg, leg, lh)

    # ── Backrest ─────────────────────────────────────────────────
    back_y = -(sd / 2.0 - back_thickness / 2.0)
    back_z = lh + st + bh / 2.0
    back_w = sw * 0.8  # slightly narrower than the seat
    _add_box(bm, 0.0, back_y, back_z, back_w, back_thickness, bh)

    bm.to_mesh(mesh)
    bm.free()
    return mesh


_BUILDERS = {
    "table": _build_table_geometry,
    "chair": _build_chair_geometry,
}


def build_geometry(spec):
    """Dispatch to the correct geometry builder based on spec['generator']."""
    gen = spec.get("generator", "table")
    builder = _BUILDERS.get(gen)
    if builder is None:
        raise ValueError(f"unknown generator: {gen!r} (known: {sorted(_BUILDERS)})")
    return builder(spec["params"])


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


def assign_uvs(mesh_data):
    """UV unwrap every face using Blender's smart_project so all faces (top
    AND legs) get sensible texture coordinates.  May introduce UV seams at
    island boundaries, but the gate tolerates those (position-only watertight
    check)."""
    obj = _find_object_for_mesh(mesh_data)
    if obj is None:
        return
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Ensure a UV layer exists.
    if not mesh_data.uv_layers:
        mesh_data.uv_layers.new(name="UVMap")

    # Enter edit mode, select all faces, run smart_project.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


def _find_object_for_mesh(mesh_data):
    """Return the Blender object that owns the given mesh data, or None."""
    for o in bpy.data.objects:
        if o.data == mesh_data:
            return o
    return None


def _lerp(a, b, t):
    """Linear interpolation between two RGB tuples."""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def apply_material(mesh, material_name):
    """Create a procedural wood material with shader nodes, bake the base colour
    to an image texture with Cycles-CPU, then wire the baked texture into the
    Principled BSDF Base Color so the glTF exporter writes a baseColorTexture.

    Material colours and roughness are driven by foundry/materials.py."""
    # Find the object that owns this mesh.
    obj = _find_object_for_mesh(mesh)
    if obj is None:
        raise RuntimeError("Could not find object for the table mesh")

    # ── Look up the material palette entry ────────────────────
    mat_info = MATERIAL_PALETTE.get(material_name, MATERIAL_PALETTE["worn_oak"])
    dark = mat_info["grain_dark_rgb"]
    light = mat_info["grain_light_rgb"]
    roughness = mat_info["roughness"]

    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    mesh.materials.append(mat)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes; we rebuild the shader tree.
    nodes.clear()

    # ── procedural wood nodes ────────────────────────────────
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.location = (400, 200)

    material_output = nodes.new("ShaderNodeOutputMaterial")
    material_output.location = (800, 200)

    # Wave Texture (bands) for wood grain.
    wave = nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 12.0
    wave.inputs["Distortion"].default_value = 1.5
    wave.inputs["Detail"].default_value = 2.0
    wave.inputs["Detail Scale"].default_value = 3.0
    wave.location = (-600, 200)

    # ColorRamp: map wave fac to wood tones from the palette.
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-200, 200)
    ramp.color_ramp.interpolation = "LINEAR"
    # 4-stop ramp: dark → mid → light → dark
    stops = ramp.color_ramp.elements
    stops[0].position = 0.0
    stops[0].color = (*dark, 1.0)
    stops[1].position = 0.4
    stops[1].color = (*_lerp(dark, light, 0.5), 1.0)
    s2 = stops.new(0.7)
    s2.color = (*light, 1.0)
    s3 = stops.new(1.0)
    s3.color = (*dark, 1.0)

    # Wire procedural: wave → ramp → bsdf
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])

    # ── baking: capture the procedural colour into an image ───
    # Create the image to bake into.
    bake_image = bpy.data.images.new(
        "baked_wood", width=1024, height=1024,
        alpha=False, float_buffer=False,
    )
    bake_image.file_format = "PNG"

    # Image Texture node — this must be the active node for baking.
    bake_tex = nodes.new("ShaderNodeTexImage")
    bake_tex.image = bake_image
    bake_tex.location = (200, -200)
    # Select it as the active bake target.
    nodes.active = bake_tex
    bake_tex.select = True

    # Switch to Cycles CPU for baking.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1  # fast bake; quality is fine for a 1K texture

    # Temporarily replace the Principled BSDF with an Emission shader so
    # the EMIT bake captures exactly the procedural colour (no lighting).
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (400, -200)
    links.new(ramp.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], material_output.inputs["Surface"])

    # Bake.
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="EMIT")

    # Restore the Principled BSDF and wire the baked texture.
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])
    links.new(bake_tex.outputs["Color"], bsdf.inputs["Base Color"])

    # Remove the emission node (no longer needed).
    nodes.remove(emit)

    # Pack the image so the glTF exporter embeds it in the GLB.
    bake_image.pack()


def main():
    args = _argv()
    spec_path, out_glb = args[0], args[1]
    spec = json.load(open(spec_path, "r", encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = build_geometry(spec)
    apply_bevel(mesh)
    assign_uvs(mesh)
    apply_material(mesh, spec.get("material", "default"))

    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", use_selection=False
    )


main()
