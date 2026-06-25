"""Scene compiler — deterministic spec→Godot .tscn generator.

Turns a quest spec + placed-entity manifest into a runnable Godot
scene (.tscn) for the rpg project, wiring everything by a fixed
tag→behaviour table.  The LLM never appears here.

Mirrors ``foundry/publish.py`` for path/resource handling.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import navmesh
from _constants import _SUN_BASIS_INTERIOR_TUPLE as _SUN_BASIS
from category_registry import COLLISION_SIZES

# P12 (AUDIT-05 de-dup): room_shell.ensure_room_shell is no longer
# called from ``compile_scene`` — the call lives in ``scaffold.py``
# (the cache-owning site).  The module is still imported by tests
# directly (``import room_shell``), so we don't re-export here.
from comp_tags import (
    _NPC_BODY_CATEGORY,
    _NPC_BODY_MATERIAL,
    _SHELL_NODES,
    _SHELL_SCRIPTS,
    _TAG_TABLE,
)
from lighting_resolve import _resolve_lighting
from material_classes import CLASSES, class_for
from placement import (
    _find_open_npc_positions,
    _get_prop_footprints,
    _guard_player_spawn,
    _resolve_prop_overlaps,
    read_asset_aabb_min_y,
    rest_offset,
)
from scene_data import write_sidecar_data
from tscn_writer import (
    ext_resource,
    fmt_float,
    node_header,
    sub_resource_header,
    transform3d,
)

# ── Manifest entry shape ─────────────────────────────────────────

class PlacedEntity(TypedDict, total=False):
    id: str
    category: str       # "table" | "shelf" | "chair" | "cabinet"
    material: str        # "worn_oak" | "rough_granite" | ...
    wear: float          # 0.15 .. 1.0
    x: float             # world position
    y: float
    z: float
    surface: str         # "underlay" for rugs (skip AABB separation)
    decor: bool          # True for decoration (no collider, no pickup tag)


# ── B3: Per-item metadata emitter ──────────────────────────────
# Reads use_verb/weight/durability/openable from category_registry
# and emits _forge_* metadata on compiled props.

def _b3_emit_item_metadata(lines: list[str], category: str) -> None:
    """Emit B3 per-item metadata lines for *category* from the registry."""
    from category_registry import REGISTRY
    entry = REGISTRY.get(category, {})
    uv = entry.get("use_verb")
    if uv:
        lines.append(f'metadata/_forge_use_verb = "{uv}"')
    wt = entry.get("weight")
    if wt is not None:
        lines.append(f'metadata/_forge_weight = {float(wt)}')
    dur = entry.get("durability")
    if dur is not None:
        lines.append(f'metadata/_forge_durability = {int(dur)}')
    if entry.get("openable"):
        lines.append('metadata/_forge_openable = "true"')
        # CB-2: empty contents by default (container.gd reads this to spawn items)
        lines.append('metadata/_forge_contents = ""')
    # CB-2: place-on-surface — furniture with a top surface for placing items
    if entry.get("furniture_top_y") is not None:
        lines.append('metadata/_forge_surface_tag = "place"')
        lines.append(f'metadata/_forge_surface_y = {float(entry["furniture_top_y"])}')

# CB-7: Outdoor terrain defaults
_OUTDOOR_GROUND_SIZE = 80.0  # outdoor ground plane extent
_OUTDOOR_GROUND_THICKNESS = 0.5

# ── Room dimensions (Item 2) ─────────────────────────────────────
# The visible room shell: floor, 4 walls, ceiling.
# Sized to contain all props within a 20×20 footprint.

_ROOM_WIDTH = 20.0       # X extent
_ROOM_DEPTH = 20.0       # Z extent
_ROOM_HEIGHT = 3.0       # wall height
_ROOM_WALL_THICKNESS = 0.4
_ROOM_FLOOR_THICKNESS = 0.2

# ── Light defaults (Item 1) ──────────────────────────────────────
_LIGHT_HEIGHT = 8.0
_AMBIENT_COLOR = (0.15, 0.15, 0.2, 1.0)
_BACKGROUND_COLOR = (0.05, 0.05, 0.1, 1.0)

# Player spawn offset (FIX-1): player sits at (0, PLAYER_SPAWN_Y, 0)
# to be clear of the floor (top at y=0) and props.
_PLAYER_SPAWN_Y = 1.2  # capsule rests on floor (bottom at y≈0): centre = height/2 + radius = 0.9 + 0.3


# ── Helper functions (defined before data structures that use them) ─

# fmt_float is now the canonical formatter, imported from tscn_writer.
# Keep _fmt_pos as a backward-compat alias used throughout this file;
# all new code should import fmt_float from tscn_writer directly.
_fmt_pos = fmt_float


def _fmt_vec3(x: float, y: float, z: float) -> str:
    """Format a Vector3 string for sub_resource size fields."""
    return f"Vector3({_fmt_pos(x)}, {_fmt_pos(y)}, {_fmt_pos(z)})"


# ── Room sub-resource builder (Item 2) ────────────────────────────
# Built per-call so room_size can vary.  Uses _fmt_pos and light
# constants defined above.

def _build_room_sub_resources(
    room_w: float, room_d: float,
    room_h: float = _ROOM_HEIGHT,
    wall_t: float = _ROOM_WALL_THICKNESS,
    floor_t: float = _ROOM_FLOOR_THICKNESS,
    ambient: tuple | None = None,
    ambient_energy: float = 0.5,
    background: tuple | None = None,
    fog_color: tuple | None = None,
    fog_density: float = 0.015,
    fog_light_energy: float = 0.5,
    exposure: float = 1.0,
    shell_floor: dict | None = None,
    shell_wall: dict | None = None,
    shell_ceiling: dict | None = None,
    nav_vertices = None,
    nav_polygons = None,
    shell_glb_path = None,
    tonemap_mode: int = 3,
) -> tuple[list[dict], list[dict]]:
    """Build the list of room sub-resources for the given dimensions.

    P-G: *ambient* and *background* override the default environment
    colours (per-theme lighting).  Quality A: *ambient_energy* sets
    ambient_light_energy.

    B2: *fog_color*, *fog_density*, *fog_light_energy*, and *exposure*
    override the default post-processing (per-theme atmosphere).
    """
    amb = ambient if ambient is not None else _AMBIENT_COLOR
    bg = background if background is not None else _BACKGROUND_COLOR
    fc = fog_color if fog_color is not None else (0.2, 0.18, 0.22, 1.0)
    # E1: per-theme shell material overrides
    sf = shell_floor or {"albedo": (0.35, 0.25, 0.15), "roughness": 0.85}
    sw = shell_wall or {"albedo": (0.6, 0.55, 0.5), "roughness": 0.8}
    sc = shell_ceiling or {"albedo": (0.75, 0.7, 0.65), "roughness": 0.75}
    # Task 6: compute navmesh vertices/polygons before building the list
    if nav_vertices and nav_polygons:
        _nv = ", ".join(f"{_fmt_pos(v[0])}, 0, {_fmt_pos(v[2])}" for v in nav_vertices)
        _nav_verts = f"vertices = PackedVector3Array({_nv})"
        _tri_lines = ",\n".join(
            f"PackedInt32Array({p[0]}, {p[1]}, {p[2]})" for p in nav_polygons
        )
        _nav_polys = f"polygons = [\n{_tri_lines}\n]"
    else:
        _nav_verts = (
            "vertices = PackedVector3Array("
            + f"{_fmt_pos(-room_w/2 + 1.2)}, 0, {_fmt_pos(-room_d/2 + 1.2)}, "
            + f"{_fmt_pos(room_w/2 - 1.2)}, 0, {_fmt_pos(-room_d/2 + 1.2)}, "
            + f"{_fmt_pos(room_w/2 - 1.2)}, 0, {_fmt_pos(room_d/2 - 1.2)}, "
            + f"{_fmt_pos(-room_w/2 + 1.2)}, 0, {_fmt_pos(room_d/2 - 1.2)})"
        )
        _nav_polys = "polygons = [\nPackedInt32Array(0, 1, 2),\nPackedInt32Array(0, 2, 3)\n]"
    _nav_props = [
        _nav_verts,
        _nav_polys,
        "agent_radius = 0.3",
        "agent_height = 2.0",
        "agent_max_slope = 45.0",
        "agent_max_climb = 0.3",
        "cell_size = 0.3",
    ]
    # Shared sub-resources — present in BOTH GLB and box-shell branches:
    # Environment, player body, NavigationMesh, door visual, wall collision
    # shapes (the wall bodies still get emitted as static colliders even when
    # their visible mesh comes from the GLB shell).
    resources: list[dict] = [
    # Environment for WorldEnvironment (Item 1)
    # B2: Extended with ACES tonemap, SSAO, bloom, fog, exposure
    {"id": "world_env", "type": "Environment",
     "props": [
         "background_mode = 1",
         f"background_color = Color({bg[0]}, {bg[1]}, {bg[2]}, {bg[3]})",
         "ambient_light_source = 1",
         f"ambient_light_color = Color({amb[0]}, {amb[1]}, {amb[2]}, {amb[3]})",
         f"ambient_light_energy = {ambient_energy}",
         # B2: ACES tonemap (overridable via tonemap_mode param)
         f"tonemap_mode = {tonemap_mode}",
         "tonemap_white = 1.0",
         # B2: SSAO
         "ssao_enabled = true",
         "ssao_radius = 0.8",
         "ssao_intensity = 1.2",
         "ssao_power = 1.5",
         "ssao_detail = 0.5",
         "ssao_horizon = 0.06",
         "ssao_sharpness = 0.98",
         # B2: Bloom
         "glow_enabled = true",
         "glow_intensity = 0.2",
         "glow_strength = 1.0",
         "glow_bloom = 0.0",
         "glow_blend_mode = 2",
         "glow_hdr_bleed_threshold = 1.3",
         "glow_hdr_bleed_scale = 1.0",
         "glow_hdr_luminance_cap = 12.0",
         # B2: Fog (exponential — day_night.gd adjusts at runtime)
         "fog_enabled = true",
         "fog_mode = 0",
         f"fog_density = {fog_density}",
         f"fog_light_color = Color({fc[0]}, {fc[1]}, {fc[2]}, {fc[3]})",
         f"fog_light_energy = {fog_light_energy}",
         # B2: Exposure (brightness adjustment)
         "adjustment_enabled = true",
         f"adjustment_brightness = {exposure}",
     ]},
    # Player visible body (Item 4)
    {"id": "player_body_mesh", "type": "CapsuleMesh",
     "props": ["radius = 0.3", "height = 1.8"]},
    {"id": "player_body_mat", "type": "StandardMaterial3D",
     "props": ["albedo_color = Color(0.2, 0.3, 0.5, 1)"]},
    # CB-3 / Task 6: NavigationMesh — carved from prop footprints
    # when available, otherwise the flat-quad fallback
    {"id": "nav_mesh", "type": "NavigationMesh",
     "props": _nav_props},
    # CB-4: Door visual mesh + material (shared by all door entities)
    {"id": "door_mesh", "type": "BoxMesh",
     "props": ["size = Vector3(0.1, 2.4, 1.8)"]},
    {"id": "door_mat", "type": "StandardMaterial3D",
     "props": [
         "albedo_color = Color(0.35, 0.22, 0.12, 1)",
         "roughness = 0.8",
         "metallic = 0.0",
     ]},
    # Collision shapes for walls (always — walls are StaticBody3D in both branches)
    {"id": "wall_ns_shape", "type": "BoxShape3D",
     "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(room_h)}, {_fmt_pos(wall_t)})"]},
    {"id": "wall_ew_shape", "type": "BoxShape3D",
     "props": [f"size = Vector3({_fmt_pos(wall_t)}, {_fmt_pos(room_h)}, {_fmt_pos(room_d)})"]},
    ]
    # ── Shell-source branch (Task 6 fix) ───────────────────────────
    #   GLB path present   → stone/timber triplanar StandardMaterials +
    #                        Texture2D ext_resources for shell_stone_*/shell_timber_*.
    #                        NO box-shell BoxMeshes/textures/materials (the
    #                        scene_compiler used to emit BOTH which stacked
    #                        the inline box over the GLB → magenta walls).
    #   GLB path None     → inline box-shell fallback with floor/wall/ceiling
    #                        BoxMeshes + tileable shell_*_*.png Texture2D
    #                        ext_resources + the per-theme albedo-color tinted
    #                        floor_mat/wall_mat/ceiling_mat.  Used when
    #                        Blender is unavailable.
    #
    #   Fix: shell textures are now ext_resource Texture2D references
    #   (not CompressedTexture2D sub_resources with load_path=).  Godot
    #   resolves the .png path to the imported .ctex automatically —
    #   this is how prop GLB textures already work.
    texture_ext_resources: list[dict] = []
    if shell_glb_path is not None:
        texture_ext_resources.extend([
            {"id": "tex_wall_a", "type": "Texture2D",
             "path": "res://assets/shell_wall_albedo.png"},
            {"id": "tex_wall_n", "type": "Texture2D",
             "path": "res://assets/shell_wall_normal.png"},
            {"id": "tex_wall_o", "type": "Texture2D",
             "path": "res://assets/shell_wall_orm.png"},
            {"id": "tex_roof_a", "type": "Texture2D",
             "path": "res://assets/shell_roof_albedo.png"},
            {"id": "tex_roof_n", "type": "Texture2D",
             "path": "res://assets/shell_roof_normal.png"},
            {"id": "tex_roof_o", "type": "Texture2D",
             "path": "res://assets/shell_roof_orm.png"},
            {"id": "tex_timber_a", "type": "Texture2D",
             "path": "res://assets/shell_timber_albedo.png"},
            {"id": "tex_timber_n", "type": "Texture2D",
             "path": "res://assets/shell_timber_normal.png"},
            {"id": "tex_timber_o", "type": "Texture2D",
             "path": "res://assets/shell_timber_orm.png"},
        ])
        resources.extend([
            # Triplanar StandardMaterial3D applied to the GLB's 'wall' surface
            {"id": "shell_wall_mat", "type": "StandardMaterial3D",
             "props": [
                 "albedo_color = Color(0.6, 0.58, 0.54, 1)",
                 "albedo_texture = ExtResource(\"tex_wall_a\")",
                 "roughness = 0.75",
                 "roughness_texture = ExtResource(\"tex_wall_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_wall_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_wall_n\")",
                 "uv1_triplanar = true",
                 "uv1_world_triplanar = true",
                 "uv1_scale = Vector3(2, 2, 2)",
             ]},
            # Triplanar StandardMaterial3D applied to the GLB's 'roof' surface
            {"id": "shell_roof_mat", "type": "StandardMaterial3D",
             "props": [
                 "albedo_color = Color(0.48, 0.45, 0.42, 1)",
                 "albedo_texture = ExtResource(\"tex_roof_a\")",
                 "roughness = 0.85",
                 "roughness_texture = ExtResource(\"tex_roof_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_roof_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_roof_n\")",
                 "uv1_triplanar = true",
                 "uv1_world_triplanar = true",
                 "uv1_scale = Vector3(2, 2, 2)",
             ]},
            # Triplanar StandardMaterial3D applied to the GLB's 'timber' surface
            {"id": "shell_timber_mat", "type": "StandardMaterial3D",
             "props": [
                 "albedo_color = Color(0.4, 0.26, 0.13, 1)",
                 "albedo_texture = ExtResource(\"tex_timber_a\")",
                 "roughness = 0.85",
                 "roughness_texture = ExtResource(\"tex_timber_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_timber_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_timber_n\")",
                 "uv1_triplanar = true",
                 "uv1_world_triplanar = true",
                 "uv1_scale = Vector3(1, 1, 1)",
             ]},
        ])
    else:
        # Box-shell fallback (Blender unavailable or generation failed).
        # Floor + 4 walls + ceiling as BoxMesh, tileable albedo/normal/orm
        # Texture2D ext_resources, and per-theme tinted StandardMaterial3Ds.
        # When the PNGs are missing Godot falls back to a 1×1 white texture
        # so the albedo_color tint still renders a readable surface.
        texture_ext_resources.extend([
            {"id": "tex_floor_a", "type": "Texture2D",
             "path": "res://assets/shell_floor_albedo.png"},
            {"id": "tex_floor_n", "type": "Texture2D",
             "path": "res://assets/shell_floor_normal.png"},
            {"id": "tex_floor_o", "type": "Texture2D",
             "path": "res://assets/shell_floor_orm.png"},
            {"id": "tex_wall_a", "type": "Texture2D",
             "path": "res://assets/shell_wall_albedo.png"},
            {"id": "tex_wall_n", "type": "Texture2D",
             "path": "res://assets/shell_wall_normal.png"},
            {"id": "tex_wall_o", "type": "Texture2D",
             "path": "res://assets/shell_wall_orm.png"},
            {"id": "tex_ceil_a", "type": "Texture2D",
             "path": "res://assets/shell_ceiling_albedo.png"},
            {"id": "tex_ceil_n", "type": "Texture2D",
             "path": "res://assets/shell_ceiling_normal.png"},
            {"id": "tex_ceil_o", "type": "Texture2D",
             "path": "res://assets/shell_ceiling_orm.png"},
        ])
        resources.extend([
            {"id": "floor_vis_mesh", "type": "BoxMesh",
             "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(floor_t)}, {_fmt_pos(room_d)})"]},
            {"id": "wall_ns_mesh", "type": "BoxMesh",
             "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(room_h)}, {_fmt_pos(wall_t)})"]},
            {"id": "wall_ew_mesh", "type": "BoxMesh",
             "props": [f"size = Vector3({_fmt_pos(wall_t)}, {_fmt_pos(room_h)}, {_fmt_pos(room_d)})"]},
            {"id": "ceiling_mesh", "type": "BoxMesh",
             "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(floor_t)}, {_fmt_pos(room_d)})"]},
            # Per-theme tinted StandardMaterial3Ds (Fix-Batch-1 Task 4 + E1)
            {"id": "floor_mat", "type": "StandardMaterial3D",
             "props": [
                 f"albedo_color = Color({sf['albedo'][0]}, {sf['albedo'][1]}, {sf['albedo'][2]}, 1)",
                 "albedo_texture = ExtResource(\"tex_floor_a\")",
                 f"roughness = {sf['roughness']}",
                 "roughness_texture = ExtResource(\"tex_floor_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_floor_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_floor_n\")",
                 "uv1_scale = Vector3(10, 10, 10)",
             ]},
            {"id": "wall_mat", "type": "StandardMaterial3D",
             "props": [
                 f"albedo_color = Color({sw['albedo'][0]}, {sw['albedo'][1]}, {sw['albedo'][2]}, 1)",
                 "albedo_texture = ExtResource(\"tex_wall_a\")",
                 f"roughness = {sw['roughness']}",
                 "roughness_texture = ExtResource(\"tex_wall_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_wall_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_wall_n\")",
                 "uv1_scale = Vector3(10, 10, 10)",
                 "cull_mode = 2",
             ]},
            {"id": "ceiling_mat", "type": "StandardMaterial3D",
             "props": [
                 f"albedo_color = Color({sc['albedo'][0]}, {sc['albedo'][1]}, {sc['albedo'][2]}, 1)",
                 "albedo_texture = ExtResource(\"tex_ceil_a\")",
                 f"roughness = {sc['roughness']}",
                 "roughness_texture = ExtResource(\"tex_ceil_o\")",
                 "roughness_texture_channel = 1",
                 "ao_texture = ExtResource(\"tex_ceil_o\")",
                 "ao_texture_channel = 0",
                 "normal_texture = ExtResource(\"tex_ceil_n\")",
                 "uv1_scale = Vector3(10, 10, 10)",
                 "cull_mode = 2",
             ]},
        ])
    return resources, texture_ext_resources


# ── Room node builder (Items 1-2) ─────────────────────────────────
# Built per-call so room_size can vary.

def _build_room_nodes(
    room_w: float, room_d: float,
    room_h: float = _ROOM_HEIGHT,
    directional_color: tuple | None = None,
    directional_energy: float | None = None,
    is_outdoor: bool = False,
    shell_glb_path = None,
) -> list[dict]:
    """Build the list of room nodes (lights, meshes, walls) for the
    given dimensions.

    P-G: *directional_color* and *directional_energy* override the
    default DirectionalLight3D (per-theme lighting).

    CB-7: When *is_outdoor* is True, skips walls and ceiling, and
    adds an outdoor ground plane MeshInstance3D.

    Task 6: When *shell_glb_path* is provided, the room's visible
    floor/walls/ceiling come from the instanced shell.glb (emitted
    separately in compile_scene).  This function therefore emits the
    *bodies* for the four walls (so collision still works) but does
    NOT emit the FloorMesh / Ceiling / Wall*_mesh visible children.
    The compile_scene wall-loop also short-circuits the wall_mesh
    emission in this branch so no orphan boxes ship in the .tscn."""
    light_nodes: list[dict] = [
    # WorldEnvironment (Item 1)
    {"name": "WorldEnvironment", "type": "WorldEnvironment", "parent": ".",
     "props": ['environment = SubResource("world_env")']},
    ]
    # DirectionalLight3D (Item 1) — P-G: per-theme colour + energy
    # Sun basis from _constants (deterministic shared anchor)
    _sb = _SUN_BASIS
    dl_props = [
        f"transform = {transform3d(_sb, (0, float(_LIGHT_HEIGHT), 0))}",
    ]
    if directional_color is not None:
        dl_props.append(
            f"light_color = Color({directional_color[0]}, {directional_color[1]}, {directional_color[2]}, 1)"
        )
    if directional_energy is not None:
        dl_props.append(f"light_energy = {directional_energy}")
    light_nodes.append(
        {"name": "DirectionalLight3D", "type": "DirectionalLight3D", "parent": ".",
         "props": dl_props}
    )

    common_nodes = [
        # CB-3: NavigationRegion3D for NPC pathfinding
        {"name": "NavigationRegion3D", "type": "NavigationRegion3D", "parent": ".",
         "props": ['navmesh = SubResource("nav_mesh")']},
    ]

    # Wall bodies — required for player collision in BOTH branches.
    # In the GLB shell branch, the visible mesh comes from the GLB
    # children; the bodies here are collision-only.
    wall_node_objs = [
        # North wall (z = -room_d/2)
        {"name": "WallN", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (0, room_h / 2, -room_d / 2))}",
         ]},
        # South wall (z = +room_d/2)
        {"name": "WallS", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (0, room_h / 2, room_d / 2))}",
         ]},
        # East wall (x = +room_w/2)
        {"name": "WallE", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (room_w / 2, room_h / 2, 0))}",
         ]},
        # West wall (x = -room_w/2)
        {"name": "WallW", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (-room_w / 2, room_h / 2, 0))}",
         ]},
    ]

    if is_outdoor:
        # CB-7: Outdoor — ground plane only, no walls or ceiling
        return light_nodes + common_nodes + [
            {"name": "GroundPlane", "type": "MeshInstance3D", "parent": ".",
             "props": [
                 f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (0, -_OUTDOOR_GROUND_THICKNESS / 2, 0))}",
                 'mesh = SubResource("floor_vis_mesh")',
                 'surface_material_override/0 = SubResource("floor_mat")',
             ]},
        ]

    if shell_glb_path is not None:
        # GLB shell branch: walls as collider-only bodies; the
        # visible shell.glb + stone/timber material overrides are
        # emitted by compile_scene right after this loop.
        return light_nodes + common_nodes + wall_node_objs

    # Box-shell fallback: visible FloorMesh + walls (with mesh + collision
    # children, emitted by compile_scene loop) + Ceiling.
    return light_nodes + common_nodes + [
        # Visible floor mesh (child of existing Floor StaticBody3D)
        {"name": "FloorMesh", "type": "MeshInstance3D", "parent": "Floor",
         "props": [
             'mesh = SubResource("floor_vis_mesh")',
             'surface_material_override/0 = SubResource("floor_mat")',
         ]},
    ] + wall_node_objs + [
        # Ceiling
        {"name": "Ceiling", "type": "MeshInstance3D", "parent": ".",
         "props": [
             f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (0, room_h, 0))}",
             'mesh = SubResource("ceiling_mesh")',
             'surface_material_override/0 = SubResource("ceiling_mat")',
         ]},
    ]


# ── Wall collision children definitions ───────────────────────────

_WALL_COLLISION_NODES: list[dict] = [
    {"name": "WallN_collision", "type": "CollisionShape3D", "parent": "WallN",
     "shape": "wall_ns_shape"},
    {"name": "WallS_collision", "type": "CollisionShape3D", "parent": "WallS",
     "shape": "wall_ns_shape"},
    {"name": "WallE_collision", "type": "CollisionShape3D", "parent": "WallE",
     "shape": "wall_ew_shape"},
    {"name": "WallW_collision", "type": "CollisionShape3D", "parent": "WallW",
     "shape": "wall_ew_shape"},
]

_WALL_MESH_NODES: list[dict] = [
    {"name": "WallN_mesh", "type": "MeshInstance3D", "parent": "WallN",
     "mesh": "wall_ns_mesh", "mat": "wall_mat"},
    {"name": "WallS_mesh", "type": "MeshInstance3D", "parent": "WallS",
     "mesh": "wall_ns_mesh", "mat": "wall_mat"},
    {"name": "WallE_mesh", "type": "MeshInstance3D", "parent": "WallE",
     "mesh": "wall_ew_mesh", "mat": "wall_mat"},
    {"name": "WallW_mesh", "type": "MeshInstance3D", "parent": "WallW",
     "mesh": "wall_ew_mesh", "mat": "wall_mat"},
]   


# ── Public helpers ───────────────────────────────────────────────

def _emit_control_layout(lines: list[str], fill: bool = False) -> None:
    """Emit Godot 4 Control layout properties for a full-window fill."""
    lines.append("layout_mode = 3")
    lines.append("anchors_preset = 15")
    if fill:
        lines.append("anchor_right = 1.0")
        lines.append("anchor_bottom = 1.0")
        lines.append("grow_horizontal = 2")
        lines.append("grow_vertical = 2")


def _glb_res_path(category: str, material: str, assets_subdir: str = "assets") -> str:
    """Build the res:// path for a placed entity's GLB.

    Mirrors publish.py convention: ``res://{assets_subdir}/{category}_{material}.glb``.
    """
    return f"res://{assets_subdir}/{category}_{material}.glb"


def _resolve_unique_glbs(manifest: list[PlacedEntity]) -> list[tuple[str, str]]:
    """Return sorted unique (category, material) pairs from the manifest."""
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for entry in manifest:
        pair = (entry.get("category", "?"), entry.get("material", "default"))
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    result.sort()
    return result


def resolve_unique_glbs_with_npc(
    manifest: list[PlacedEntity],
    quest_specs: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """Return sorted unique (category, material) pairs INCLUDING the NPC body
    ONLY when quest_specs is non-empty OR an NPC entity exists in the manifest.

    This is the single source of truth for which GLBs a compiled scene
    references. Used by both compile_scene() (to emit ext_resource blocks)
    and scaffold.py (to copy the correct asset family per GLB).
    """
    unique = _resolve_unique_glbs(manifest)
    # Include NPC body GLB only when there are quest specs with NPCs
    # OR the manifest explicitly includes an NPC entity.
    has_npc = bool(quest_specs) if quest_specs is not None else True
    if not has_npc:
        # Check manifest for NPC-category entities
        has_npc = any(
            entry.get("category") == _NPC_BODY_CATEGORY
            for entry in manifest
        )
    if has_npc:
        npc_pair = (_NPC_BODY_CATEGORY, _NPC_BODY_MATERIAL)
        if npc_pair not in unique:
            unique.append(npc_pair)
            unique.sort()
    return unique


def _ext_resource_block(unique_glbs: list[tuple[str, str]], assets_subdir: str) -> str:
    """Build the [ext_resource] header block for unique GLBs.

    Omits the ``uid`` attribute intentionally — Godot auto-generates
    UIDs on import, and omitting them keeps the output deterministic
    (same input → byte-identical .tscn).
    """
    lines: list[str] = []
    for idx, (category, material) in enumerate(unique_glbs, start=1):
        path = _glb_res_path(category, material, assets_subdir)
        lines.append(ext_resource("PackedScene", path, str(idx)))
    return "\n".join(lines)


def compile_scene(
    quest_specs: list[dict],
    manifest: list[PlacedEntity],
    output_path: str,
    assets_subdir: str = "assets",
    scene_uid: str | None = None,
    room_size: dict | None = None,
    theme: str | None = None,
    camera_mode: str = "first",
    room_graph: dict | None = None,  # CB-4: multi-room graph
    current_room: tuple | None = None,  # CB-4: which room this scene represents
    room_type: str = "indoor",  # CB-7: "indoor" | "outdoor"
    exterior_plan: dict | None = None,  # CB-7: ExteriorPlan data for outdoor rooms
    lighting_plan: dict | None = None,  # Generative lighting plan (hearth/torch/candle/window + env)
    palette: dict | None = None,          # Scene palette for per-class material override
    decisions_out: list | None = None,    # Phase 0.3: mutable list for threading decisions back
    *,
    shell_glb_path: str | None = None,   # P12: cached shell GLB (caller-supplied; compile_scene no longer calls ensure_room_shell)  # noqa: E501  literal
    shell_decisions: list | None = None, # P12: Decision Points from the cache resolver (forwarded into decisions_out)
) -> str:
    """Compile quest specs + manifest into a Godot .tscn file.

    Also writes a ``_quest_data.json`` file alongside the .tscn
    containing dialogue, objective, and quest metadata so the
    scene loader (P5) can read it without parsing .tscn metadata.

    C-4: Accepts a **list** of quest specs (one per NPC).  Emits N
    NPC nodes with unique IDs and per-NPC quest data.

    FIX-1: Props are now StaticBody3D with CollisionShape3D children;
    GLBs are instanced via header-line ``instance=ExtResource(...)``
    (not a property line); floor + player collision shapes added;
    props are pushed away from the player spawn.

    Items 1-2: Emits WorldEnvironment + DirectionalLight3D for
    lighting, and a visible room shell (floor/walls/ceiling meshes
    with materials) so the scene isn't grey.

    Args:
        quest_specs: List of validated quest specs from
                     ``QuestBehaviourPlanner.plan_multi()`` (C-4).
        manifest: List of placed entities with at least ``id``, ``category``,
                  ``material``, and optional ``x``, ``y``, ``z``.
        output_path: File path to write the .tscn to (e.g.
                     ``/home/.../rpg/scenes/slice1_fetch.tscn``).
        assets_subdir: Subdirectory where GLBs live (default ``"assets"``).
        scene_uid: Optional Godot UID for the scene.  Only emitted when
                   provided (keeps tests deterministic).
        room_size: Optional dict with ``w`` (width) and ``d`` (depth)
                   keys to size the room shell.  Defaults to 20×20.
        theme: Optional theme name (``hermit``, ``blacksmith``,
               ``dungeon``, ...).  Drives per-theme DirectionalLight
               colour + ambient/fog tint via room_control.LIGHTING_TABLE.
        camera_mode: ``"first"`` (eye-level, default) or ``"third"``
                     (over-the-shoulder).  U-7.
        room_graph: CB-4 multi-room graph; emit door entities + their
                    metadata when provided (see ``current_room``).
        current_room: CB-4 ``(x, z)`` tuple identifying which room this
                      scene represents within the multi-room graph.
        room_type: "indoor" (walls+ceiling) or "outdoor" (terrain floor,
                   no walls, biome atmosphere).  CB-7.
        exterior_plan: For outdoor rooms, the ExteriorPlan dict from
                       exterior_planner (field, biome, scatter_placements).
        lighting_plan: Phase 0.3 generative lighting plan.  When
                       provided, scene emits per-source OmniLight3D
                       (hearth/torch/candle/window) plus per-theme
                       ocean/sky/fog plumbing.  Without one, the
                       default per-theme rig is used.
        palette: Phase 0.6b scene palette mapping role → base colour.
                 When provided, prop models override their imported
                 material with per-class StandardMaterial3D
                 (texture + albedo + ORM) so the palette wins over the
                 GLB's baked colours.
        decisions_out: Phase 0.3 mutable list — scene compiler pushes
                       Decision Points (e.g. ambiguous lighting,
                       navmesh.too_dense) here.  The Build Report
                       consumes it after compile.  *Positional or
                       keyword* (lies before the ``*,`` separator).
                       Only ``shell_glb_path`` + ``shell_decisions``
                       below are keyword-only.
        shell_glb_path: AUDIT-05 P12 caller-resolved path to the
                        cached shell GLB.  ``None`` keeps the inline
                        box-shell fallback.  Resolving the cache is
                        no longer this function's job (de-dup).
                        **Keyword-only** — pass by name.
        shell_decisions: AUDIT-05 P12 decision points emitted by the
                         cache resolver; forwarded into
                         ``decisions_out`` when both are supplied.
                         **Keyword-only** — pass by name.

    Returns:
        The *output_path* (so callers can assert the file was written).

    P-G: When *theme* is provided, derives DirectionalLight + ambient
    colours/energy from the per-theme LIGHTING_TABLE in room_control.
    """
    # C-4 backward compat: wrap single dict in list
    if isinstance(quest_specs, dict):
        quest_specs = [quest_specs]

    unique_glbs = resolve_unique_glbs_with_npc(manifest, quest_specs=quest_specs)

    # Compute used tags — include open/door if any entity in the manifest
    # has category.openable=True or category is "door"
    used_tags = {"pickup", "talk"}
    from category_registry import REGISTRY as _REG
    for entry in manifest:
        cat = entry.get("category", "?")
        if not entry.get("decor"):
            ce = _REG.get(cat, {})
            if ce.get("openable"):
                used_tags.add("open")
            if cat == "door":
                used_tags.add("door")
    # CB-4: If room_graph is provided, always include door tag
    if room_graph:
        used_tags.add("door")
    # CB-6: If any enemy entity appears in manifest, include enemy tag
    for entry in manifest:
        if entry.get("category") == "enemy" and not entry.get("decor"):
            used_tags.add("enemy")
            break
    used_tag_scripts: dict[str, str] = {}  # path → ext_resource id
    for tag in sorted(used_tags):
        path = _TAG_TABLE.get(tag)
        if path:
            used_tag_scripts[path] = f"s_{tag}"

    # ── Resolve room dimensions from room_size or defaults ─────
    is_outdoor = (room_type == "outdoor")
    room_w: float = _ROOM_WIDTH
    room_d: float = _ROOM_DEPTH
    if is_outdoor:
        room_w = _OUTDOOR_GROUND_SIZE
        room_d = _OUTDOOR_GROUND_SIZE
    if room_size:
        room_w = float(room_size.get("w", room_w))
        room_d = float(room_size.get("d", room_d))

    # ── Identify interactable entities (FIX-5) ──────────────────
    # Decor entries get no collider, no pickup tag.
    interactable_ids: set[str] = {
        e["id"] for e in manifest
        if not e.get("decor")
    }

    # ── Compute sub_resource count (FIX-1/FIX-5) ───────────────
    # floor BoxShape3D + player CapsuleShape3D + one BoxShape3D per
    # interactable prop + NPC.
    # Num interactable = manifest entries + door entities (CB-4)
    num_interactable = len(interactable_ids)
    # CB-4: Add door entities from room_graph
    door_entities: list[dict] = []
    if room_graph and current_room is not None:
        from room_graph import door_position_on_wall, get_doors_for_room
        room_doors = get_doors_for_room(current_room, room_graph.get("doors", []))
        for dd in room_doors:
            fr, to = tuple(dd["from_room"]), tuple(dd["to_room"])
            dx, dy, dz, yaw = door_position_on_wall(fr, to, room_w, room_d)
            door_id = dd["door_id"]
            door_entities.append({
                "id": door_id, "category": "door",
                "x": dx, "y": dy, "z": dz, "yaw": yaw,
                "locked": dd.get("locked", False),
                "key_entity": dd.get("key_entity"),
                "to_room": dd["to_room"],
            })
            interactable_ids.add(door_id)
    num_interactable = len(interactable_ids)
    num_sub_resources = 2 + num_interactable + 1  # +1 for NPC

    # ── P-G: Resolve per-theme lighting (Phase 1.4 → lighting_resolve) ──
    resolv = _resolve_lighting(
        lighting_plan, theme, is_outdoor, exterior_plan,
        room_w, room_d, _ROOM_HEIGHT,
    )
    ambient_override = resolv["ambient_override"]
    ambient_energy_override = resolv["ambient_energy_override"]
    background_override = resolv["background_override"]
    dir_color_override = resolv["dir_color_override"]
    dir_energy_override = resolv["dir_energy_override"]
    fog_color_override = resolv["fog_color_override"]
    fog_density_override = resolv["fog_density_override"]
    fog_light_energy_override = resolv["fog_light_energy_override"]
    exposure_override = resolv["exposure_override"]
    interior_lights = resolv["interior_lights"]
    shell_floor = resolv["shell_floor"]
    shell_wall = resolv["shell_wall"]
    shell_ceiling = resolv["shell_ceiling"]
    _plan_tonemap = resolv["_plan_tonemap"]

    # Quality B1: Compute NPC positions by finding open floor spots
    # with at least 0.6 m clearance from every prop footprint.  Computed
    # before the no-clip pass so the separation step below can push props
    # away from the *actual* NPC location instead of a hardcoded guess.
    npc_positions = _find_open_npc_positions(
        quest_specs, manifest, room_w, room_d,
    )

    # ── No-clip placement pass (Item 3) ─────────────────────────
    # Deterministic AABB separation so props don't intersect each
    # other or the NPC.  Skips underlay and decor entries.
    if npc_positions:
        separated_manifest = _resolve_prop_overlaps(
            manifest, npc_x=npc_positions[0][0], npc_z=npc_positions[0][1],
        )
    else:
        separated_manifest = _resolve_prop_overlaps(manifest)

    # CB-7: Append scatter vegetation as decor props for outdoor rooms
    if is_outdoor and exterior_plan:
        scatter_placements = exterior_plan.get("scatter_placements", [])
        for sp_idx, sp in enumerate(scatter_placements):
            cat = sp.get("category", "rock")
            # Scatter entries don't carry material — use category as both for GLB path
            separated_manifest.append({
                "id": f"scatter_{cat}_{sp_idx}",
                "category": cat,
                "material": cat,  # exterior GLBs keyed as {category}_{category}.glb
                "x": sp.get("x", 0.0),
                "y": sp.get("y", 0.0),
                "z": sp.get("z", 0.0),
                "decor": True,  # no collision, no pickup tag
            })

    # ── Task 6: Shell GLB + carved navmesh ─────────────────────
    # P12 (AUDIT-05 de-dup): ``compile_scene`` no longer calls
    # ``room_shell.ensure_room_shell`` itself — the call lives entirely
    # in ``foundry/scaffold.py`` (the cache-owning site).  Scaffold
    # threads the result in here via ``shell_glb_path`` (the path to
    # the cached shell.glb) and ``shell_decisions`` (the Decision
    # Points returned by the cache resolver).  When the caller passes
    # ``shell_glb_path=None`` we fall back to the inline box-shell
    # path (preserves today’s deterministic-by-default test behavior).
    if shell_decisions and decisions_out is not None:
        decisions_out.extend(shell_decisions)

    # ── Palette-driven material classes ─────────────────────────
    # When a palette is provided, compute the set of material classes
    # present in the scene (from manifest material → class_for).
    palette_classes: list[str] = []
    if palette is not None:
        class_set: set[str] = set()
        for entry in manifest:
            cls = class_for(entry.get("material", "default"))
            class_set.add(cls)
        if shell_glb_path is not None:
            class_set.add("stone")
            # Task 2: roof gets its own class (role "shadow") so it
            # doesn't share "stone"'s albedo/role-colour with the walls.
            class_set.add("rock")
            class_set.add("wood")
        palette_classes = sorted(class_set)

    # Build carved navmesh from settled prop footprints
    nav_vertices: list = []
    nav_polygons: list = []
    footprints = _get_prop_footprints(separated_manifest, clearance=0.0)
    if footprints:
        nav_vertices, nav_polygons = navmesh.carve_walkable(room_w, room_d, footprints)
    if not nav_vertices:
        nav_vertices, nav_polygons = [], []

    # ── Build room resources + nodes (moved after navmesh compute) ───
    room_sub_resources, texture_ext_resources = _build_room_sub_resources(
        room_w, room_d,
        ambient=ambient_override,
        ambient_energy=ambient_energy_override,
        background=background_override,
        fog_color=fog_color_override,
        fog_density=fog_density_override,
        fog_light_energy=fog_light_energy_override,
        exposure=exposure_override,
        shell_floor=shell_floor,
        shell_wall=shell_wall,
        shell_ceiling=shell_ceiling,
        nav_vertices=nav_vertices,
        nav_polygons=nav_polygons,
        shell_glb_path=shell_glb_path,
        tonemap_mode=_plan_tonemap if _plan_tonemap is not None else 3,
    )
    room_nodes = _build_room_nodes(
        room_w, room_d,
        directional_color=dir_color_override,
        directional_energy=dir_energy_override,
        is_outdoor=is_outdoor,
        shell_glb_path=shell_glb_path,
    )

    # ── Write quest data as a JSON file alongside the .tscn ──────
    # Phase 1.4: delegated to scene_data.write_sidecar_data
    world_log_path = write_sidecar_data(
        output_path, quest_specs, manifest, npc_positions,
        _NPC_BODY_CATEGORY, _NPC_BODY_MATERIAL,
        room_graph=room_graph, current_room=current_room,
    )
    output_dir = str(Path(output_path).parent)
    # Real built GLBs (and their .aabb.json/.sidecar.json siblings) live in
    # the build's assets dir, a SIBLING of the scene's own directory (e.g.
    # build/scenes/main.tscn + build/assets/*.glb) — not output_dir itself.
    assets_dir = str(Path(output_path).parent.parent / assets_subdir)

    # ── Build GLB id map ────────────────────────────────────────
    glb_ids: dict[tuple[str, str], str] = {}
    for i, (cat, mat) in enumerate(unique_glbs, start=1):
        glb_ids[(cat, mat)] = str(i)

    # ── Build collision shape data for each interactable ────────
    # Map entity id → (sub_resource_id, size_tuple)
    collision_info: dict[str, tuple[str, tuple[float, float, float]]] = {}
    sub_res_idx = 1

    # Floor sub_resource
    floor_sub_id = f"sub_{sub_res_idx}"
    sub_res_idx += 1

    # Player sub_resource
    player_sub_id = f"sub_{sub_res_idx}"
    sub_res_idx += 1

    # All prop collisions — skip decor entries (no collider)
    for entry in manifest:
        eid = entry["id"]
        if entry.get("decor"):
            continue  # decor entries get no collision
        cat = entry.get("category", "?")
        collision_info[eid] = (
            f"sub_{sub_res_idx}",
            COLLISION_SIZES.get(cat, COLLISION_SIZES["?"]),
        )
        sub_res_idx += 1

    # NPC collision
    collision_info["NPC"] = (
        f"sub_{sub_res_idx}",
        COLLISION_SIZES.get("humanoid", (0.5, 2.8, 0.4)),
    )
    sub_res_idx += 1

    # CB-4: Door collision shapes — thin boxes on walls
    for dd in door_entities:
        door_id = dd["id"]
        collision_info[door_id] = (
            f"sub_{sub_res_idx}",
            (0.1, 2.4, 1.8),  # thin door collision: 10cm thick × 2.4m tall × 1.8m wide
        )
        sub_res_idx += 1

    # ── Build .tscn content ─────────────────────────────────────
    lines: list[str] = []

    # Count room shell sub-resources for load_steps.  Accurately reflects
    # the branch behaviour since the source list differs between GLB
    # (2 triplanar materials) and box-shell fallback (4 BoxMeshes + 3
    # materials) branches.  Shell textures are now ext_resource Texture2D
    # entries (emitted in the header block), not sub_resource
    # CompressedTexture2D entries.
    num_room_sub_resources = len(room_sub_resources)
    num_texture_ext_resources = len(texture_ext_resources)

    total_load_steps = (
        len(unique_glbs)                     # GLB ext_resources
        + len(_SHELL_SCRIPTS)                # shell scripts
        + len(used_tag_scripts)              # component scripts
        + num_sub_resources                  # collision sub_resources
        + num_room_sub_resources             # Environment + meshes + materials + wall shapes
        + num_texture_ext_resources          # shell texture ext_resources (Texture2D)
        + (1 if shell_glb_path is not None else 0)  # Task 6: shell GLB ext_resource
        + (2 * len(palette_classes))         # palette class texture ext_resources
        + len(palette_classes)               # palette class material sub_resources
    )
    header = f"[gd_scene load_steps={total_load_steps} format=3]"
    if scene_uid:
        header = f'[gd_scene load_steps={total_load_steps} format=3 uid="{scene_uid}"]'
    lines.append(header)
    lines.append("")

    # ExtResources: GLBs
    ext_block = _ext_resource_block(unique_glbs, assets_subdir)
    if ext_block:
        lines.append(ext_block)
    # Task 6: Shell GLB ext_resource (when Blender-generated room shell is available)
    shell_glb_ext_id = None
    if shell_glb_path is not None:
        shell_glb_ext_id = str(len(unique_glbs) + 1)
        shell_name = Path(shell_glb_path).name
        lines.append(
            ext_resource("PackedScene", f"res://assets/{shell_name}", shell_glb_ext_id)
        )
    # Shell texture ext_resources (Texture2D .png references — Godot resolves
    # to the imported .ctex automatically, same as prop GLB textures).
    # Emitted as ext_resource header entries, NOT CompressedTexture2D
    # sub_resources with load_path=.
    for tex in texture_ext_resources:
        lines.append(
            ext_resource(tex["type"], tex["path"], tex["id"])
        )
    # ExtResources: shell scripts (P4)
    for entry in _SHELL_SCRIPTS:
        lines.append(
            ext_resource("Script", entry["path"], entry["id"])
        )
    # ExtResources: tag-based component scripts (P5)
    for path, script_id in sorted(used_tag_scripts.items()):
        lines.append(
            ext_resource("Script", path, script_id)
        )
    # Palette class texture ext_resources (Texture2D .png references)
    if palette is not None:
        for cls in palette_classes:
            lines.append(
                ext_resource("Texture2D", f"res://assets/class_{cls}_albedo.png", f"tex_class_{cls}_a")
            )
            lines.append(
                ext_resource("Texture2D", f"res://assets/class_{cls}_normal.png", f"tex_class_{cls}_n")
            )
    lines.append("")

    # ── SubResources: collision shapes (FIX-1) ──────────────────
    # Floor: BoxShape3D sized by room dimensions
    lines.append(sub_resource_header("BoxShape3D", floor_sub_id))
    lines.append(f"size = Vector3({_fmt_pos(room_w)}, 1, {_fmt_pos(room_d)})")
    lines.append("")

    # Player: CapsuleShape3D
    lines.append(sub_resource_header("CapsuleShape3D", player_sub_id))
    lines.append("radius = 0.3")
    lines.append("height = 1.8")
    lines.append("")

    # Interactable collision shapes (all props + NPC)
    for eid, (sub_id, (sx, sy, sz)) in sorted(collision_info.items()):
        lines.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]')
        lines.append(f"size = {_fmt_vec3(sx, sy, sz)}")
        lines.append("")

    # ── Room shell sub-resources (Environment, meshes, materials) ─
    for sr in room_sub_resources:
        lines.append(f'[sub_resource type="{sr["type"]}" id="{sr["id"]}"]')
        for prop in sr["props"]:
            lines.append(prop)
        lines.append("")

    # ── Palette class material sub_resources ────────────────────
    if palette is not None:
        roles = palette.get("roles", {})
        for cls in palette_classes:
            ci = CLASSES.get(cls, CLASSES["stone"])
            role_color = roles.get(ci["role"], roles.get("base", (0.5, 0.5, 0.5)))
            r, g, b = role_color
            lines.append(f'[sub_resource type="StandardMaterial3D" id="mat_{cls}"]')
            lines.append(f"albedo_color = Color({r}, {g}, {b}, 1)")
            lines.append(f'albedo_texture = ExtResource("tex_class_{cls}_a")')
            lines.append("normal_enabled = true")
            lines.append(f'normal_texture = ExtResource("tex_class_{cls}_n")')
            lines.append(f"roughness = {ci['roughness']}")
            lines.append(f"metallic = {ci['metallic']}")
            # Phase 3.1: triplanar gating — only natural large-surface classes
            # (stone/wood/rock/soil) get world-space triplanar UV; small props
            # (metal/fabric/foliage) use standard UV to avoid moire and save cost.
            if ci.get("triplanar", True):
                lines.append("uv1_triplanar = true")
                lines.append("uv1_world_triplanar = true")
            lines.append("")

    # Root (no parent attribute — Godot 4 convention)
    lines.append('[node name="Root" type="Node3D"]')
    lines.append("")

    # ── Floor node (FIX-1b) ─────────────────────────────────────
    # StaticBody3D sized by room dimensions, top at y=0 → centre at y=-0.5
    lines.append('[node name="Floor" type="StaticBody3D" parent="."]')
    lines.append(
        "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)"
    )
    lines.append('[node name="FloorCollision" type="CollisionShape3D" parent="Floor"]')
    lines.append(f'shape = SubResource("{floor_sub_id}")')
    lines.append("")

    # ── Room shell nodes: lights, visible geometry, walls (Items 1-2) ─
    for room_node in room_nodes:
        lines.append(
            f'[node name="{room_node["name"]}" type="{room_node["type"]}" '
            f'parent="{room_node["parent"]}"]'
        )
        for prop in room_node.get("props", []):
            lines.append(prop)
        lines.append("")
        # Emit wall collision child if this is a wall body (always —
        # the GLB shell branch still needs invisible StaticBody3D
        # wall colliders for player physics).
        wall_coll = next(
            (wc for wc in _WALL_COLLISION_NODES if wc["parent"] == room_node["name"]),
            None,
        )
        if wall_coll:
            lines.append(
                f'[node name="{wall_coll["name"]}" type="{wall_coll["type"]}" '
                f'parent="{wall_coll["parent"]}"]'
            )
            lines.append(f'shape = SubResource("{wall_coll["shape"]}")')
            lines.append("")
        # Task 6 fix: in the GLB shell branch the visible wall mesh comes
        # from the rendered shell.glb.  Shipping Wall*_mesh children on
        # top of that stacks invisible boxes over the GLB and was the
        # root cause of the magenta walls.  Skip wall_mesh emission
        # entirely when shell_glb_path is provided; the box-shell
        # fallback below is unchanged.
        wall_mesh = next(
            (wm for wm in _WALL_MESH_NODES if wm["parent"] == room_node["name"]),
            None,
        )
        if wall_mesh and shell_glb_path is None:
            lines.append(
                f'[node name="{wall_mesh["name"]}" type="{wall_mesh["type"]}" '
                f'parent="{wall_mesh["parent"]}"]'
            )
            lines.append(f'mesh = SubResource("{wall_mesh["mesh"]}")')
            lines.append(
                f'surface_material_override/0 = SubResource("{wall_mesh["mat"]}")'
            )
            lines.append("")

    # ── Task 6 fix: Shell instance + wall/roof/timber material overrides ─
    # When room_shell.ensure_room_shell() returns a Blender-generated
    # GLB the room's visible geometry comes from that PackedScene.
    # shell.glb contains three top-level mesh objects named "wall" (walls),
    # "roof" (roof boards), and "timber" (floor + rafters + tie-beams +
    # king-post + ridge).  Instancing shell.glb as `Shell` then redeclaring
    # the children with `material_override =` propagates the build's
    # triplanar StandardMaterials per surface — the rest of the GLB's
    # geometry survives intact.
    if shell_glb_path is not None and shell_glb_ext_id is not None:
        lines.append(
            f'[node name="Shell" parent="." instance=ExtResource("{shell_glb_ext_id}")]'
        )
        lines.append("")
        if palette is not None:
            # Palette-driven: use per-class materials. Task 2: roof uses
            # the "rock" class (role "shadow") instead of "stone" (role
            # "base") so the ceiling reads as a distinct surface from
            # the walls even when a scene palette is active.
            lines.append('[node name="wall" parent="Shell"]')
            lines.append('material_override = SubResource("mat_stone")')
            lines.append("")
            lines.append('[node name="roof" parent="Shell"]')
            lines.append('material_override = SubResource("mat_rock")')
            lines.append("")
            lines.append('[node name="timber" parent="Shell"]')
            lines.append('material_override = SubResource("mat_wood")')
            lines.append("")
        else:
            lines.append('[node name="wall" parent="Shell"]')
            lines.append('material_override = SubResource("shell_wall_mat")')
            lines.append("")
            lines.append('[node name="roof" parent="Shell"]')
            lines.append('material_override = SubResource("shell_roof_mat")')
            lines.append("")
            lines.append('[node name="timber" parent="Shell"]')
            lines.append('material_override = SubResource("shell_timber_mat")')
            lines.append("")

    # Quality A: Interior OmniLight3D ceiling lights (after shell, before props)
    for il_node in interior_lights:
        lines.append(
            f'[node name="{il_node["name"]}" type="{il_node["type"]}" '
            f'parent="{il_node["parent"]}"]'
        )
        for prop in il_node.get("props", []):
            lines.append(prop)
        lines.append("")

    # ── Placed props (FIX-1a/d/e) ───────────────────────────────
    # Props are now StaticBody3D with collision shapes.  GLB model
    # is instanced via header-line instance=ExtResource(...).
    # Uses separated_manifest from the no-clip pass (Item 3).
    for entry in separated_manifest:
        eid = entry["id"]
        cat = entry.get("category", "?")
        mat = entry.get("material", "default")
        x = entry.get("x", 0.0)
        y = entry.get("y", 0.0)
        z = entry.get("z", 0.0)
        is_decor = entry.get("decor", False)
        # Task 2: rest the prop on the floor (kill floating)
        prop_y = y
        if not is_decor and eid in collision_info:
            _, (_, sy, _) = collision_info[eid]
            # Try real AABB min-y from sidecar/aabb.json; fall back to collision-box approx
            aabb_min_y = read_asset_aabb_min_y(assets_dir, cat, mat)
            if aabb_min_y is not None:
                prop_y = y + rest_offset(aabb_min_y)
            else:
                prop_y = y + rest_offset(-sy / 2.0)
        # CB-2/CB-6: Determine tag — openable→open, enemy→enemy, others→decor/pickup
        from category_registry import REGISTRY
        reg_entry = REGISTRY.get(cat, {})
        if cat == "enemy":
            tag = "enemy"
        elif not is_decor and reg_entry.get("openable"):
            tag = "open"
        elif is_decor:
            tag = "inert"
        else:
            tag = "pickup"
        glb_id = glb_ids.get((cat, mat), "1")

        # Guard: push away from player spawn (FIX-1e)
        x, z = _guard_player_spawn(x, z)

        # CB-6: Enemy entities are CharacterBody3D (moveable)
        if cat == "enemy":
            lines.append(f'[node name="{eid}" type="CharacterBody3D" parent="."]')
        elif is_decor:
            lines.append(f'[node name="{eid}" type="Node3D" parent="."]')
        elif eid in interactable_ids:
            lines.append(f'[node name="{eid}" type="StaticBody3D" parent="."]')
        else:
            lines.append(f'[node name="{eid}" type="Node3D" parent="."]')
        lines.append(
            f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (x, prop_y, z))}"
        )
        if not is_decor:
            lines.append(f'metadata/_forge_tag = "{tag}"')
            # P-B: add category metadata for named prompts
            lines.append(f'metadata/_forge_category = "{cat}"')
            # B3: per-item flags (use_verb, weight, durability, openable)
            _b3_emit_item_metadata(lines, cat)
            # P5: attach component script by tag
            component_path = _TAG_TABLE.get(tag)
            if component_path and component_path in used_tag_scripts:
                lines.append(
                    f'script = ExtResource("{used_tag_scripts[component_path]}")'
                )
        lines.append("")

        # Collision shape for interactable props (FIX-1d), skip decor
        if not is_decor and eid in collision_info:
            sub_id = collision_info[eid][0]
            lines.append(
                f'[node name="{eid}_collision" type="CollisionShape3D" parent="{eid}"]'
            )
            lines.append(f'shape = SubResource("{sub_id}")')
            lines.append("")

        # GLB model — instanced via header line (FIX-1a)
        lines.append(
            f'[node name="{eid}_model" parent="{eid}" instance=ExtResource("{glb_id}")]'
        )
        # Palette material_override on the model node (strips GLB materials)
        if palette is not None and not is_decor:
            cls = class_for(mat)
            lines.append(f'surface_material_override/0 = SubResource("mat_{cls}")')
        lines.append("")

        # B2: Light-emitting prop child (OmniLight3D) — Phase 1.4 reads from REGISTRY
        emitter = reg_entry.get("emitter")
        if emitter:
            le = emitter
            light_color = le["color"]
            light_node_name = f"{eid}_light"
            lines.append(
                f'[node name="{light_node_name}" type="OmniLight3D" parent="{eid}"]'
            )
            # Position the light above the prop centre
            lines.append("transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.5, 0)")
            lines.append(
                f"light_color = Color({light_color[0]}, {light_color[1]}, {light_color[2]}, 1)"
            )
            lines.append(f"light_energy = {le['energy']}")
            lines.append(f"omni_range = {le['range']}")
            if le.get("negative", False):
                lines.append("light_negative = true")
            # Small shadow for atmosphere (baked to keep perf)
            lines.append("shadow_enabled = true")
            lines.append("")

    # ── C-4: NPC nodes — one per quest spec ─────────────────────
    npc_script_path = _TAG_TABLE.get("talk")
    npc_glb_id = glb_ids.get((_NPC_BODY_CATEGORY, _NPC_BODY_MATERIAL), "1")
    npc_collision_sub_id = collision_info.get("NPC", ("sub_0",))[0]
    
    for idx, spec in enumerate(quest_specs):
        npc_id = spec.get("npc_id", f"npc_{idx}")
        npc_role = spec.get("npc_role", "villager")
        # Quality B1: use computed open-floor positions
        npc_x, npc_z = npc_positions[idx]
        npc_y = 0.0

        lines.append(node_header(npc_id, "StaticBody3D", "."))
        lines.append(
            f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (npc_x, npc_y, npc_z))}"
        )
        lines.append('metadata/_forge_tag = "talk"')
        lines.append('metadata/_forge_tag_give = "give"')
        lines.append(f'metadata/_forge_role = "{npc_role}"')
        # C-4: NPC ID metadata for quest_data lookup
        lines.append(f'metadata/_forge_npc_id = "{npc_id}"')
        # P5: attach npc.gd via the talk tag
        if npc_script_path and npc_script_path in used_tag_scripts:
            lines.append(
                f'script = ExtResource("{used_tag_scripts[npc_script_path]}")'
            )
        lines.append("")

        # NPC collision shape
        lines.append(
            f'[node name="{npc_id}_collision" type="CollisionShape3D" parent="{npc_id}"]'
        )
        lines.append(f'shape = SubResource("{npc_collision_sub_id}")')
        lines.append("")

        # CB-7: Skeleton3D for procedural humanoid rig
        lines.append(node_header("Skeleton", "Skeleton3D", npc_id))
        lines.append("")

        # CB-7: AnimationPlayer for idle/walk animations
        lines.append(node_header("AnimationPlayer", "AnimationPlayer", npc_id))
        lines.append('root_node = NodePath("../Skeleton")')
        lines.append("")

        # CB-7: BoneAttachment3D on Hips bone — carries the GLB body mesh
        lines.append(node_header("HipsAttachment", "BoneAttachment3D", npc_id))
        lines.append('bone_name = "Hips"')
        lines.append('skeleton = NodePath("../Skeleton")')
        lines.append("")

        # NPC body GLB instance — now attached to the Hips bone
        lines.append(
            node_header("Body", parent=f"{npc_id}/HipsAttachment", instance=npc_glb_id)
        )
        lines.append("")

        # NPC nameplate
        lines.append(node_header("Nameplate", "Label3D", npc_id))
        lines.append("transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2.0, 0)")
        lines.append(f'text = "{npc_role}"')
        lines.append("billboard = 1")
        lines.append("horizontal_alignment = 1")
        lines.append("font_size = 32")
        lines.append("outline_size = 2")
        lines.append("outline_modulate = Color(0, 0, 0, 1)")
        lines.append("")

    # ── Shell nodes (P4: with scripts attached + proper UI layout)
    for shell in _SHELL_NODES:
        parent = shell["parent"]
        lines.append(
            f'[node name="{shell["name"]}" type="{shell["type"]}" '
            f'parent="{parent}"]'
        )
        if shell.get("script"):
            lines.append(f'script = ExtResource("{shell["script"]}")')
        if shell["name"] == "Camera3D":
            # U-7: camera mode — first (eye-level) or third (behind player)
            if camera_mode == "third":
                lines.append(
                    "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2.0, 3.0)"
                )
            else:
                lines.append(
                    "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.7, 0)"
                )
            lines.append("current = true")
        if shell["name"] == "CarriedItem":
            # Position in front of camera (0.4 m forward, 0.1 m right, -0.1 m down)
            lines.append(
                "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0.15, -0.1, -0.45)"
            )
        if shell["name"] == "Player":
            # Player spawn at y=1 to be clear of floor (FIX-1c)
            lines.append(
                "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
                f"0, {_fmt_pos(_PLAYER_SPAWN_Y)}, 0)"
            )
        if shell["name"] == "HUD":
            _emit_control_layout(lines, fill=True)
        if shell["name"] == "WinScreen":
            lines.append("visible = false")
            _emit_control_layout(lines, fill=True)
        lines.append("")

    # Player CollisionShape3D (FIX-1c) — placed AFTER the Player node
    # so it's a child of Player.
    lines.append(
        '[node name="PlayerCollision" type="CollisionShape3D" parent="Player"]'
    )
    lines.append(f'shape = SubResource("{player_sub_id}")')
    lines.append("")

    # Player visible body (Item 4) — CapsuleMesh so the player doesn't
    # appear as a floating free camera.
    lines.append(
        '[node name="BodyMesh" type="MeshInstance3D" parent="Player"]'
    )
    lines.append('mesh = SubResource("player_body_mesh")')
    lines.append(
        'surface_material_override/0 = SubResource("player_body_mat")'
    )
    lines.append("")

    # HUD child labels
    lines.append('[node name="Crosshair" type="ColorRect" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 8")
    lines.append("anchor_left = 0.5")
    lines.append("anchor_top = 0.5")
    lines.append("anchor_right = 0.5")
    lines.append("anchor_bottom = 0.5")
    lines.append("offset_left = -4.0")
    lines.append("offset_top = -4.0")
    lines.append("offset_right = 4.0")
    lines.append("offset_bottom = 4.0")
    lines.append("color = Color(0, 1, 0, 0.8)")
    lines.append("")

    lines.append('[node name="ObjectiveLabel" type="Label" parent="HUD"]')
    lines.append("layout_mode = 0")
    lines.append("offset_left = 20.0")
    lines.append("offset_top = 20.0")
    lines.append("offset_right = 600.0")
    lines.append("offset_bottom = 50.0")
    lines.append("text = \"\"")
    lines.append("")

    lines.append('[node name="InteractLabel" type="Label" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 8")
    lines.append("anchor_left = 0.5")
    lines.append("anchor_top = 0.5")
    lines.append("anchor_right = 0.5")
    lines.append("anchor_bottom = 0.5")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append("text = \"\"")
    lines.append('horizontal_alignment = 1')
    lines.append("")

    # B1: Quest counter label — top-right, shows "X / N quests done"
    lines.append('[node name="QuestCounter" type="Label" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchor_left = 1.0")
    lines.append("anchor_top = 0.0")
    lines.append("anchor_right = 1.0")
    lines.append("anchor_bottom = 0.0")
    lines.append("offset_left = -280.0")
    lines.append("offset_top = 8.0")
    lines.append("offset_right = -8.0")
    lines.append("offset_bottom = 32.0")
    lines.append("grow_horizontal = 0")
    lines.append("grow_vertical = 0")
    lines.append("text = \"\"")
    lines.append("horizontal_alignment = 2")
    lines.append("modulate = Color(0.8, 0.8, 0.5, 0.9)")
    lines.append("visible = false")
    lines.append("")

    # B1: Quest log panel — toggle with J, lists all NPC quests
    lines.append('[node name="QuestLog" type="Control" parent="HUD"]')
    _emit_control_layout(lines, fill=False)
    lines.append("anchor_left = 0.01")
    lines.append("anchor_top = 0.05")
    lines.append("anchor_right = 0.35")
    lines.append("anchor_bottom = 0.85")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append("modulate = Color(1, 1, 1, 0.85)")
    lines.append("")

    # B1: Quest log background
    lines.append('[node name="QuestLogBG" type="ColorRect" parent="HUD/QuestLog"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 15")
    lines.append("anchor_right = 1.0")
    lines.append("anchor_bottom = 1.0")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append("color = Color(0.05, 0.05, 0.08, 0.85)")
    lines.append("")

    # B1: Quest log text
    lines.append('[node name="QuestLogText" type="Label" parent="HUD/QuestLog"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 15")
    lines.append("anchor_right = 1.0")
    lines.append("anchor_bottom = 1.0")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append("offset_left = 8.0")
    lines.append("offset_top = 8.0")
    lines.append("offset_right = -8.0")
    lines.append("offset_bottom = -8.0")
    lines.append("text = \"\"")
    lines.append("horizontal_alignment = 0")
    lines.append("vertical_alignment = 0")
    lines.append("autowrap_mode = 3")
    lines.append("")

    # B1: Subtitle / dialogue scrollback panel — bottom of screen
    lines.append('[node name="SubtitlePanel" type="RichTextLabel" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchor_left = 0.15")
    lines.append("anchor_top = 0.78")
    lines.append("anchor_right = 0.85")
    lines.append("anchor_bottom = 0.95")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 0")
    lines.append("modulate = Color(1, 1, 1, 0.7)")
    lines.append("bbcode_enabled = true")
    lines.append("text = \"\"")
    lines.append("scroll_following = true")
    lines.append("")

    # B1: Tooltip label — center-top, shows hovered prop/NPC name
    lines.append('[node name="TooltipLabel" type="Label" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 8")
    lines.append("anchor_left = 0.5")
    lines.append("anchor_top = 0.55")
    lines.append("anchor_right = 0.5")
    lines.append("anchor_bottom = 0.55")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append("text = \"\"")
    lines.append("horizontal_alignment = 1")
    lines.append("vertical_alignment = 1")
    lines.append("modulate = Color(0.9, 0.85, 0.7, 0.9)")
    lines.append("visible = false")
    lines.append("")

    # C-2: Inventory label — right side of screen, shows carried items
    lines.append('[node name="InventoryLabel" type="Label" parent="HUD"]')
    lines.append("layout_mode = 1")
    lines.append("anchor_left = 1.0")
    lines.append("anchor_top = 0.0")
    lines.append("anchor_right = 1.0")
    lines.append("anchor_bottom = 0.0")
    lines.append("offset_left = -220.0")
    lines.append("offset_top = 80.0")
    lines.append("offset_right = -20.0")
    lines.append("offset_bottom = 400.0")
    lines.append("grow_horizontal = 0")
    lines.append("grow_vertical = 0")
    lines.append("text = \"\"")
    lines.append("horizontal_alignment = 2")
    lines.append("modulate = Color(0.85, 0.85, 0.85, 0.9)")
    lines.append("")

    # Win screen child labels (P-B)
    lines.append('[node name="WinLabel" type="Label" parent="WinScreen"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 8")
    lines.append("anchor_left = 0.5")
    lines.append("anchor_top = 0.4")
    lines.append("anchor_right = 0.5")
    lines.append("anchor_bottom = 0.4")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append('text = "You won!"')
    lines.append("horizontal_alignment = 1")
    lines.append("vertical_alignment = 1")
    lines.append("")
    lines.append('[node name="WinSubLabel" type="Label" parent="WinScreen"]')
    lines.append("layout_mode = 1")
    lines.append("anchors_preset = 8")
    lines.append("anchor_left = 0.5")
    lines.append("anchor_top = 0.5")
    lines.append("anchor_right = 0.5")
    lines.append("anchor_bottom = 0.5")
    lines.append("grow_horizontal = 2")
    lines.append("grow_vertical = 2")
    lines.append('text = "Press R to restart / Esc to quit"')
    lines.append("horizontal_alignment = 1")
    lines.append("vertical_alignment = 1")
    lines.append("")

    # B2: Wire theme into DayNight node for ambient sound + time-of-day start
    if theme:
        lines.append('[node name="DayNight" parent="."]')
        lines.append(f'metadata/_forge_theme = "{theme}"')
        lines.append("")

    # ── QuestData node (no script — P5 reads the JSON resource directly)
    lines.append('[node name="QuestData" type="Node" parent="."]')
    lines.append("")

    # ── CB-4: Door entities on room boundaries ───────────────────
    door_script_path = _TAG_TABLE.get("door")
    for dd_idx, dd in enumerate(door_entities):
        door_id = dd["id"]
        dx, dy, dz = dd["x"], dd["y"], dd["z"]
        yaw = dd.get("yaw", 0.0)
        # CB-4: Apply yaw to door transform so doors face the correct direction
        import math
        cos_y = math.cos(yaw)
        sin_y = math.sin(yaw)
        lines.append(f'[node name="{door_id}" type="StaticBody3D" parent="."]')
        lines.append(
            f"transform = {transform3d((cos_y, 0, -sin_y, 0, 1, 0, sin_y, 0, cos_y), (dx, dy, dz))}"
        )
        lines.append('metadata/_forge_tag = "door"')
        if dd.get("locked"):
            lines.append(f'metadata/_forge_key_entity = "{dd["key_entity"]}"')
        # CB-4: neighbour room data for traversal + world log path for persistence
        to_room = dd.get("to_room", [0, 0])
        lines.append(f'metadata/_forge_target_room = "{to_room[0]},{to_room[1]}"')
        lines.append(f'metadata/_forge_world_log = "{world_log_path}"')
        if door_script_path and door_script_path in used_tag_scripts:
            lines.append(
                f'script = ExtResource("{used_tag_scripts[door_script_path]}")'
            )
        lines.append("")
        # Door collision shape (thin box on the wall)
        if door_id in collision_info:
            door_sub_id = collision_info[door_id][0]
            lines.append(f'[node name="{door_id}_collision" type="CollisionShape3D" parent="{door_id}"]')
            lines.append(f'shape = SubResource("{door_sub_id}")')
            lines.append("")
        # CB-4: Door visual model — simple BoxMesh so doors are visible
        lines.append(
            f'[node name="{door_id}_model" parent="{door_id}"]'
        )
        lines.append('mesh = SubResource("door_mesh")')
        lines.append('surface_material_override/0 = SubResource("door_mat")')
        lines.append("")

    content = "\n".join(lines)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    return output_path


def _parse_scene_text(tscn_text: str) -> dict:
    """Parse a .tscn text into a structured dict for test assertions.

    Returns a dict with keys: ``ext_resources``, ``sub_resources``,
    ``nodes``, and ``metadata`` (a dict keyed by node name → metadata
    key-value pairs).

    Handles ``instance=ExtResource(...)`` both on the ``[node]`` header
    line (FIX-1a) and on property lines (legacy format).
    """
    ext_resources: list[dict] = []
    sub_resources: list[dict] = []
    nodes: list[dict] = []
    metadata: dict[str, dict[str, str]] = {}
    current_node: dict | None = None

    # Property prefixes we recognise as belonging to the current node
    _NODE_PROPERTY_PREFIXES = (
        "instance ", "transform ", "metadata/",
        "script ", "shape ",
        "current ", "visible ",
        "layout_mode ", "anchors_preset ",
        "anchor_", "offset_", "grow_", "text ",
        "horizontal_alignment ",
        "environment ", "shadow_enabled ", "navmesh ",
        "mesh ", "surface_material_override/",
    )

    for line in tscn_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("[ext_resource "):
            id_match = re.search(r'id="([^"]+)"', stripped)
            path_match = re.search(r'path="([^"]+)"', stripped)
            type_match = re.search(r'type="([^"]+)"', stripped)
            ext_resources.append({
                "id": id_match.group(1) if id_match else "",
                "path": path_match.group(1) if path_match else "",
                "type": type_match.group(1) if type_match else "",
            })

        elif stripped.startswith("[sub_resource "):
            id_match = re.search(r'id="([^"]+)"', stripped)
            type_match = re.search(r'type="([^"]+)"', stripped)
            sub_resources.append({
                "id": id_match.group(1) if id_match else "",
                "type": type_match.group(1) if type_match else "",
            })

        elif stripped.startswith("[node "):
            if current_node:
                nodes.append(current_node)
            name_match = re.search(r'name="([^"]+)"', stripped)
            type_match = re.search(r'type="([^"]+)"', stripped)
            parent_match = re.search(r'parent="([^"]+)"', stripped)
            instance_match = re.search(
                r'instance\s*=\s*ExtResource\("([^"]+)"\)', stripped
            )
            current_node = {
                "name": name_match.group(1) if name_match else "",
                "type": type_match.group(1) if type_match else "",
                "parent": parent_match.group(1) if parent_match else "",
                "instance": instance_match.group(1) if instance_match else None,
            }
            metadata[current_node["name"]] = {}

        elif current_node and (
            stripped.startswith(_NODE_PROPERTY_PREFIXES)
        ):
            # Property line for the current node
            if stripped.startswith("instance = ExtResource"):
                m = re.search(
                    r'instance\s*=\s*ExtResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["instance"] = m.group(1)
            elif stripped.startswith("script = ExtResource"):
                m = re.search(
                    r'script\s*=\s*ExtResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["script"] = m.group(1)
            elif stripped.startswith("shape = SubResource"):
                m = re.search(
                    r'shape\s*=\s*SubResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["shape"] = m.group(1)
            elif stripped.startswith("mesh = SubResource"):
                m = re.search(
                    r'mesh\s*=\s*SubResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["mesh"] = m.group(1)
            elif stripped.startswith("environment = SubResource"):
                m = re.search(
                    r'environment\s*=\s*SubResource\("([^"]+)"\)', stripped
                )
                if m:
                    current_node["environment"] = m.group(1)
            elif stripped.startswith("surface_material_override/"):
                m = re.search(
                    r'surface_material_override/\d+\s*=\s*SubResource\("([^"]+)"\)', stripped
                )
                if m:
                    if "surface_materials" not in current_node:
                        current_node["surface_materials"] = []
                    current_node["surface_materials"].append(m.group(1))
            elif stripped.startswith("metadata/"):
                key_val = stripped[len("metadata/"):]
                eq = key_val.find(" = ")
                if eq != -1:
                    key = key_val[:eq].strip()
                    val = key_val[eq + 3:].strip().strip('"')
                    metadata[current_node["name"]][key] = val

    if current_node:
        nodes.append(current_node)

    return {
        "ext_resources": ext_resources,
        "sub_resources": sub_resources,
        "nodes": nodes,
        "metadata": metadata,
    }



# ── C-3: World log initialisation ─────────────────────────────────
# Phase 1.4: canonical functions moved to scene_data.py.
# Re-exported here for backward-compat.

from scene_data import _init_world_log, read_quest_data  # noqa: E402, F401


# ── Task 4: Bake scene_desc builder + bake_scene wiring ────────────
# Phase 1.2: canonical builder lives in lighting_bake.build_scene_desc.
# bake_and_apply also moved to lighting_bake.  scene_compiler imports
# from there if it ever needs to call them (it doesn't — compile_scene
# only wires the realtime rig).
