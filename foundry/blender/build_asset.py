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

    return ramp.outputs["Color"]


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

    # Wire mix → ramp (using combined texture colour as fac)
    # Convert colour to greyscale fac via luminance proxy: use Fac of mix
    # We'll use the voronoi Fac output as a single-channel driver.
    # Actually, wire the voronoi Fac as the ramp driver (single channel).
    links.new(voronoi.outputs["Fac"], ramp.inputs["Fac"])

    return ramp.outputs["Color"]


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

    return ramp.outputs["Color"]


_BUILDERS = {
    "table": _build_table_geometry,
    "chair": _build_chair_geometry,
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
    color_socket = builder(nodes, links, mat_info, seed)

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
