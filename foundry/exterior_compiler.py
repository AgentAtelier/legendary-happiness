"""foundry.exterior_compiler — emit the exterior-layer Godot .tscn from an ExteriorPlan.

The RICH exterior path (terrain heightfield GLB + biome flora + open sky + a
player spawn outside), kept in its own module so it doesn't collide with the
CB-7 *flat* outdoor code in ``scene_compiler``. Flora is instanced per scatter
placement (simple + correct; MultiMesh batching is a later optimization). The
building + interior fuse is a follow-up; this emits the standalone outdoor layer.

Pure string emission — deterministic, unit-testable without Godot.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List

from exterior_planner import ExteriorPlan

# Sun basis (a fixed pleasant angle); biome sets its energy.
_SUN_XFORM = "0.707107, -0.5, 0.5, 0, 0.707107, 0.707107, -0.707107, -0.5, 0.5"


def _transform3d(x: float, y: float, z: float, yaw: float = 0.0, scale: float = 1.0) -> str:
    """A Godot Transform3D string: yaw about Y + uniform scale + translation."""
    c, s = math.cos(yaw), math.sin(yaw)
    # X axis, Y axis, Z axis (each * scale), then origin.
    xx, xy, xz = c * scale, 0.0, -s * scale
    yx, yy, yz = 0.0, scale, 0.0
    zx, zy, zz = s * scale, 0.0, c * scale
    vals = [xx, xy, xz, yx, yy, yz, zx, zy, zz, x, y, z]
    return "Transform3D(" + ", ".join(f"{v:.4f}" for v in vals) + ")"


def _default_interior_plan(ext_plan: ExteriorPlan, *, material: str = "worn_oak") -> dict:
    """A deterministic interior plan sized to the BUILDING interior (inset for
    walls). The LLM RoomPlanner can override this by passing its own plan."""
    b = ext_plan.building
    w = max(2.0, b["half_w"] * 2.0 - 0.6)
    d = max(2.0, b["half_d"] * 2.0 - 0.6)
    props = [
        {"category": "table", "count": 1, "material": material},
        {"category": "chair", "count": 2, "material": material},
    ]
    return {"room_size": {"w": w, "d": d}, "props": props}


def compile_exterior_build(brief: dict, seed: int, *, plan: dict | None = None,
                           npc_count: int = 1, lighting_tier: int | None = None,
                           baker=None, cache_root=None,
                           assets_subdir: str = "assets") -> str:
    """Live-assembly: Brief → ExteriorPlanner + (RoomPlanner|default) interior →
    one playable exterior ``.tscn`` (terrain + flora + building + furnished interior).

    The interior manifest is SOURCED LIVE from ``room_layout.layout_room`` (sized to
    the building). ``lighting_tier`` (else ``brief["lighting_tier"]``): 0 realtime
    (individual instances); 1/2 bake the static scene's GI in Blender and emit a
    single baked GLB. Any bake failure falls back to realtime.
    """
    from exterior_planner import plan_exterior
    from room_layout import layout_room

    ext_plan = plan_exterior(brief, seed)
    if plan is None:
        plan = _default_interior_plan(ext_plan)
    manifest, _meta, _decisions = layout_room(plan, seed=seed, npc_count=npc_count)

    tier = int(lighting_tier if lighting_tier is not None else brief.get("lighting_tier", 0) or 0)
    if tier <= 0:
        return emit_exterior_layer(ext_plan, interior_manifest=manifest)

    import lighting_bake
    scene_desc = _scene_desc_from(ext_plan, manifest, tier, assets_subdir)
    result = lighting_bake.bake_scene(scene_desc, baker=baker or _blender_baker,
                                      cache_root=cache_root)
    if result.get("status") in ("baked", "cached") and result.get("artifacts"):
        res = f"res://{assets_subdir}/{os.path.basename(result['artifacts'][0])}"
        return emit_baked_scene(ext_plan, res, assets_subdir=assets_subdir)
    return emit_exterior_layer(ext_plan, interior_manifest=manifest)  # realtime fallback


def _xform_list(x: float, y: float, z: float, yaw: float = 0.0, scale: float = 1.0) -> list:
    c, s = math.cos(yaw), math.sin(yaw)
    return [c * scale, 0.0, -s * scale, 0.0, scale, 0.0, s * scale, 0.0, c * scale, x, y, z]


def _scene_desc_from(ext_plan: ExteriorPlan, manifest: list, tier: int,
                     assets_subdir: str) -> dict:
    """Assemble the bake contract from the plan + interior manifest + biome lights."""
    atm = ext_plan.biome.get("atmosphere", {})
    placements = [{"glb": f"{assets_subdir}/terrain.glb", "transform": _xform_list(0, 0, 0),
                   "static": True}]
    for p in ext_plan.scatter_placements:
        placements.append({"glb": f"{assets_subdir}/{p['category']}.glb",
                           "transform": _xform_list(p["x"], p["y"], p["z"],
                                                    p.get("yaw", 0.0), p.get("scale", 1.0)),
                           "static": True})
    py = ext_plan.building["pad_height"]
    for e in manifest:
        placements.append({"glb": f"{assets_subdir}/{e['category']}_{e['material']}.glb",
                           "transform": _xform_list(e["x"], py + e.get("y", 0.0), e["z"],
                                                    e.get("yaw", 0.0)),
                           "static": True})
    return {
        "placements": placements,
        "sun": {"direction": list(atm.get("sun_dir", [0.3, -0.6, -0.7])),
                "energy": float(atm.get("sun_energy", 1.1)),
                "color": list(atm.get("sun_color", [1.0, 0.97, 0.92]))},
        "sky": {"top": list(atm.get("sky_tint", [0.6, 0.7, 0.85])),
                "horizon": list(atm.get("fog_color", [0.6, 0.6, 0.6])),
                "ambient_energy": float(atm.get("ambient_energy", 0.5))},
        "tier": tier, "samples": 96 if tier >= 2 else 24,
    }


def emit_baked_scene(ext_plan: ExteriorPlan, baked_glb_res: str, *,
                     assets_subdir: str = "assets") -> str:
    """Emit a ``.tscn`` instancing the single BAKED scene GLB (static geometry +
    baked-GI vertex colors) + a realtime sun (tier-1 direct) + sky + player spawn."""
    atm = ext_plan.biome.get("atmosphere", {})
    fog_c = atm.get("fog_color", (0.66, 0.72, 0.7))
    sun_e = atm.get("sun_energy", 1.1)
    sky_t = atm.get("sky_tint", (0.62, 0.74, 0.88))
    ext = [f'[ext_resource type="PackedScene" path="{baked_glb_res}" id="1_baked"]']
    subs = [
        '[sub_resource type="ProceduralSkyMaterial" id="sky_mat"]',
        f"sky_top_color = Color({sky_t[0]}, {sky_t[1]}, {sky_t[2]}, 1)",
        f"sky_horizon_color = Color({fog_c[0]}, {fog_c[1]}, {fog_c[2]}, 1)",
        '[sub_resource type="Sky" id="sky"]',
        'sky_material = SubResource("sky_mat")',
        '[sub_resource type="Environment" id="world_env"]',
        "background_mode = 2",
        'sky = SubResource("sky")',
        "ambient_light_source = 3",
        "tonemap_mode = 3",
    ]
    n_sub = sum(1 for ln in subs if ln.startswith("[sub_resource"))
    header = [f"[gd_scene load_steps={len(ext) + n_sub + 1} format=3]"]
    sp = ext_plan.spawn
    spawn_y = ext_plan.building["pad_height"]
    nodes = [
        '[node name="Root" type="Node3D"]',
        '[node name="WorldEnvironment" type="WorldEnvironment" parent="."]',
        'environment = SubResource("world_env")',
        '[node name="Sun" type="DirectionalLight3D" parent="."]',
        f"transform = Transform3D({_SUN_XFORM}, 0, 20, 0)",
        f"light_energy = {sun_e}",
        "shadow_enabled = true",
        '[node name="BakedScene" parent="." instance=ExtResource("1_baked")]',
        '[node name="PlayerSpawn" type="Marker3D" parent="."]',
        "transform = " + _transform3d(sp["x"], spawn_y, sp["z"], sp.get("yaw", 0.0)),
    ]
    return "\n".join(header + [""] + ext + [""] + subs + [""] + nodes) + "\n"


def _blender_baker(scene_desc: dict, out_dir: str) -> list:
    """The real baker: shell out to the headless Blender Cycles bake."""
    import json
    import shutil
    import subprocess

    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("blender not available for bake")
    bake_py = os.path.join(os.path.dirname(__file__), "blender", "bake_lighting.py")
    desc_p = os.path.join(out_dir, "scene_desc.json")
    with open(desc_p, "w") as f:
        json.dump(scene_desc, f)
    r = subprocess.run([blender, "-b", "--python", bake_py, "--", desc_p, out_dir],
                       capture_output=True, text=True, timeout=1800)
    out = os.path.join(out_dir, "baked.glb")
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"bake failed rc={r.returncode}: {(r.stderr or '')[-300:]}")
    return [out]


def _emit_building(plan: ExteriorPlan):
    """The building shell on the pad: 4 walls (a door gap on the door side) + a
    flat roof, each a StaticBody3D with BoxMesh + BoxShape3D collision so the
    player is blocked by walls and enters through the gap. Returns
    ``(sub_resource_lines, node_lines)``.
    """
    b = plan.building
    hw, hd = b["half_w"], b["half_d"]
    py = b["pad_height"]
    wt, wh, door_w = 0.2, 2.6, 1.4
    full_w, full_d = hw * 2.0, hd * 2.0
    subs: List[str] = []
    nodes: List[str] = []
    n = [0]

    def box_body(name, cx, cz, sx, sz, h=wh, cy=None):
        cy = (py + h / 2.0) if cy is None else cy
        mid, cid = f"bm_{n[0]}", f"bs_{n[0]}"
        n[0] += 1
        subs.append(f'[sub_resource type="BoxMesh" id="{mid}"]')
        subs.append(f"size = Vector3({sx:.3f}, {h:.3f}, {sz:.3f})")
        subs.append(f'[sub_resource type="BoxShape3D" id="{cid}"]')
        subs.append(f"size = Vector3({sx:.3f}, {h:.3f}, {sz:.3f})")
        nodes.append(f'[node name="{name}" type="StaticBody3D" parent="."]')
        nodes.append("transform = " + _transform3d(cx, cy, cz))
        nodes.append(f'[node name="{name}_mesh" type="MeshInstance3D" parent="{name}"]')
        nodes.append(f'mesh = SubResource("{mid}")')
        nodes.append(f'[node name="{name}_col" type="CollisionShape3D" parent="{name}"]')
        nodes.append(f'shape = SubResource("{cid}")')

    box_body("WallBack", 0.0, -hd, full_w, wt)     # -Z
    box_body("WallE", hw, 0.0, wt, full_d)          # +X
    box_body("WallW", -hw, 0.0, wt, full_d)         # -X
    seg = (full_w - door_w) / 2.0                   # +Z door side: two segments
    box_body("WallFrontL", -(door_w / 2.0 + seg / 2.0), hd, seg, wt)
    box_body("WallFrontR", (door_w / 2.0 + seg / 2.0), hd, seg, wt)
    box_body("Roof", 0.0, 0.0, full_w + 0.4, full_d + 0.4, h=0.2, cy=py + wh + 0.1)
    return subs, nodes


def emit_exterior_layer(plan: ExteriorPlan, interior_manifest=None, *,
                        assets_subdir: str = "assets") -> str:
    """Return the full exterior-layer ``.tscn`` text for *plan*.

    *interior_manifest* (optional): placed props/NPCs ``{id, category, material,
    x, y, z, yaw}`` emitted INSIDE the building, on the pad floor.
    """
    biome = plan.biome
    atm = biome.get("atmosphere", {})
    fog_c = atm.get("fog_color", (0.66, 0.72, 0.7))
    fog_d = atm.get("fog_density", 0.01)
    sun_e = atm.get("sun_energy", 1.1)
    sky_t = atm.get("sky_tint", (0.62, 0.74, 0.88))

    # ── ext_resources: terrain + each unique flora category ───────
    flora_cats = sorted({p["category"] for p in plan.scatter_placements})
    ext_ids: Dict[str, str] = {"terrain": "1_terrain"}
    ext_lines: List[str] = [
        f'[ext_resource type="PackedScene" path="res://{assets_subdir}/terrain.glb" id="1_terrain"]'
    ]
    for i, cat in enumerate(flora_cats, start=2):
        rid = f"{i}_{cat}"
        ext_ids[cat] = rid
        ext_lines.append(
            f'[ext_resource type="PackedScene" path="res://{assets_subdir}/{cat}.glb" id="{rid}"]'
        )

    # interior props (INSIDE the building): one PackedScene per (category, material)
    interior = interior_manifest or []
    interior_ids: Dict[str, str] = {}
    nxt = len(flora_cats) + 2
    for e in interior:
        key = f"{e['category']}_{e['material']}"
        if key not in interior_ids:
            rid = f"{nxt}_{key}"
            interior_ids[key] = rid
            ext_lines.append(
                f'[ext_resource type="PackedScene" path="res://{assets_subdir}/{key}.glb" id="{rid}"]'
            )
            nxt += 1

    # ── sub_resources: procedural open sky + biome environment ────
    sub_lines = [
        '[sub_resource type="ProceduralSkyMaterial" id="sky_mat"]',
        f"sky_top_color = Color({sky_t[0]}, {sky_t[1]}, {sky_t[2]}, 1)",
        f"sky_horizon_color = Color({fog_c[0]}, {fog_c[1]}, {fog_c[2]}, 1)",
        '[sub_resource type="Sky" id="sky"]',
        'sky_material = SubResource("sky_mat")',
        '[sub_resource type="Environment" id="world_env"]',
        "background_mode = 2",
        'sky = SubResource("sky")',
        "ambient_light_source = 3",
        "fog_enabled = true",
        f"fog_density = {fog_d}",
        f"fog_light_color = Color({fog_c[0]}, {fog_c[1]}, {fog_c[2]}, 1)",
        "tonemap_mode = 3",
    ]
    building_subs, building_nodes = _emit_building(plan)
    sub_lines += building_subs

    n_sub = sum(1 for ln in sub_lines if ln.startswith("[sub_resource"))
    load_steps = len(ext_lines) + n_sub + 1
    header = [f"[gd_scene load_steps={load_steps} format=3]"]

    # ── nodes ─────────────────────────────────────────────────────
    nodes = [
        '[node name="Root" type="Node3D"]',
        '[node name="WorldEnvironment" type="WorldEnvironment" parent="."]',
        'environment = SubResource("world_env")',
        '[node name="Sun" type="DirectionalLight3D" parent="."]',
        f"transform = Transform3D({_SUN_XFORM}, 0, 20, 0)",
        f"light_energy = {sun_e}",
        "shadow_enabled = true",
        '[node name="Terrain" parent="." instance=ExtResource("1_terrain")]',
    ]
    nodes += building_nodes
    for i, p in enumerate(plan.scatter_placements):
        rid = ext_ids[p["category"]]
        nodes.append(f'[node name="flora_{i}" parent="." instance=ExtResource("{rid}")]')
        nodes.append(
            "transform = " + _transform3d(p["x"], p["y"], p["z"], p.get("yaw", 0.0), p.get("scale", 1.0))
        )

    # interior props/NPCs, on the building's pad floor (y = pad_height + offset)
    py = plan.building["pad_height"]
    for j, e in enumerate(interior):
        rid = interior_ids[f"{e['category']}_{e['material']}"]
        eid = e.get("id", f"prop_{j}")
        nodes.append(f'[node name="{eid}" parent="." instance=ExtResource("{rid}")]')
        nodes.append(
            "transform = " + _transform3d(e["x"], py + e.get("y", 0.0), e["z"], e.get("yaw", 0.0))
        )

    # Player spawn marker (outside, on the door side, at terrain height there).
    sp = plan.spawn
    spawn_y = plan.building["pad_height"]
    nodes.append('[node name="PlayerSpawn" type="Marker3D" parent="."]')
    nodes.append("transform = " + _transform3d(sp["x"], spawn_y, sp["z"], sp.get("yaw", 0.0)))

    return "\n".join(header + [""] + ext_lines + [""] + sub_lines + [""] + nodes) + "\n"
