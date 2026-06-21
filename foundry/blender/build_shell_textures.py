"""Run INSIDE Blender:
    blender --background --python build_shell_textures.py -- <out_dir>

E1 Room Shell: Bakes tiling PBR textures (albedo, normal, ORM) for
floor (stone), wall (stone-light), and ceiling (stone-lighter).

The textures are small (512×512) because they tile.  Each gets a
smart-UV unwrap on a unit plane so UVs fill [0,1] — Godot can then
set uv1_scale for tiling at the desired repetition.
"""

import hashlib
import math
import os
import struct
import sys

import bmesh
import bpy


_foundry_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from materials import MATERIAL_PALETTE


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _add_plane(bm, size=2.0):
    """Add a flat plane (Z-up) centred at origin."""
    res = bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    return res


# ── Material node graphs (reuse the same builders) ──────────────

def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _stone_color_nodes(nodes, links, mat_info, seed):
    base = mat_info["base_rgb"]
    mottle = mat_info["mottle_rgb"]
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1000, 300)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-800, 300)
    mapping.vector_type = "TEXTURE"
    mapping.inputs["Scale"].default_value = (2.0, 2.0, 2.0)
    mapping.inputs["Location"].default_value = (seed, seed, 0.0)
    voronoi = nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-600, 300)
    voronoi.inputs["Scale"].default_value = 8.0
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-600, 0)
    noise.inputs["Scale"].default_value = 12.0
    noise.inputs["Detail"].default_value = 4.0
    noise.inputs["Roughness"].default_value = 0.6
    mix_textures = nodes.new("ShaderNodeMixRGB")
    mix_textures.blend_type = "MIX"
    mix_textures.location = (-300, 300)
    mix_textures.inputs["Fac"].default_value = 0.5
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(voronoi.outputs["Color"], mix_textures.inputs["Color1"])
    links.new(noise.outputs["Color"], mix_textures.inputs["Color2"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (200, 300)
    ramp.color_ramp.interpolation = "LINEAR"
    stops = ramp.color_ramp.elements
    stops[0].position = 0.0
    stops[0].color = (*base, 1.0)
    stops[1].position = 0.5
    stops[1].color = (*mottle, 1.0)
    s2 = stops.new(1.0)
    s2.color = (*base, 1.0)
    links.new(mix_textures.outputs["Color"], ramp.inputs["Fac"])
    return ramp.outputs["Color"], voronoi.outputs["Distance"]


def _build_stone_material(mesh, mat_name, mat_info, seed=0.0):
    """Build a stone material node graph on *mesh*, bake full PBR set,
    and save textures to disk."""
    obj = None
    for o in bpy.data.objects:
        if o.data == mesh:
            obj = o
            break
    if obj is None:
        raise RuntimeError("Could not find object for mesh")

    roughness = mat_info.get("roughness", 0.85)
    metallic = float(mat_info.get("metallic", 0.0))

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    mesh.materials.append(mat)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.location = (800, 300)

    material_output = nodes.new("ShaderNodeOutputMaterial")
    material_output.location = (1200, 300)

    color_socket, height_socket = _stone_color_nodes(nodes, links, mat_info, seed)

    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.location = (200, 100)
    ao.inputs["Distance"].default_value = 0.2

    mix_ao = nodes.new("ShaderNodeMixRGB")
    mix_ao.blend_type = "MULTIPLY"
    mix_ao.location = (500, 300)
    mix_ao.inputs["Fac"].default_value = 1.0

    links.new(color_socket, mix_ao.inputs["Color1"])
    links.new(ao.outputs["Color"], mix_ao.inputs["Color2"])
    links.new(mix_ao.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1

    # ── NORMAL bake ────────────────────────────────────────
    bump = nodes.new("ShaderNodeBump")
    bump.location = (1000, -100)
    bump.inputs["Strength"].default_value = 0.2
    bump.inputs["Distance"].default_value = 0.05
    links.new(height_socket, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    normal_img = bpy.data.images.new("shell_normal", width=512, height=512,
                                      alpha=False, float_buffer=False)
    normal_img.colorspace_settings.name = "Non-Color"
    normal_tex = nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal_img
    normal_tex.location = (1000, -300)
    for n in nodes:
        n.select = False
    nodes.active = normal_tex
    normal_tex.select = True
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT",
                        use_clear=True, margin=16)

    for link in list(bump.inputs["Height"].links):
        links.remove(link)
    for link in list(bump.outputs["Normal"].links):
        links.remove(link)
    nodes.remove(bump)
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.location = (1000, -300)
    links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    # ── AO bake ────────────────────────────────────────────
    ao_img = bpy.data.images.new("shell_ao", width=512, height=512,
                                  alpha=False, float_buffer=False)
    ao_img.colorspace_settings.name = "Non-Color"
    ao_tex = nodes.new("ShaderNodeTexImage")
    ao_tex.image = ao_img
    ao_tex.location = (200, -700)
    for n in nodes:
        n.select = False
    nodes.active = ao_tex
    ao_tex.select = True
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)
    emit_ao = nodes.new("ShaderNodeEmission")
    emit_ao.location = (400, -700)
    links.new(ao.outputs["Color"], emit_ao.inputs["Color"])
    links.new(emit_ao.outputs["Emission"], material_output.inputs["Surface"])
    bpy.ops.object.bake(type="EMIT", use_clear=True, margin=16)

    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)
    for link in list(emit_ao.inputs["Color"].links):
        links.remove(link)
    nodes.remove(emit_ao)
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])
    for n in nodes:
        n.select = False
    nodes.active = None

    # ── EMIT bake (albedo) ─────────────────────────────────
    albedo_img = bpy.data.images.new("shell_albedo", width=512, height=512,
                                      alpha=False, float_buffer=False)
    albedo_tex_node = nodes.new("ShaderNodeTexImage")
    albedo_tex_node.image = albedo_img
    albedo_tex_node.location = (800, -500)
    for n in nodes:
        n.select = False
    nodes.active = albedo_tex_node
    albedo_tex_node.select = True
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)
    emit_albedo = nodes.new("ShaderNodeEmission")
    emit_albedo.location = (1000, -500)
    links.new(mix_ao.outputs["Color"], emit_albedo.inputs["Color"])
    links.new(emit_albedo.outputs["Emission"], material_output.inputs["Surface"])
    bpy.ops.object.bake(type="EMIT", margin=16)

    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])
    for link in list(emit_albedo.inputs["Color"].links):
        links.remove(link)
    nodes.remove(emit_albedo)
    for n in nodes:
        n.select = False
    nodes.active = None

    # ── ORM pack: R=AO, G=roughness, B=metallic, A=1 ───────
    orm_img = bpy.data.images.new("shell_orm", width=512, height=512,
                                   alpha=False, float_buffer=False)
    orm_img.colorspace_settings.name = "Non-Color"
    orm_pixels = [0.0] * (512 * 512 * 4)
    ao_pixels = list(ao_img.pixels[:])
    px_count = 512 * 512
    for i in range(px_count):
        orm_pixels[4 * i + 0] = ao_pixels[4 * i]       # R = AO
        orm_pixels[4 * i + 1] = roughness               # G = roughness
        orm_pixels[4 * i + 2] = metallic                 # B = metallic
        orm_pixels[4 * i + 3] = 1.0                     # A = 1
    orm_img.pixels[:] = orm_pixels

    return albedo_img, normal_img, orm_img


def main():
    args = _argv()
    out_dir = args[0]
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ── Floor: rough_granite (stone) ──────────────────
    floor_mesh = bpy.data.meshes.new("floor_plane")
    floor_obj = bpy.data.objects.new("floor_plane", floor_mesh)
    bpy.context.collection.objects.link(floor_obj)
    bm_f = bmesh.new()
    _add_plane(bm_f, size=2.0)
    bm_f.to_mesh(floor_mesh)
    bm_f.free()
    bpy.context.view_layer.objects.active = floor_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

    albedo, normal, orm = _build_stone_material(
        floor_mesh, "floor_mat", MATERIAL_PALETTE["rough_granite"], seed=0.0
    )
    _save_textures(albedo, normal, orm, out_dir, "floor")

    # ── Wall: lighter stone ───────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    wall_mesh = bpy.data.meshes.new("wall_plane")
    wall_obj = bpy.data.objects.new("wall_plane", wall_mesh)
    bpy.context.collection.objects.link(wall_obj)
    bm_w = bmesh.new()
    _add_plane(bm_w, size=2.0)
    bm_w.to_mesh(wall_mesh)
    bm_w.free()
    bpy.context.view_layer.objects.active = wall_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

    wall_info = dict(MATERIAL_PALETTE["rough_granite"])
    wall_info["base_rgb"] = tuple(min(1.0, c * 1.25) for c in wall_info["base_rgb"])
    wall_info["mottle_rgb"] = tuple(min(1.0, c * 1.2) for c in wall_info["mottle_rgb"])
    albedo, normal, orm = _build_stone_material(
        wall_mesh, "wall_mat", wall_info, seed=1.0
    )
    _save_textures(albedo, normal, orm, out_dir, "wall")

    # ── Ceiling: even lighter ─────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ceil_mesh = bpy.data.meshes.new("ceiling_plane")
    ceil_obj = bpy.data.objects.new("ceiling_plane", ceil_mesh)
    bpy.context.collection.objects.link(ceil_obj)
    bm_c = bmesh.new()
    _add_plane(bm_c, size=2.0)
    bm_c.to_mesh(ceil_mesh)
    bm_c.free()
    bpy.context.view_layer.objects.active = ceil_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

    ceil_info = dict(MATERIAL_PALETTE["rough_granite"])
    ceil_info["base_rgb"] = tuple(min(1.0, c * 1.45) for c in ceil_info["base_rgb"])
    ceil_info["mottle_rgb"] = tuple(min(1.0, c * 1.35) for c in ceil_info["mottle_rgb"])
    albedo, normal, orm = _build_stone_material(
        ceil_mesh, "ceil_mat", ceil_info, seed=2.0
    )
    _save_textures(albedo, normal, orm, out_dir, "ceiling")


def _save_textures(albedo_img, normal_img, orm_img, out_dir, prefix):
    """Save textures as PNGs to *out_dir* with given *prefix*."""
    for img, suffix in [(albedo_img, "albedo"),
                         (normal_img, "normal"),
                         (orm_img, "orm")]:
        path = os.path.join(out_dir, f"shell_{prefix}_{suffix}.png")
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        print(f"  wrote {path}")


main()
