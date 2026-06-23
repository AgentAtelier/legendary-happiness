"""Blender headless Cycles (HIP) lighting bake.

    blender -b --python bake_lighting.py -- <scene_desc.json> <out_dir> <tier>

Assembles the scene (GLB placements, or primitives for self-contained tests),
adds the sun + sky from the desc, lightmap-unwraps a UV2, and bakes on the GPU:
  tier 1 → DIFFUSE indirect → vertex colors (realtime sun keeps direct + shadows)
  tier 2 → COMBINED → vertex colors (fully static)
Exports <out_dir>/baked.glb with the baked colors. Deterministic (fixed seed,
denoise off).
"""

import json
import math
import os
import sys

import bpy
import mathutils


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    return argv[0], argv[1]


def _enable_hip(samples: int):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "HIP"
        prefs.refresh_devices()
        for d in prefs.devices:
            d.use = (d.type == "HIP")  # GPU device(s) only, skip CPU
    except Exception as e:
        print(f"[bake] HIP enable failed ({e}); falling back to CPU")
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        sc.cycles.device = "GPU"
    except Exception:
        sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.seed = 0
    sc.cycles.use_denoising = False  # determinism
    used = [d.name for d in prefs.devices if d.use]
    print(f"[bake] cycles.device={sc.cycles.device} devices_on={used}")


def _ensure_material(obj):
    if not obj.data.materials:
        m = bpy.data.materials.new(obj.name + "_m")
        m.use_nodes = True
        obj.data.materials.append(m)


def _add_primitive(p):
    kind = p.get("primitive", "box")
    if kind == "plane":
        bpy.ops.mesh.primitive_plane_add(size=p.get("size", 8.0))
    else:
        bpy.ops.mesh.primitive_cube_add(size=p.get("size", 1.0))
    obj = bpy.context.active_object
    loc = p.get("location", [0, 0, 0])
    obj.location = (loc[0], loc[1], loc[2])
    # a few subdivisions so vertex-colour GI has somewhere to land
    if p.get("subdivide", 3):
        import bmesh
        bm = bmesh.new(); bm.from_mesh(obj.data)
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=p.get("subdivide", 3),
                                  use_grid_fill=True)
        bm.to_mesh(obj.data); bm.free()
    return obj


def _add_glb(p):
    bpy.ops.import_scene.gltf(filepath=p["glb"])
    obj = bpy.context.active_object
    t = p.get("transform")
    if t and len(t) == 12:
        b = mathutils.Matrix(((t[0], t[1], t[2], t[9]),
                              (t[3], t[4], t[5], t[10]),
                              (t[6], t[7], t[8], t[11]),
                              (0, 0, 0, 1)))
        obj.matrix_world = b
    return obj


def main():
    path, out_dir = _args()
    desc = json.load(open(path))
    tier = int(desc.get("tier", 1))
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    _enable_hip(int(desc.get("samples", 16)))

    # World / sky
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    sky = desc.get("sky", {})
    top = sky.get("top", [0.5, 0.6, 0.8])
    bg.inputs[0].default_value = (top[0], top[1], top[2], 1.0)
    bg.inputs[1].default_value = float(sky.get("ambient_energy", 0.5))

    # Sun
    sd = desc.get("sun", {})
    ld = bpy.data.lights.new("Sun", type="SUN")
    ld.energy = float(sd.get("energy", 1.0)) * 3.0
    col = sd.get("color", [1, 1, 1])
    ld.color = (col[0], col[1], col[2])
    sun = bpy.data.objects.new("Sun", ld)
    bpy.context.collection.objects.link(sun)
    direction = mathutils.Vector(sd.get("direction", [0.3, -1.0, 0.4])).normalized()
    sun.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Interior emitters (hearth/torch/candle) so GI bounces warm interior light,
    # not just sky. POINT lamps at the planned positions; wattage scales the plan's
    # relative energy. (Same desc coordinate space as placements.)
    for li in desc.get("interior_lights", []):
        il = bpy.data.lights.new(str(li.get("type", "point")), type="POINT")
        il.energy = float(li.get("energy", 1.0)) * 60.0
        ic = li.get("color", [1, 1, 1])
        il.color = (ic[0], ic[1], ic[2])
        il.shadow_soft_size = 0.15
        iob = bpy.data.objects.new(il.name, il)
        bpy.context.collection.objects.link(iob)
        iob.location = tuple(li.get("pos", [0, 0, 0]))

    # Objects + UV2 + a colour attribute to bake into
    objs = []
    for p in desc.get("placements", []):
        obj = _add_glb(p) if (p.get("glb") and os.path.exists(p["glb"])) else _add_primitive(p)
        _ensure_material(obj)
        me = obj.data
        if not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        if len(me.uv_layers) < 2:
            me.uv_layers.new(name="UV2")
        me.uv_layers.active_index = len(me.uv_layers) - 1
        # lightmap-pack the active (UV2) layer
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.uv.lightmap_pack(PREF_CONTEXT="ALL_FACES", PREF_MARGIN_DIV=0.2)
        except Exception:
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        if "bake_col" not in me.color_attributes:
            me.color_attributes.new(name="bake_col", type="FLOAT_COLOR", domain="POINT")
        me.color_attributes.active_color = me.color_attributes["bake_col"]
        objs.append(obj)
        obj.select_set(False)

    # Bake into vertex colours
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bake = bpy.context.scene.render.bake
    bake.target = "VERTEX_COLORS"
    if int(tier) >= 2:
        bpy.ops.object.bake(type="COMBINED")
    else:
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"INDIRECT"})

    # Keep ONLY the baked attribute so it becomes COLOR_0 (consumers read the
    # first set; a stray default attribute would otherwise mask the bake).
    for o in objs:
        cas = o.data.color_attributes
        for name in [c.name for c in cas if c.name != "bake_col"]:
            cas.remove(cas[name])
        idx = list(cas).index(cas["bake_col"])
        cas.active_color_index = idx
        cas.render_color_index = idx  # glTF COLOR_0 = the render-active color

    # diagnostics: did the bake write the colour attribute?
    ca = objs[0].data.color_attributes.get("bake_col")
    if ca and len(ca.data):
        sample = [round(c, 3) for c in ca.data[0].color[:3]]
        vals = [tuple(round(v.color[k], 3) for k in range(3)) for v in ca.data]
        uniq = len(set(vals))
        print(f"[bake] bake_col first={sample} distinct_values={uniq}/{len(vals)}")

    out = os.path.join(out_dir, "baked.glb")
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", export_vertex_color="ACTIVE",
    )
    print(f"[bake] wrote {out}")


if __name__ == "__main__":
    main()
