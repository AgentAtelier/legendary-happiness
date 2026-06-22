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


def emit_exterior_layer(plan: ExteriorPlan, *, assets_subdir: str = "assets") -> str:
    """Return the full exterior-layer ``.tscn`` text for *plan*."""
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

    load_steps = len(ext_lines) + 4  # 3 sub_resources + 1
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
    for i, p in enumerate(plan.scatter_placements):
        rid = ext_ids[p["category"]]
        nodes.append(f'[node name="flora_{i}" parent="." instance=ExtResource("{rid}")]')
        nodes.append(
            "transform = " + _transform3d(p["x"], p["y"], p["z"], p.get("yaw", 0.0), p.get("scale", 1.0))
        )

    # Player spawn marker (outside, on the door side, at terrain height there).
    sp = plan.spawn
    spawn_y = plan.building["pad_height"]
    nodes.append('[node name="PlayerSpawn" type="Marker3D" parent="."]')
    nodes.append("transform = " + _transform3d(sp["x"], spawn_y, sp["z"], sp.get("yaw", 0.0)))

    return "\n".join(header + [""] + ext_lines + [""] + sub_lines + [""] + nodes) + "\n"
