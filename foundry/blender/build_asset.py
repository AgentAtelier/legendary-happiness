"""Run INSIDE Blender:
    blender --background --python build_asset.py -- <spec_json> <out_glb>

Slice 3 adds UV unwrapping, a procedural wood material with shader nodes, and
Cycles-CPU baking of the base color to an embedded image texture so the glTF
exporter writes a baseColorTexture. Blender is Z-up; the glTF exporter writes
Y-up, so the GLB has height on Y, footprint on X/Z.
"""

import hashlib
import json
import math
import os
import random
import struct
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


def _add_cylinder(bm, cx, cy, cz, radius, height, segments=16):
    """Add a cylinder (Z-up) centred at (cx, cy, cz) with given radius and height.

    Uses bmesh.ops.create_cone with equal diameters for a straight cylinder.
    The default cone has base at z=0, top at z=height; we shift to centre at cz.
    """
    res = bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=radius, radius2=radius, depth=height,
    )
    for v in res["verts"]:
        v.co.z += cz - height / 2.0
        v.co.x += cx
        v.co.y += cy


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


def _metal_color_nodes(nodes, links, mat_info, seed):
    """Build a metal-specific colour subgraph: mostly flat dark tint with a
    subtle noise streak for variation, 2-stop ramp between tint_rgb and base_rgb.

    Returns the ColorRamp's Color output socket."""
    tint = mat_info["tint_rgb"]
    base = mat_info["base_rgb"]

    # Object-space coordinate chain
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1000, 300)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-800, 300)
    mapping.vector_type = "TEXTURE"
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 4.0)
    mapping.inputs["Location"].default_value = (seed, seed, 0.0)

    # Subtle noise streak for surface variation
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, 300)
    noise.inputs["Scale"].default_value = 20.0
    noise.inputs["Detail"].default_value = 2.0
    noise.inputs["Roughness"].default_value = 0.9

    # Wire coordinates → noise
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    # ColorRamp: 2-stop dark tint → slightly lighter base
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (200, 300)
    ramp.color_ramp.interpolation = "LINEAR"
    stops = ramp.color_ramp.elements
    stops[0].position = 0.0
    stops[0].color = (*tint, 1.0)
    stops[1].position = 1.0
    stops[1].color = (*base, 1.0)

    # Wire noise fac → ramp
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    # Slice 4: also expose noise.Fac as the NORMAL-bake height source.
    return ramp.outputs["Color"], noise.outputs["Fac"]


def apply_roughness_bake(
    obj, nodes, links, bsdf,
    baseline_roughness, metallic_factor,
    image_name="baked_metallic_roughness",
):
    """Bake a packed ``metallicRoughnessTexture`` image so the glTF
    exporter emits a single ``metallicRoughnessTexture`` entry.

    Channel convention (matches glTF 2.0 spec):
      R = unused
      G = roughness (per-material base ± small noise variation)
      B = metallic_factor (per-material constant)
      A = 1

    Pipeline:
      1. Build a procedural roughness subgraph with a fresh low-frequency
         noise that modulates ``baseline_roughness`` by ±0.05 (small
         amplitude; reusing the procedural-noise concept from slice 4).
      2. Cycles EMIT bake a grayscale roughness image (R=G=B=roughness).
      3. Python post-pack the pixels into the final layout
         (R=0, G=roughness, B=metallic_factor, A=1).
      4. Restore BSDF as the surface; wire ``TexImage → SepRGB →
         {G → BSDF.Roughness, B → BSDF.Metallic}``.

    Determinism: Cycles CPU + samples=1 + seeded mapping coords (same
    chain as colour builders) + Python rounding -> byte-identical GLB
    for identical spec.
    """
    # Cycles CPU is required for baking; idempotent with the
    # EMIT-pass setup that already ran.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1

    # 1 ── Roughness subgraph: baseline + ±0.05 noise variation.
    #
    # Blender 4.0+ Noise Texture ``Fac`` output is signed [-1, +1]; the
    # classic ``[0,1]`` mapping from earlier versions is gone.  The
    # chain below remaps that signed value through ``/2`` -> [-0.5,+0.5]
    # -> ``*amp`` -> [-0.05,+0.05] -> ``+baseline`` so the per-pixel
    # roughness is baseline ±0.05.  Two Math nodes are enough.
    tex_coord_rr = nodes.new("ShaderNodeTexCoord")
    tex_coord_rr.location = (-1000, -300)

    mapping_rr = nodes.new("ShaderNodeMapping")
    mapping_rr.location = (-800, -300)
    mapping_rr.vector_type = "TEXTURE"
    # Different scale than colour builders so roughness variation
    # doesn't correlate with colour bands.
    mapping_rr.inputs["Scale"].default_value = (3.0, 3.0, 3.0)
    mapping_rr.inputs["Location"].default_value = (0.0, 0.0, 0.0)

    noise_rr = nodes.new("ShaderNodeTexNoise")
    noise_rr.location = (-600, -300)
    noise_rr.inputs["Scale"].default_value = 8.0
    noise_rr.inputs["Detail"].default_value = 2.0
    noise_rr.inputs["Roughness"].default_value = 0.7

    # Map signed [-1, +1] -> [-0.5, +0.5] -> [-0.05, +0.05] -> centred on baseline.
    div2 = nodes.new("ShaderNodeMath")
    div2.operation = "DIVIDE"
    div2.inputs[1].default_value = 2.0
    div2.location = (-400, -300)

    scale_amp = nodes.new("ShaderNodeMath")
    scale_amp.operation = "MULTIPLY"
    scale_amp.inputs[1].default_value = 0.1  # total amplitude ±0.05
    scale_amp.location = (-200, -300)

    add_base = nodes.new("ShaderNodeMath")
    add_base.operation = "ADD"
    add_base.inputs[1].default_value = baseline_roughness
    add_base.location = (0, -300)

    links.new(tex_coord_rr.outputs["Object"], mapping_rr.inputs["Vector"])
    links.new(mapping_rr.outputs["Vector"], noise_rr.inputs["Vector"])
    links.new(noise_rr.outputs["Fac"], div2.inputs[0])
    links.new(div2.outputs["Value"], scale_amp.inputs[0])
    links.new(scale_amp.outputs["Value"], add_base.inputs[0])

    roughness_socket = add_base.outputs["Value"]

    # 2 ── Image to initially bake the scalar roughness into.
    rough_image = bpy.data.images.new(
        image_name, width=1024, height=1024,
        alpha=False, float_buffer=False,
    )
    rough_image.file_format = "PNG"
    rough_image.colorspace_settings.name = "Non-Color"

    rough_tex = nodes.new("ShaderNodeTexImage")
    rough_tex.image = rough_image
    rough_tex.location = (200, -300)

    # Cycles bakes only into the SELECTED + active TexImage; clear other
    # selections so subsequent bakes don't bleed into this one.
    saved_select = {n.name: n.select for n in nodes}
    for n in nodes:
        n.select = False
    nodes.active = rough_tex
    rough_tex.select = True

    # 3 ── Object must be selected + active for the bake call.
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # 4 ── Swap Surface for an Emission that emits the scalar roughness
    #       in RGB (grayscale, since R=G=B=roughness).
    material_output = next(
        (n for n in nodes if n.type == "OUTPUT_MATERIAL"), None
    )
    if material_output is None:
        raise RuntimeError("expected an OUTPUT_MATERIAL node in the graph")
    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)

    combine = nodes.new("ShaderNodeCombineColor")
    combine.location = (200, -500)
    links.new(roughness_socket, combine.inputs["Red"])
    links.new(roughness_socket, combine.inputs["Green"])
    links.new(roughness_socket, combine.inputs["Blue"])

    emit = nodes.new("ShaderNodeEmission")
    emit.location = (400, -500)
    links.new(combine.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], material_output.inputs["Surface"])

    bpy.ops.object.bake(type="EMIT", use_clear=True)

    # 5 ── Restore BSDF as the material output surface.
    for link in list(material_output.inputs["Surface"].links):
        links.remove(link)
    for socket_name in ("Red", "Green", "Blue"):
        for link in list(combine.inputs[socket_name].links):
            links.remove(link)
    for link in list(emit.inputs["Color"].links):
        links.remove(link)
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])

    # 6 ── Python post-pack: bake produced R=G=B=roughness; re-pack into
    #       the glTF metallicRoughnessTexture channel convention
    #       R=0, G=roughness_value, B=metallic_factor, A=1.
    src_pixels = list(rough_image.pixels[:])
    px_count = len(src_pixels) // 4
    out = [0.0] * (px_count * 4)
    for i in range(px_count):
        # The bake wrote the scalar roughness value into all three RGB
        # channels; pick the green channel since that maps to roughness.
        g = src_pixels[4 * i + 1]
        out[4 * i + 1] = g
        out[4 * i + 2] = float(metallic_factor)
        out[4 * i + 3] = 1.0
    rough_image.pixels[:] = out

    # 7 ── Wire: TexImage -> SeparateColor -> {BSDF.Roughness, BSDF.Metallic}.
    sep = nodes.new("ShaderNodeSeparateColor")
    sep.location = (600, -300)
    links.new(rough_tex.outputs["Color"], sep.inputs["Color"])

    # When BSDF.Roughness/Metallic sockets are image-driven, the
    # default_value is irrelevant — but reset to 0.0 so any future
    # deletion of the link leaves a benign fallback rather than the
    # unexpected "baseline_roughness" the material palette reported.
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["Metallic"].default_value = 0.0
    links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

    # 8 ── Cleanup intermediate roughness-subgraph + bake nodes.
    for n in (emit, combine, add_base, scale_amp, div2,
              noise_rr, mapping_rr, tex_coord_rr):
        nodes.remove(n)

    # 9 ── Pack so the GLB carries the metallicRoughness image.
    rough_image.pack()

    # Restore prior selection state (apply_material does not bake again).
    for n in nodes:
        n.select = False
    for name, was in saved_select.items():
        if was:
            try:
                nodes[name].select = True
            except KeyError:
                pass
    nodes.active = None


def _stone_color_nodes(nodes, links, mat_info, seed):
    """Build a stone-specific colour subgraph: object-space coords with
    Voronoi+Noise → 3-stop ColorRamp for mottled-grey granite look.

    Returns the ColorRamp's Color output socket."""
    base = mat_info["base_rgb"]
    mottle = mat_info["mottle_rgb"]

    # Object-space coordinate chain (same as wood for shared grounding)
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1000, 300)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-800, 300)
    mapping.vector_type = "TEXTURE"
    mapping.inputs["Scale"].default_value = (2.0, 2.0, 2.0)
    mapping.inputs["Location"].default_value = (seed, seed, 0.0)

    # ── Voronoi for stone mottling ───────────────────────────
    voronoi = nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (-600, 300)
    voronoi.inputs["Scale"].default_value = 8.0

    # ── Noise overlay for secondary variation ────────────────
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-600, 0)
    noise.inputs["Scale"].default_value = 12.0
    noise.inputs["Detail"].default_value = 4.0
    noise.inputs["Roughness"].default_value = 0.6

    # Mix Voronoi + Noise 50/50 for a composite fac
    mix_textures = nodes.new("ShaderNodeMixRGB")
    mix_textures.blend_type = "MIX"
    mix_textures.location = (-300, 300)
    mix_textures.inputs["Fac"].default_value = 0.5

    # ── Wire the coordinate chain ────────────────────────────
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(voronoi.outputs["Color"], mix_textures.inputs["Color1"])
    links.new(noise.outputs["Color"], mix_textures.inputs["Color2"])

    # ColorRamp: 3-stop mottled-grey → base → mottle → base
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

    # Wire mix output → ramp (ColorRamp auto-converts colour to greyscale)
    links.new(mix_textures.outputs["Color"], ramp.inputs["Fac"])

    # Slice 4: also expose voronoi.Distance as the NORMAL-bake height
    # source — cells' edge-distance reads convincingly as mottled relief.
    return ramp.outputs["Color"], voronoi.outputs["Distance"]


def _wood_color_nodes(nodes, links, mat_info, seed):
    """Build the wood-specific colour subgraph: object-space coords with
    noise warp → Wave Texture (bands) → CONSTANT ColorRamp of wood tones.

    Returns the ColorRamp's Color output socket."""
    dark = mat_info["grain_dark_rgb"]
    light = mat_info["grain_light_rgb"]

    # ── Object-space coordinate chain ───────────────────────
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1000, 300)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-800, 300)
    mapping.vector_type = "TEXTURE"
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 3.0)
    mapping.inputs["Location"].default_value = (seed, seed, 0.0)

    # ── Noise warp (breaks parallel stripe corduroy) ─────────
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-800, 0)
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.75

    noise_scale = nodes.new("ShaderNodeVectorMath")
    noise_scale.operation = "MULTIPLY"
    noise_scale.location = (-600, 0)
    noise_scale.inputs[1].default_value = (0.35, 0.35, 0.35)

    warp_add = nodes.new("ShaderNodeVectorMath")
    warp_add.operation = "ADD"
    warp_add.location = (-400, 300)

    # ── Wave Texture (bands) for wood grain ─────────────────
    wave = nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 9.0
    wave.inputs["Distortion"].default_value = 4.0
    wave.inputs["Detail"].default_value = 5.0
    wave.inputs["Detail Scale"].default_value = 3.0
    wave.location = (-200, 300)

    # ── Wire the coordinate warp chain ──────────────────────
    links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], warp_add.inputs[0])
    links.new(noise.outputs["Color"], noise_scale.inputs[0])
    links.new(noise_scale.outputs["Vector"], warp_add.inputs[1])
    links.new(warp_add.outputs["Vector"], wave.inputs["Vector"])

    # ColorRamp: map wave fac to wood tones from the palette.
    # CONSTANT interpolation → stepped, painted-band read.
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (200, 300)
    ramp.color_ramp.interpolation = "CONSTANT"
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

    # Wire wave → ramp
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])

    # Slice 4: also expose wave.Fac as the NORMAL-bake height source.
    return ramp.outputs["Color"], wave.outputs["Fac"]


def _build_shelf_geometry(params):
    """Build a shelf unit: two side panels + N horizontal boards.

    Layout (Z-up): side panels run full height on left/right edges.
    Boards are evenly distributed between bottom and top."""
    w, d, h = params["width"], params["depth"], params["height"]
    bt = params["board_thickness"]
    n = int(params["n_shelves"])
    st = params["side_thickness"]

    mesh = bpy.data.meshes.new("shelf")
    obj = bpy.data.objects.new("shelf", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # ── Two side panels ──────────────────────────────────────
    panel_x = w / 2.0 - st / 2.0
    for sx in (-1, 1):
        _add_box(bm, sx * panel_x, 0.0, h / 2.0, st, d, h)

    # ── N horizontal boards ──────────────────────────────────
    # Distribute evenly from bottom_board_z to top_board_z
    bottom_z = bt / 2.0
    top_z = h - bt / 2.0
    for i in range(n):
        t = i / max(n - 1, 1)
        board_z = bottom_z + t * (top_z - bottom_z)
        _add_box(bm, 0.0, 0.0, board_z, w, d, bt)

    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_cabinet_geometry(params):
    """Build a cabinet: closed box body on a short base/plinth.

    Layout (Z-up): plinth at the bottom, body sits on top."""
    w, d, h = params["width"], params["depth"], params["height"]
    pt = params["panel_thickness"]
    bh = params["base_height"]

    body_h = h - bh

    mesh = bpy.data.meshes.new("cabinet")
    obj = bpy.data.objects.new("cabinet", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # ── Base / plinth ────────────────────────────────────────
    _add_box(bm, 0.0, 0.0, bh / 2.0, w, d, bh)

    # ── Body (closed box — hollow shell via panel walls) ─────
    body_cz = bh + body_h / 2.0

    # Floor panel
    _add_box(bm, 0.0, 0.0, bh + pt / 2.0, w, d, pt)

    # Ceiling panel
    _add_box(bm, 0.0, 0.0, h - pt / 2.0, w, d, pt)

    # Left + right walls
    wall_x = w / 2.0 - pt / 2.0
    for sx in (-1, 1):
        _add_box(bm, sx * wall_x, 0.0, body_cz, pt, d - 2 * pt, body_h)

    # Back wall
    wall_y = -(d / 2.0 - pt / 2.0)
    _add_box(bm, 0.0, wall_y, body_cz, w - 2 * pt, pt, body_h)

    # Front wall (closed box)
    front_y = +(d / 2.0 - pt / 2.0)
    _add_box(bm, 0.0, front_y, body_cz, w - 2 * pt, pt, body_h)

    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_humanoid_geometry(params):
    """Build a stylized low-poly humanoid from box primitives (P7).

    P7 OFF-RAMP NOTE: The box-primitive humanoid may not be perfectly
    watertight at arm/torso interfaces (coplanar faces at the same Z
    range create non-manifold edges).  This is an accepted trade-off
    for the off-ramp golem/totem form; the full humanoid (with boolean
    union or armature-based skinning) is a P7+ ticket.

    Proportions (all as fractions of total_height):
      - Head:        ~0.18× at top
      - Neck:        0.05× thin connector
      - Torso:       ~0.35× centred above legs
      - Upper arms:  ~0.18× each side of torso
      - Forearms:    ~0.18× below upper arms
      - Thighs:      ~0.22× below torso
      - Calves:      ~0.22× below thighs
      - Feet:        0.04× small blocks at base

    All parts are axis-aligned boxes.  The mesh is a single merged
    bmesh so the gate's watertight check passes (position-welded).

    Also adds a simple idle bob animation: Z-location keyframes on
    the root object (0→+0.04→0 over 60 frames, cyclic).
    """
    th = params["total_height"]
    bw = params["body_width"]
    lt = params["limb_thickness"]
    hs = params["head_size"]

    # Derived dimensions (fixed ratios of total_height)
    head_h = hs
    head_w = hs * 0.75
    head_d = hs * 0.7

    neck_h = th * 0.04
    neck_w = lt * 0.8
    neck_d = lt * 0.8

    torso_h = th * 0.32
    torso_w = bw
    torso_d = bw * 0.55

    upper_arm_len = th * 0.17
    upper_arm_w = lt
    upper_arm_d = lt * 0.8

    forearm_len = th * 0.17
    forearm_w = lt * 0.85
    forearm_d = lt * 0.7

    thigh_len = th * 0.22
    thigh_w = lt * 1.1
    thigh_d = lt * 0.9

    calf_len = th * 0.22
    calf_w = lt * 0.95
    calf_d = lt * 0.8

    foot_h = th * 0.04
    foot_w = lt * 1.2
    foot_d = lt * 1.4

    mesh = bpy.data.meshes.new("humanoid")
    obj = bpy.data.objects.new("humanoid", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # Z-level layout (bottom to top):
    #   foot_bottom = 0
    #   calf: foot_h → foot_h + calf_len
    #   thigh: foot_h + calf_len → foot_h + calf_len + thigh_len
    #   torso: foot_h + calf_len + thigh_len → ... + torso_h
    #   neck: ... → ... + neck_h
    #   head: ... → ... + head_h

    foot_bottom = foot_h / 2.0
    calf_cz = foot_h + calf_len / 2.0
    thigh_cz = foot_h + calf_len + thigh_len / 2.0
    torso_cz = foot_h + calf_len + thigh_len + torso_h / 2.0
    neck_cz = foot_h + calf_len + thigh_len + torso_h + neck_h / 2.0
    head_cz = foot_h + calf_len + thigh_len + torso_h + neck_h + head_h / 2.0

    shoulder_y = foot_h + calf_len + thigh_len + torso_h
    hip_y = foot_h + calf_len + thigh_len

    # ── Feet ──────────────────────────────────────────────────
    foot_spread = lt * 0.6
    for sx in (-1, 1):
        _add_box(bm, sx * foot_spread, 0.0, foot_bottom,
                 foot_w, foot_d, foot_h)

    # ── Calves ───────────────────────────────────────────────
    leg_x = lt * 0.55
    for sx in (-1, 1):
        _add_box(bm, sx * leg_x, 0.0, calf_cz,
                 calf_w, calf_d, calf_len)

    # ── Thighs ───────────────────────────────────────────────
    for sx in (-1, 1):
        _add_box(bm, sx * leg_x, 0.0, thigh_cz,
                 thigh_w, thigh_d, thigh_len)

    # ── Torso ────────────────────────────────────────────────
    _add_box(bm, 0.0, 0.0, torso_cz, torso_w, torso_d, torso_h)

    # ── Upper arms ───────────────────────────────────────────
    arm_x = torso_w / 2.0 + upper_arm_w / 2.0
    upper_arm_cz = shoulder_y - upper_arm_len / 2.0
    for sx in (-1, 1):
        _add_box(bm, sx * arm_x, 0.0, upper_arm_cz,
                 upper_arm_w, upper_arm_d, upper_arm_len)

    # ── Forearms ─────────────────────────────────────────────
    forearm_cz = shoulder_y - upper_arm_len - forearm_len / 2.0
    for sx in (-1, 1):
        _add_box(bm, sx * arm_x, 0.0, forearm_cz,
                 forearm_w, forearm_d, forearm_len)

    # ── Neck ─────────────────────────────────────────────────
    _add_box(bm, 0.0, 0.0, neck_cz, neck_w, neck_d, neck_h)

    # ── Head ─────────────────────────────────────────────────
    _add_box(bm, 0.0, 0.0, head_cz, head_w, head_d, head_h)

    bm.to_mesh(mesh)
    bm.free()

    # ── Idle bob animation (P7 off-ramp: object-level Z oscillation) ─
    _add_idle_bob(obj)

    return mesh


def _add_idle_bob(obj, amplitude=0.04, period=60):
    """Add a simple cyclic idle bob animation on the root object.

    Animates Z-location: 0 → +amplitude → 0 over *period* frames,
    with MAKE_CYCLIC extrapolation so the glTF exporter writes a
    looping default animation.

    Handles both Blender 4.x (action.fcurves.new) and 5.x
    (action.fcurve_ensure_for_datablock / layers API).  Skips the
    animation gracefully if neither API is available.
    """
    obj.animation_data_create()
    action = bpy.data.actions.new(name="idle_bob")
    obj.animation_data.action = action

    fcurves = []

    # Try Blender 4.x API first
    if hasattr(action, "fcurves") and hasattr(action.fcurves, "new"):
        for idx in range(3):
            fc = action.fcurves.new(data_path="location", index=idx)
            fcurves.append(fc)
    # Try Blender 5.x fcurve_ensure API
    elif hasattr(action, "fcurve_ensure_for_datablock"):
        for idx in range(3):
            try:
                fc = action.fcurve_ensure_for_datablock(
                    data_path="location", index=idx
                )
                if fc is not None:
                    fcurves.append(fc)
            except Exception:
                pass
    # Fallback: use layers API (Blender 5.1+)
    elif hasattr(action, "layers"):
        try:
            layer = action.layers.new("idle_bob")
            # In Blender 5.x, strips replace the old fcurves-per-action model.
            # Try to get/create fcurves through the layer.
            for idx in range(3):
                # Use keyframe_insert on the object as the simplest fallback
                pass
        except Exception:
            pass

    if not fcurves:
        # Could not create FCurves — skip idle animation gracefully.
        # The GLB will export fine without it.
        return

    # Only animate Z (index 2).  X and Y stay at 0.
    if len(fcurves) >= 3:
        z_curve = fcurves[2]
    else:
        return

    # Keyframes: frame 0 → 0, frame period/2 → amplitude, frame period → 0
    z_curve.keyframe_points.insert(0, 0.0)
    z_curve.keyframe_points.insert(period / 2, amplitude)
    z_curve.keyframe_points.insert(period, 0.0)

    # Linear interpolation
    for kp in z_curve.keyframe_points:
        kp.interpolation = "LINEAR"

    # Cyclic: loop forever
    for fc in fcurves:
        fc.modifiers.new("CYCLES")


def _build_rug_geometry(params):
    """A thin flat watertight box — a rug/mat lying on the floor (#6 decor)."""
    w, d, t = params["width"], params["depth"], params["thickness"]
    mesh = bpy.data.meshes.new("rug")
    obj = bpy.data.objects.new("rug", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, t / 2.0, w, d, t)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_painting_geometry(params):
    """A thin vertical watertight box — a framed painting to hang on a wall
    (#6 decor). Thin axis is Y (Blender) → becomes depth in the Y-up GLB;
    width=X, height=Z. The layout's yaw faces it into the room."""
    w, h, t = params["width"], params["height"], params["thickness"]
    mesh = bpy.data.meshes.new("painting")
    obj = bpy.data.objects.new("painting", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, t, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


# ── P-E: 10 carryable generators (≤0.3 m) ────────────────────────

def _build_key_geometry(params):
    """A small flat key: rectangular head + thin shaft."""
    hw, hh, sl = params["head_w"], params["head_h"], params["shaft_l"]
    mesh = bpy.data.meshes.new("key")
    obj = bpy.data.objects.new("key", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    # Head: flat box at origin (≥0.01 m all dims for gate pass)
    ht = 0.012
    _add_box(bm, 0.0, 0.0, 0.0, hw, hh, ht)
    # Shaft: thin box extending from head
    shaft_cx = hw / 2.0 + sl / 2.0
    _add_box(bm, shaft_cx, 0.0, 0.0, sl, 0.012, ht)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_book_geometry(params):
    """A flat rectangular book."""
    w, d, t = params["width"], params["depth"], params["thickness"]
    mesh = bpy.data.meshes.new("book")
    obj = bpy.data.objects.new("book", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, t / 2.0, w, d, t)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_cup_geometry(params):
    """A small cup: cylinder body + box handle."""
    r, h = params["radius"], params["height"]
    mesh = bpy.data.meshes.new("cup")
    obj = bpy.data.objects.new("cup", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, h / 2.0, r, h)
    # Handle: small box inset so it overlaps the cylinder body for watertightness
    handle_r = r - 0.005
    _add_box(bm, handle_r, 0.0, h * 0.55, 0.03, 0.01, h * 0.25)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_gem_geometry(params):
    """A small faceted gem (box approximation)."""
    s = params["size"]
    mesh = bpy.data.meshes.new("gem")
    obj = bpy.data.objects.new("gem", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, s * 0.6, s * 0.7, s * 0.5, s)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_bottle_geometry(params):
    """A small bottle: cylinder body + narrower cylinder neck."""
    br, bh = params["body_radius"], params["body_height"]
    nr, nh = params["neck_radius"], params["neck_height"]
    mesh = bpy.data.meshes.new("bottle")
    obj = bpy.data.objects.new("bottle", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, bh / 2.0, br, bh)
    _add_cylinder(bm, 0.0, 0.0, bh + nh / 2.0, nr, nh)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_scroll_geometry(params):
    """A thin cylindrical scroll."""
    r, length = params["radius"], params["length"]
    mesh = bpy.data.meshes.new("scroll")
    obj = bpy.data.objects.new("scroll", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, length / 2.0, r, length)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_coin_pouch_geometry(params):
    """A small flattened pouch."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("coin_pouch")
    obj = bpy.data.objects.new("coin_pouch", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_candle_geometry(params):
    """A small candle: cylinder body + tiny cylinder wick."""
    r, h = params["radius"], params["height"]
    mesh = bpy.data.meshes.new("candle")
    obj = bpy.data.objects.new("candle", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, h / 2.0, r, h)
    # Wick: tiny cylinder on top
    _add_cylinder(bm, 0.0, 0.0, h + 0.015, 0.008, 0.03, segments=8)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_dagger_geometry(params):
    """A small dagger: long thin blade box + handle box + crossguard nub."""
    bl, bw = params["blade_l"], params["blade_w"]
    hl = params["handle_l"]
    bt = 0.015  # blade thickness
    mesh = bpy.data.meshes.new("dagger")
    obj = bpy.data.objects.new("dagger", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    # Blade: long thin box extending in +X
    blade_cx = bl / 2.0
    _add_box(bm, blade_cx, 0.0, 0.0, bl, bw, bt)
    # Handle: shorter box behind the blade
    handle_cx = -hl / 2.0
    _add_box(bm, handle_cx, 0.0, 0.0, hl, bw * 0.7, bw * 0.7)
    # Crossguard: thin box at blade/handle junction, offset in Y to avoid coplanar faces
    _add_box(bm, 0.0, 0.001, 0.0, bw * 1.5, 0.008, bw * 0.6)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_ring_geometry(params):
    """A small ring: thin flat disc (cylinder).  Reads as a ring at this scale."""
    s = params["size"]  # outer diameter
    ht = 0.012            # ring height (thin band)
    mesh = bpy.data.meshes.new("ring")
    obj = bpy.data.objects.new("ring", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, ht / 2.0, s / 2.0, ht, segments=24)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


# ── P-F: 20 stress-test prop generators ────────────────────────────

def _build_barrel_geometry(params):
    """A barrel: cylinder body + 3 ring bands."""
    r, h = params["radius"], params["height"]
    mesh = bpy.data.meshes.new("barrel")
    obj = bpy.data.objects.new("barrel", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, h / 2.0, r, h, segments=16)
    # Three ring bands: top, middle, bottom
    br = r + 0.015
    bt = 0.02
    for frac in (0.15, 0.5, 0.85):
        _add_cylinder(bm, 0.0, 0.0, h * frac, br, bt, segments=12)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_crate_geometry(params):
    """A crate: simple box."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("crate")
    obj = bpy.data.objects.new("crate", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_chest_geometry(params):
    """A chest: box body + slightly wider lid on top."""
    w, d, h = params["width"], params["depth"], params["height"]
    body_h = h * 0.75
    lid_h = h * 0.25
    mesh = bpy.data.meshes.new("chest")
    obj = bpy.data.objects.new("chest", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, body_h / 2.0, w, d, body_h)
    _add_box(bm, 0.0, 0.0, body_h + lid_h / 2.0, w + 0.02, d + 0.02, lid_h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_stool_geometry(params):
    """A stool: cylinder seat + 3 box legs."""
    r, h = params["radius"], params["height"]
    seat_t = 0.04
    leg_h = h - seat_t
    leg_r = 0.03
    mesh = bpy.data.meshes.new("stool")
    obj = bpy.data.objects.new("stool", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, leg_h + seat_t / 2.0, r, seat_t, segments=20)
    for angle in (0.0, 2.094, 4.189):
        lx = r * 0.7 * math.cos(angle)
        ly = r * 0.7 * math.sin(angle)
        _add_cylinder(bm, lx, ly, leg_h / 2.0, leg_r, leg_h, segments=12)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_wardrobe_geometry(params):
    """A wardrobe: tall closed cabinet."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("wardrobe")
    obj = bpy.data.objects.new("wardrobe", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    # Crown moulding: slightly wider box on top
    _add_box(bm, 0.0, 0.0, h - 0.03, w + 0.04, d + 0.04, 0.05)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_desk_geometry(params):
    """A desk: wider table with a back panel."""
    w, d, h = params["width"], params["depth"], params["height"]
    tt = 0.05
    lh = h - tt
    lr = 0.04
    leg = lr * 2.0
    mesh = bpy.data.meshes.new("desk")
    obj = bpy.data.objects.new("desk", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, lh + tt / 2.0, w, d, tt)
    # 4 legs at corners
    hx = w / 2.0 - 0.06 - leg / 2.0
    hy = d / 2.0 - 0.06 - leg / 2.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box(bm, sx * hx, sy * hy, lh / 2.0, leg, leg, lh)
    # Back panel
    _add_box(bm, 0.0, -(d / 2.0 - 0.02), lh / 2.0 + 0.1, w, 0.03, lh * 0.6)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_lantern_geometry(params):
    """A lantern: tall thin cylinder body + wider top section."""
    r, h = params["radius"], params["height"]
    top_h = h * 0.2
    body_h = h - top_h
    mesh = bpy.data.meshes.new("lantern")
    obj = bpy.data.objects.new("lantern", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, body_h / 2.0, r, body_h, segments=16)
    _add_cylinder(bm, 0.0, 0.0, body_h + top_h / 2.0, r + 0.03, top_h, segments=16)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_pot_geometry(params):
    """A pot/urn: wider cylinder body + narrower neck."""
    br, bh = params["body_radius"], params["body_height"]
    nr, nh = params["neck_radius"], params["neck_height"]
    mesh = bpy.data.meshes.new("pot")
    obj = bpy.data.objects.new("pot", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, bh / 2.0, br, bh, segments=20)
    _add_cylinder(bm, 0.0, 0.0, bh + nh / 2.0, nr, nh, segments=16)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_weapon_rack_geometry(params):
    """A weapon rack: two tall posts + horizontal bars."""
    w, d, h = params["width"], params["depth"], params["height"]
    t = 0.04
    mesh = bpy.data.meshes.new("weapon_rack")
    obj = bpy.data.objects.new("weapon_rack", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    # Two tall posts
    for sx in (-1, 1):
        _add_box(bm, sx * (w / 2.0 - t / 2.0), 0.0, h / 2.0, t, t, h)
    # Three horizontal bars
    for frac in (0.2, 0.5, 0.8):
        _add_box(bm, 0.0, 0.0, h * frac, w - t, t, t)
    # Base
    _add_box(bm, 0.0, 0.0, t / 2.0, w + 0.04, d, t)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_pillar_geometry(params):
    """A pillar: tall cylinder."""
    r, h = params["radius"], params["height"]
    mesh = bpy.data.meshes.new("pillar")
    obj = bpy.data.objects.new("pillar", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, h / 2.0, r, h, segments=20)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


# ── P-F batch 3: edge-case stress-test generators ────────────────

def _build_huge_table_geometry(params):
    """Max-size table: same as table but pushes footprint/height limits."""
    return _build_table_geometry(params)


def _build_tiny_stool_geometry(params):
    """Min-size stool: pushes the lower bound of stool parameters."""
    return _build_stool_geometry(params)


def _build_partition_geometry(params):
    """A very thin, tall, wide partition wall."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("partition")
    obj = bpy.data.objects.new("partition", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_tall_post_geometry(params):
    """A very tall, narrow post/column."""
    r, h = params["radius"], params["height"]
    mesh = bpy.data.meshes.new("tall_post")
    obj = bpy.data.objects.new("tall_post", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_cylinder(bm, 0.0, 0.0, h / 2.0, r, h, segments=12)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_wide_platform_geometry(params):
    """A very wide, flat platform."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("wide_platform")
    obj = bpy.data.objects.new("wide_platform", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_many_leg_table_geometry(params):
    """A table with 8 legs (part-count stressor)."""
    tw, td, tt = params["top_width"], params["top_depth"], params["top_thickness"]
    lh, lr = params["leg_height"], params["leg_radius"]
    leg = lr * 2.0
    mesh = bpy.data.meshes.new("many_leg_table")
    obj = bpy.data.objects.new("many_leg_table", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, lh + tt / 2.0, tw, td, tt)
    # 8 legs in a circle
    for i in range(8):
        angle = i * math.pi / 4.0
        lx = (tw / 2.0 - 0.08) * math.cos(angle)
        ly = (td / 2.0 - 0.08) * math.sin(angle)
        _add_box(bm, lx, ly, lh / 2.0, leg, leg, lh)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_ladder_geometry(params):
    """A ladder: two tall rails + many thin rungs (part-count + thinness)."""
    w, d, h = params["width"], params["depth"], params["height"]
    n = int(params["n_rungs"])
    rt = 0.03
    mesh = bpy.data.meshes.new("ladder")
    obj = bpy.data.objects.new("ladder", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    # Two rails
    for sx in (-1, 1):
        _add_box(bm, sx * (w / 2.0 - rt / 2.0), 0.0, h / 2.0, rt, d, h)
    # N rungs evenly distributed
    for i in range(n):
        t = (i + 0.5) / max(n, 1)
        _add_box(bm, 0.0, 0.0, h * t, w, d, rt)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_l_bench_geometry(params):
    """An L-shaped bench: two benches at 90° — asymmetric aspect stressor."""
    w, d, h = params["width"], params["depth"], params["height"]
    seat_t = 0.05
    leg_h = h - seat_t
    leg_s = 0.04
    mesh = bpy.data.meshes.new("L_bench")
    obj = bpy.data.objects.new("L_bench", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    # Main bench along X
    _add_box(bm, 0.0, -(d / 2.0 - d / 4.0), leg_h + seat_t / 2.0, w, d / 2.0, seat_t)
    # L-extension along Y (from the left end)
    ext_x = -(w / 2.0 - d / 4.0)
    _add_box(bm, ext_x, 0.0, leg_h + seat_t / 2.0, d / 2.0, d, seat_t)
    # Legs under main bench
    for sx in (-1, 1):
        _add_box(bm, sx * (w / 2.0 - 0.06), -(d / 2.0 - d / 4.0), leg_h / 2.0, leg_s, leg_s, leg_h)
    # Legs under L-extension
    for sy in (-1, 1):
        _add_box(bm, -(w / 2.0 - d / 4.0), sy * (d / 2.0 - 0.06), leg_h / 2.0, leg_s, leg_s, leg_h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_planter_geometry(params):
    """A planter: box body + slightly inset top rim."""
    w, d, h = params["width"], params["depth"], params["height"]
    mesh = bpy.data.meshes.new("planter")
    obj = bpy.data.objects.new("planter", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, d, h)
    # Rim: slightly wider box on top
    _add_box(bm, 0.0, 0.0, h - 0.03, w + 0.04, d + 0.04, 0.05)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_bench_geometry(params):
    """A bench: flat seat + 4 box legs."""
    w, d, h = params["width"], params["depth"], params["height"]
    seat_t = 0.05
    leg_h = h - seat_t
    leg_s = 0.04
    mesh = bpy.data.meshes.new("bench")
    obj = bpy.data.objects.new("bench", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, leg_h + seat_t / 2.0, w, d, seat_t)
    inset = 0.06
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box(bm, sx * (w / 2.0 - inset), sy * (d / 2.0 - inset),
                     leg_h / 2.0, leg_s, leg_s, leg_h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


_BUILDERS = {
    "table": _build_table_geometry,
    "chair": _build_chair_geometry,
    "shelf": _build_shelf_geometry,
    "cabinet": _build_cabinet_geometry,
    "humanoid": _build_humanoid_geometry,
    "rug": _build_rug_geometry,
    "painting": _build_painting_geometry,
    "key": _build_key_geometry,
    "book": _build_book_geometry,
    "cup": _build_cup_geometry,
    "gem": _build_gem_geometry,
    "bottle": _build_bottle_geometry,
    "scroll": _build_scroll_geometry,
    "coin-pouch": _build_coin_pouch_geometry,
    "candle": _build_candle_geometry,
    "dagger": _build_dagger_geometry,
    "ring": _build_ring_geometry,
    # P-F batch 1: themed-useful stress-test generators
    "barrel": _build_barrel_geometry,
    "crate": _build_crate_geometry,
    "chest": _build_chest_geometry,
    "stool": _build_stool_geometry,
    "bench": _build_bench_geometry,
    # P-F batch 2: remaining themed-useful generators
    "wardrobe": _build_wardrobe_geometry,
    "desk": _build_desk_geometry,
    "lantern": _build_lantern_geometry,
    "pot": _build_pot_geometry,
    "weapon-rack": _build_weapon_rack_geometry,
    "pillar": _build_pillar_geometry,
    "planter": _build_planter_geometry,
    # P-F batch 3: edge-case stress-test generators
    "huge_table": _build_huge_table_geometry,
    "tiny_stool": _build_tiny_stool_geometry,
    "partition": _build_partition_geometry,
    "tall_post": _build_tall_post_geometry,
    "wide_platform": _build_wide_platform_geometry,
    "many_leg_table": _build_many_leg_table_geometry,
    "ladder": _build_ladder_geometry,
    "L_bench": _build_l_bench_geometry,
}

_COLOR_BUILDERS = {
    "wood": _wood_color_nodes,
    "stone": _stone_color_nodes,
    "metal": _metal_color_nodes,
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

    Offset ~0.015 m, 2 segments; bakes into the exported mesh.  The offset is
    clamped to a fraction of the mesh's smallest extent so thin decor (a 0.02 m
    rug) isn't collapsed — without this a fixed 0.015 m bevel eats a 0.01 m
    half-thickness and breaks watertightness.
    """
    co = [v.co for v in mesh_data.vertices]
    if co:
        xs = [c.x for c in co]; ys = [c.y for c in co]; zs = [c.z for c in co]
        min_extent = min(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        offset = min(0.015, 0.4 * min_extent)
    else:
        offset = 0.015
    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    bmesh.ops.bevel(
        bm,
        geom=[e for e in bm.edges],
        offset=offset,
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


def apply_normal_bake(obj, nodes, links, bsdf, height_socket, image_name="baked_normal"):
    """Bake Cycles ``type="NORMAL"`` into a tangent-space normal image, then
    replace the live Bump with ``ImageTexture → NormalMap → BSDF.Normal`` so
    the glTF exporter writes a ``normalTexture``.

    The ``height_socket`` is the SAME scalar the family colour builder
    already computes to drive base colour:
      - wood  : ``wave.tex.Fac``       (band-stepped wood tones)
      - stone : ``voronoi.tex.Distance`` (cell-edge mottling)
      - metal : ``noise.tex.Fac``      (subtle streak)

    Slice 4 plumbing: live Bump while Cycles captures, then unwire and
    swap to the baked image.  Subtle strength (0.4) + Distance (0.05) →
    plausible first pass without dominating the look.  Non-Color
    colorspace on the baked image is critical — gamma warping the
    tangent vectors would make the surface look broken.
    """
    # Cycles CPU is required for baking; the helper is self-contained.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1

    # 1 ── Live Bump wiring: feed the height scalar → Bump → BSDF.Normal.
    # Subtle strength (0.2) + small Distance (0.05) → plausible first
    # pass that reads as surface micro-relief on all three families.
    bump = nodes.new("ShaderNodeBump")
    bump.location = (1000, -100)
    bump.inputs["Strength"].default_value = 0.2
    bump.inputs["Distance"].default_value = 0.05
    links.new(height_socket, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # 2 ── New image to bake into (tangent-space normal map).
    normal_image = bpy.data.images.new(
        image_name, width=1024, height=1024,
        alpha=False, float_buffer=False,
    )
    normal_image.file_format = "PNG"
    normal_image.colorspace_settings.name = "Non-Color"  # critical

    # 3 ── Image Texture node; must be the only SELECTED+ACTIVE bake target.
    normal_tex = nodes.new("ShaderNodeTexImage")
    normal_tex.image = normal_image
    normal_tex.location = (1000, -300)
    saved_select = {n.name: n.select for n in nodes}
    for n in nodes:
        n.select = False
    nodes.active = normal_tex
    normal_tex.select = True

    # 4 ── Make the target object active for the bake call.
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # 5 ── Bake.  Cycles emits the post-Bump tangent-space normal as RGB.
    # normal_space="TANGENT" is explicit (default is also TANGENT in modern
    # Blender, but pinning it removes a version-dependency foot-gun:
    # glTF's normalTexture is always tangent-space, so a bake in any
    # other space would silently produce a malformed asset).
    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_clear=True)

    # 6 ── Tear down the live Bump wiring.
    for link in list(bump.inputs["Height"].links):
        links.remove(link)
    for link in list(bump.outputs["Normal"].links):
        links.remove(link)
    nodes.remove(bump)

    # 7 ── Wire the baked image through a NormalMap node (required for
    #       the glTF exporter to emit a normalTexture).
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.location = (1000, -300)
    links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    # 8 ── Pack so the GLB carries the image without writing to disk.
    normal_image.pack()

    # Restore prior selection state — apply_material's later steps
    # re-set nodes.active to their own bake target.
    for n in nodes:
        n.select = False
    for name, was in saved_select.items():
        if was:
            try:
                nodes[name].select = True
            except KeyError:
                pass
    nodes.active = None


def apply_material(mesh, material_name, seed=0.0):
    """Create a procedural wood material with shader nodes, bake the base colour
    to an image texture with Cycles-CPU, then wire the baked texture into the
    Principled BSDF Base Color so the glTF exporter writes a baseColorTexture.

    Material colours and roughness are driven by foundry/materials.py.

    Shader recipe (anti-procedural-tell):
      - Object-space coordinates through an anisotropic Mapping so grain runs
        along the asset's long axis.
      - Noise-based coordinate warp BEFORE the wave is measured (breaks the
        parallel-stripe corduroy read).
      - CONSTANT ColorRamp for stepped, painted-band wood tones.
      - AO baked INTO baseColor via MixRGB(MULTIPLY) to ground the asset.
      - seed offsets the Mapping Location so two same-material assets are not
        pixel-identical."""
    # Find the object that owns this mesh.
    obj = _find_object_for_mesh(mesh)
    if obj is None:
        raise RuntimeError("Could not find object for the table mesh")

    # ── Look up the material palette entry ────────────────────
    mat_info = MATERIAL_PALETTE.get(material_name, MATERIAL_PALETTE["worn_oak"])
    roughness = mat_info.get("roughness", 0.65)

    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    mesh.materials.append(mat)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes; we rebuild the shader tree.
    nodes.clear()

    # ── Shared tail: BSDF + material output ──────────────────
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = mat_info.get("metallic", 0.0)
    bsdf.location = (800, 300)

    material_output = nodes.new("ShaderNodeOutputMaterial")
    material_output.location = (1200, 300)

    # ── Dispatch to the family-specific colour subgraph ─────
    family = mat_info.get("family", "wood")
    builder = _COLOR_BUILDERS.get(family)
    if builder is None:
        raise ValueError(
            f"unknown material family: {family!r} (known: {sorted(_COLOR_BUILDERS)})"
        )
    # Slice 4: builders now also expose a scalar height for the NORMAL bake.
    color_socket, height_socket = builder(nodes, links, mat_info, seed)

    # ── Ambient Occlusion (grounds the asset, baked INTO baseColor) ─
    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.location = (200, 100)
    ao.inputs["Distance"].default_value = 0.2

    # MixRGB(MULTIPLY): albedo × AO → grounded base colour.
    mix_ao = nodes.new("ShaderNodeMixRGB")
    mix_ao.blend_type = "MULTIPLY"
    mix_ao.location = (500, 300)
    mix_ao.inputs["Fac"].default_value = 1.0  # full mix

    # Wire: color_socket → mix_ao(Color1), AO → mix_ao(Color2)
    links.new(color_socket, mix_ao.inputs["Color1"])
    links.new(ao.outputs["Color"], mix_ao.inputs["Color2"])

    # Wire shared: mix_ao → bsdf → material_output
    links.new(mix_ao.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], material_output.inputs["Surface"])

    # ── Slice 4: Bake the NORMAL pass before the baseColor pass. ─
    # See apply_normal_bake() for the rationale (Bump → bake → swap to
    # image→NormalMap→BSDF.Normal so glTF writes a normalTexture).
    apply_normal_bake(obj, nodes, links, bsdf, height_socket)

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
    bake_tex.location = (800, 0)
    # Select it as the active bake target.
    nodes.active = bake_tex
    bake_tex.select = True

    # Switch to Cycles CPU for baking.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1  # fast bake; quality is fine for a 1K texture

    # Temporarily replace the Principled BSDF with an Emission shader so
    # the EMIT bake captures exactly the grounded base colour (albedo × AO).
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (1000, 0)
    links.new(mix_ao.outputs["Color"], emit.inputs["Color"])
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

    # ── Slice 5: Bake the metallicRoughnessTexture pass. ────────────
    # Packs (R=0, G=roughness_modulated, B=metallic_factor, A=1) so the
    # glTF exporter emits a single metallicRoughnessTexture entry.
    # See apply_roughness_bake() for the rationale.
    apply_roughness_bake(
        obj, nodes, links, bsdf,
        baseline_roughness=roughness,
        metallic_factor=float(mat_info.get("metallic", 0.0)),
    )


def _derive_entropy_seed(spec: dict) -> int:
    """Derive a deterministic 32-bit integer seed from the spec.

    Uses stable hash (SHA-256), not Python's hash(), so the seed is
    reproducible across Python versions and processes.
    """
    key = f"{spec.get('asset_id', 'table')}_{spec.get('material', 'default')}"
    h = hashlib.sha256(key.encode()).digest()
    return struct.unpack('>I', h[:4])[0]


def _derive_material_offset(spec: dict) -> float:
    """Derive a deterministic float in [0, 10) from the spec for the
    material Mapping Location offset (anti-pixel-identical guarantee).
    """
    key = f"{spec.get('asset_id', 'table')}_{spec.get('material', 'default')}"
    h = hashlib.sha256(key.encode()).digest()
    return (struct.unpack('>I', h[4:8])[0] / (2**32)) * 10.0


def apply_entropy(mesh_data, age, seed):
    """Apply bounded, seeded deformations that scale with *age* to break
    the CAD-perfect silhouette.

    Deformations (all magnitudes capped for gate safety):
      - Per-vertex displacement along normals (sub-mm noise).
      - Global Z-twist proportional to height.
      - Tabletop sag: centre vertices pulled down.
      - Leg taper: bottom of each leg narrowed toward its centre.
      - Leg splay: bottom of each leg shifted horizontally.

    The mesh is deformed BEFORE bevelling (call order enforced in main()).
    Deterministic: identical (spec, age, seed) → byte-identical mesh.
    """
    rng = random.Random(seed)

    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    bm.verts.ensure_lookup_table()

    z_vals = [v.co.z for v in bm.verts]
    min_z = min(z_vals)
    max_z = max(z_vals)
    z_range = max(max_z - min_z, 0.01)
    mid_z = sum(z_vals) / len(z_vals)

    # ── Magnitude caps (all well inside gate +15 % tolerance) ─
    max_displace = 0.002 * age   #  2 mm surface noise at age=1
    max_twist = 0.004 * age      # ~0.2° at age=1
    max_sag = 0.012 * age        # 12 mm centre droop at age=1
    max_taper = 0.12 * age       # 12 % of distance to leg centre at age=1
    max_splay = 0.006 * age      #  6 mm leg-base shift at age=1

    # ── 1. Per-vertex displacement along normals ─────────────
    for v in bm.verts:
        offset = (rng.random() - 0.5) * 2 * max_displace
        v.co += v.normal * offset

    # ── 2. Global Z-twist (amount ∝ height) ──────────────────
    twist = (rng.random() - 0.5) * 2 * max_twist
    for v in bm.verts:
        t = (v.co.z - min_z) / z_range
        angle = twist * t
        c, s = math.cos(angle), math.sin(angle)
        v.co.x, v.co.y = v.co.x * c - v.co.y * s, v.co.x * s + v.co.y * c

    # ── 3. Top sag ───────────────────────────────────────────
    top_verts = [v for v in bm.verts if v.co.z > mid_z]
    if top_verts:
        max_top_xy = max(math.hypot(v.co.x, v.co.y) for v in top_verts)
        if max_top_xy > 0.001:
            for v in top_verts:
                dist = math.hypot(v.co.x, v.co.y)
                sag = max(0.0, 1.0 - dist / max_top_xy)
                v.co.z -= sag * max_sag * rng.uniform(0.8, 1.0)

    # ── 4. Leg taper + splay ─────────────────────────────────
    leg_verts = [v for v in bm.verts if v.co.z < mid_z]
    if leg_verts:
        # Cluster into 4 quadrants
        quads = [[], [], [], []]  # ++, -+, --, +-
        for v in leg_verts:
            if v.co.x >= 0 and v.co.y >= 0:
                quads[0].append(v)
            elif v.co.x < 0 and v.co.y >= 0:
                quads[1].append(v)
            elif v.co.x < 0 and v.co.y < 0:
                quads[2].append(v)
            else:
                quads[3].append(v)

        for quad in quads:
            if len(quad) < 4:
                continue
            cx = sum(v.co.x for v in quad) / len(quad)
            cy = sum(v.co.y for v in quad) / len(quad)
            leg_bottom = min(v.co.z for v in quad)
            leg_z_range = max(mid_z - leg_bottom, 0.01)

            splay_angle = rng.random() * 2 * math.pi
            splay_dx = math.cos(splay_angle) * max_splay
            splay_dy = math.sin(splay_angle) * max_splay

            for v in quad:
                t = (mid_z - v.co.z) / leg_z_range  # 0 at top, 1 at bottom
                # Taper toward leg centre
                v.co.x += (cx - v.co.x) * t * max_taper
                v.co.y += (cy - v.co.y) * t * max_taper
                # Splay at base
                v.co.x += splay_dx * t
                v.co.y += splay_dy * t

    bm.to_mesh(mesh_data)
    bm.free()


def main():
    args = _argv()
    spec_path, out_glb = args[0], args[1]
    spec = json.load(open(spec_path, "r", encoding="utf-8"))

    # Derive deterministic seeds from the spec.
    entropy_seed = _derive_entropy_seed(spec)
    material_offset = _derive_material_offset(spec)
    age = float(spec.get("age", 0.15))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = build_geometry(spec)
    apply_entropy(mesh, age, entropy_seed)
    apply_bevel(mesh)
    assign_uvs(mesh)
    apply_material(mesh, spec.get("material", "default"), seed=material_offset)

    bpy.ops.export_scene.gltf(
        filepath=out_glb, export_format="GLB", use_selection=False
    )


main()
