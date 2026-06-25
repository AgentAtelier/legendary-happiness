"""Run INSIDE Blender:
    blender --background --python shell_materials.py -- <out_dir> [res]

Bakes tiling PBR texture sets for the room shell's two material kinds:
    stone  → walls / roof boards   (ashlar blocks + mortar joints, real contrast)
    timber → floor / beams         (directional grain + plank seams)

Writes shell_{stone,timber}_{albedo,normal,orm}.png to <out_dir>.

Replaces the old build_shell_textures.py, whose single-octave grey Voronoi ramp
(~0.15 luminance spread, no structure, normal strength 0.2) produced flat mush.
Socket names target Blender 4.x/5.x ("Factor", not "Fac").
"""

import os
import sys

import bmesh
import bpy


def _argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


# ── node graphs ─────────────────────────────────────────────────

def build_stone_nodes(nodes, links, seed):
    """Ashlar stone walls: multi-octave tone × dark mortar joints. High contrast.
    Task 4: multi-octave Voronoi blend breaks up single-octave procedural tell.
    Returns (color_socket, height_socket)."""
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping")
    mp.vector_type = "TEXTURE"
    mp.inputs["Scale"].default_value = (5, 5, 5)  # Task 3: increased from 3
    mp.inputs["Location"].default_value = (seed, seed, 0)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    # large-scale tone variation, multi-octave
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 4.0
    n.inputs["Detail"].default_value = 8.0
    n.inputs["Roughness"].default_value = 0.65
    links.new(mp.outputs["Vector"], n.inputs["Vector"])

    # Task 4: multi-octave Voronoi blend — three scales mixed to break
    # the recognizable single-octave procedural look.
    v1 = nodes.new("ShaderNodeTexVoronoi")
    v1.feature = "DISTANCE_TO_EDGE"
    v1.inputs["Scale"].default_value = 6.0
    links.new(mp.outputs["Vector"], v1.inputs["Vector"])

    v2 = nodes.new("ShaderNodeTexVoronoi")
    v2.feature = "DISTANCE_TO_EDGE"
    v2.inputs["Scale"].default_value = 12.0
    links.new(mp.outputs["Vector"], v2.inputs["Vector"])

    v3 = nodes.new("ShaderNodeTexVoronoi")
    v3.feature = "DISTANCE_TO_EDGE"
    v3.inputs["Scale"].default_value = 24.0
    links.new(mp.outputs["Vector"], v3.inputs["Vector"])

    # Blend voronoi octaves
    v_mix1 = nodes.new("ShaderNodeMixRGB")
    v_mix1.blend_type = "MIX"
    v_mix1.inputs["Factor"].default_value = 0.4
    links.new(v1.outputs["Distance"], v_mix1.inputs["Color1"])
    links.new(v2.outputs["Distance"], v_mix1.inputs["Color2"])

    v_mix2 = nodes.new("ShaderNodeMixRGB")
    v_mix2.blend_type = "MIX"
    v_mix2.inputs["Factor"].default_value = 0.25
    links.new(v_mix1.outputs["Color"], v_mix2.inputs["Color1"])
    links.new(v3.outputs["Distance"], v_mix2.inputs["Color2"])

    # Mortar joint ramp from blended Voronoi
    joints = nodes.new("ShaderNodeValToRGB")
    j = joints.color_ramp.elements
    j[0].position = 0.0
    j[0].color = (0.05, 0.05, 0.05, 1)   # mortar (dark, recessed)
    j[1].position = 0.06
    j[1].color = (1, 1, 1, 1)            # stone face
    links.new(v_mix2.outputs["Color"], joints.inputs["Factor"])

    # stone face color with real contrast (warm grey, spread > 0.35)
    face = nodes.new("ShaderNodeValToRGB")
    f = face.color_ramp.elements
    f[0].position = 0.0
    f[0].color = (0.30, 0.28, 0.26, 1)
    f[1].position = 1.0
    f[1].color = (0.80, 0.77, 0.72, 1)
    links.new(n.outputs["Factor"], face.inputs["Factor"])

    mul = nodes.new("ShaderNodeMixRGB")
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    links.new(face.outputs["Color"], mul.inputs["Color1"])
    links.new(joints.outputs["Color"], mul.inputs["Color2"])
    return mul.outputs["Color"], joints.outputs["Color"]


def build_roof_nodes(nodes, links, seed):
    """Roof/ceiling: darker, higher roughness, distinct from wall stone.
    Subtle wood-plank-like grain + darker tone so the ceiling reads as
    a different surface from the walls.
    Returns (color_socket, height_socket)."""
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping")
    mp.vector_type = "TEXTURE"
    mp.inputs["Scale"].default_value = (4, 4, 4)
    mp.inputs["Location"].default_value = (seed + 10, seed, 0)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 5.0
    n.inputs["Detail"].default_value = 6.0
    n.inputs["Roughness"].default_value = 0.7
    links.new(mp.outputs["Vector"], n.inputs["Vector"])

    # Subtle plank-like banding along one axis
    planks = nodes.new("ShaderNodeTexWave")
    planks.wave_type = "BANDS"
    planks.inputs["Scale"].default_value = 2.0
    links.new(mp.outputs["Vector"], planks.inputs["Vector"])

    seams = nodes.new("ShaderNodeValToRGB")
    s = seams.color_ramp.elements
    s[0].position = 0.0
    s[0].color = (0.08, 0.07, 0.06, 1)   # seam
    s[1].position = 0.05
    s[1].color = (1, 1, 1, 1)
    links.new(planks.outputs["Color"], seams.inputs["Factor"])

    # Darker tone ramp (distinct from warm wall stone)
    tone = nodes.new("ShaderNodeValToRGB")
    t = tone.color_ramp.elements
    t[0].position = 0.0
    t[0].color = (0.20, 0.18, 0.16, 1)   # dark brown-grey
    t[1].position = 1.0
    t[1].color = (0.52, 0.48, 0.44, 1)   # light roof tone
    links.new(n.outputs["Factor"], tone.inputs["Factor"])

    mul = nodes.new("ShaderNodeMixRGB")
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    links.new(tone.outputs["Color"], mul.inputs["Color1"])
    links.new(seams.outputs["Color"], mul.inputs["Color2"])
    return mul.outputs["Color"], seams.outputs["Color"]


def build_timber_nodes(nodes, links, seed):
    """Oak planks: directional grain × plank seams. Returns (color, height)."""
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping")
    mp.vector_type = "TEXTURE"
    mp.inputs["Scale"].default_value = (1.0, 8.0, 1.0)   # stretch along grain
    mp.inputs["Location"].default_value = (seed, 0, 0)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 6.0
    grain.inputs["Detail"].default_value = 6.0
    links.new(mp.outputs["Vector"], grain.inputs["Vector"])

    planks = nodes.new("ShaderNodeTexWave")
    planks.wave_type = "BANDS"
    planks.inputs["Scale"].default_value = 1.5
    links.new(tc.outputs["Object"], planks.inputs["Vector"])
    seams = nodes.new("ShaderNodeValToRGB")
    s = seams.color_ramp.elements
    s[0].position = 0.0
    s[0].color = (0.06, 0.04, 0.02, 1)   # seam (dark)
    s[1].position = 0.04
    s[1].color = (1, 1, 1, 1)
    links.new(planks.outputs["Color"], seams.inputs["Factor"])

    wood = nodes.new("ShaderNodeValToRGB")
    w = wood.color_ramp.elements
    w[0].position = 0.0
    w[0].color = (0.20, 0.11, 0.05, 1)   # dark oak
    w[1].position = 1.0
    w[1].color = (0.58, 0.38, 0.19, 1)   # light oak (spread)
    links.new(grain.outputs["Factor"], wood.inputs["Factor"])

    mul = nodes.new("ShaderNodeMixRGB")
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    links.new(wood.outputs["Color"], mul.inputs["Color1"])
    links.new(seams.outputs["Color"], mul.inputs["Color2"])
    return mul.outputs["Color"], seams.outputs["Color"]


# ── bake harness (proven sequence from build_shell_textures.py) ──

def _build_and_bake(mesh, mat_name, node_builder, res, seed, roughness, metallic):
    obj = next(o for o in bpy.data.objects if o.data == mesh)

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    mesh.materials.append(mat)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    out = nodes.new("ShaderNodeOutputMaterial")

    color_socket, height_socket = node_builder(nodes, links, seed)

    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.2
    mix_ao = nodes.new("ShaderNodeMixRGB")
    mix_ao.blend_type = "MULTIPLY"
    mix_ao.inputs["Factor"].default_value = 1.0
    links.new(color_socket, mix_ao.inputs["Color1"])
    links.new(ao.outputs["Color"], mix_ao.inputs["Color2"])
    links.new(mix_ao.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"

    def _img(name, non_color):
        im = bpy.data.images.new(name, width=res, height=res, alpha=False, float_buffer=False)
        if non_color:
            im.colorspace_settings.name = "Non-Color"
        return im

    def _activate(tex_node):
        for n in nodes:
            n.select = False
        nodes.active = tex_node
        tex_node.select = True
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    # ── NORMAL (strong relief: strength 0.8, distance 0.15) ──
    scene.cycles.samples = 1
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.8
    bump.inputs["Distance"].default_value = 0.15
    links.new(height_socket, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    normal_img = _img("shell_normal", True)
    normal_tex = nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal_img
    _activate(normal_tex)
    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_clear=True, margin=16)

    # ── AO (16 samples to avoid noise) ──
    scene.cycles.samples = 16
    ao_img = _img("shell_ao", True)
    ao_tex = nodes.new("ShaderNodeTexImage")
    ao_tex.image = ao_img
    _activate(ao_tex)
    for link in list(out.inputs["Surface"].links):
        links.remove(link)
    emit = nodes.new("ShaderNodeEmission")
    links.new(ao.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    bpy.ops.object.bake(type="EMIT", use_clear=True, margin=16)

    # ── ALBEDO (emit the colour×AO; 1 sample is fine for emit) ──
    scene.cycles.samples = 1
    albedo_img = _img("shell_albedo", False)
    albedo_tex = nodes.new("ShaderNodeTexImage")
    albedo_tex.image = albedo_img
    _activate(albedo_tex)
    for link in list(emit.inputs["Color"].links):
        links.remove(link)
    links.new(mix_ao.outputs["Color"], emit.inputs["Color"])
    bpy.ops.object.bake(type="EMIT", use_clear=True, margin=16)

    # ── ORM pack: R=AO, G=roughness, B=metallic ──
    orm_img = _img("shell_orm", True)
    ao_px = list(ao_img.pixels[:])
    n_px = res * res
    orm = [0.0] * (n_px * 4)
    for i in range(n_px):
        orm[4 * i + 0] = ao_px[4 * i]
        orm[4 * i + 1] = roughness
        orm[4 * i + 2] = metallic
        orm[4 * i + 3] = 1.0
    orm_img.pixels[:] = orm
    return albedo_img, normal_img, orm_img


def _make_plane(name):
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=2.0)
    bm.to_mesh(me)
    bm.free()
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    return me


def _save(albedo, normal, orm, out_dir, prefix):
    for img, suffix in [(albedo, "albedo"), (normal, "normal"), (orm, "orm")]:
        path = os.path.join(out_dir, f"shell_{prefix}_{suffix}.png")
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        print(f"  wrote {path}")


def main():
    args = _argv()
    out_dir = args[0]
    res = int(args[1]) if len(args) > 1 else 1024
    os.makedirs(out_dir, exist_ok=True)

    surfaces = [
        ("wall", build_stone_nodes, 1.0, 0.9, 0.0),
        ("roof", build_roof_nodes, 3.0, 0.85, 0.0),
        ("timber", build_timber_nodes, 2.0, 0.7, 0.0),
    ]
    for prefix, builder, seed, rough, metal in surfaces:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = _make_plane(f"{prefix}_plane")
        albedo, normal, orm = _build_and_bake(mesh, f"{prefix}_mat", builder, res, seed, rough, metal)
        _save(albedo, normal, orm, out_dir, prefix)


if __name__ == "__main__":
    main()

