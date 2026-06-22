"""Scene compiler — deterministic spec→Godot .tscn generator.

Turns a quest spec + placed-entity manifest into a runnable Godot
scene (.tscn) for the rpg project, wiring everything by a fixed
tag→behaviour table.  The LLM never appears here.

Mirrors ``foundry/publish.py`` for path/resource handling.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, TypedDict


from category_registry import COLLISION_SIZES

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


# ── Tag → component table ────────────────────────────────────────
# P5 wires these into the .tscn.  Kept here as the single source of
# truth for which tag maps to which component script path.

_TAG_TABLE: Dict[str, str | None] = {
    "pickup": "res://scripts/pickup.gd",
    "talk": "res://scripts/npc.gd",
    # "give" is handled by npc.gd (state machine checks carried_item)
    "give": "res://scripts/npc.gd",
    # CB-2: openable containers + locked doors
    "open": "res://scripts/container.gd",
    "door": "res://scripts/door.gd",
    # CB-6: enemy entity (NOT npc.gd — separate entity type)
    "enemy": "res://scripts/enemy.gd",
    "inert": None,
}

# ── B2: Light-emitting props ────────────────────────────────────
# Categories that emit OmniLight3D when placed.  Per-category light
# params (color, energy, range) tuned for cosy indoor scale.
# Colour is (r, g, b) in [0, 1].

_LIGHT_EMITTING: Dict[str, dict] = {
    "lantern": {"color": (1.0, 0.7, 0.3), "energy": 2.5, "range": 4.0, "negative": False},
    "candle":  {"color": (1.0, 0.8, 0.4), "energy": 1.2, "range": 2.0, "negative": False},
}

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
        lines.append(f'metadata/_forge_surface_tag = "place"')
        lines.append(f'metadata/_forge_surface_y = {float(entry["furniture_top_y"])}')

# ── Shell scripts ──────────────────────────────────────────────
# P4: reusable GDScript files the compiler always attaches.
# Paths relative to res:// — these were authored once in rpg/scripts/.

_SHELL_SCRIPTS: List[dict] = [
    {"id": "s_player", "path": "res://scripts/player.gd"},
    {"id": "s_interact", "path": "res://scripts/interaction.gd"},
    {"id": "s_hud", "path": "res://scripts/hud.gd"},
    {"id": "s_win", "path": "res://scripts/win_screen.gd"},
    # B2: day/night cycle runtime
    {"id": "s_day_night", "path": "res://scripts/day_night.gd"},
    # CB-5: event_manager.gd — reads/writes events from quest_data
    {"id": "s_event_mgr", "path": "res://scripts/event_manager.gd"},
    # CB-6: health.gd — player health component (attached to Player)
    {"id": "s_health", "path": "res://scripts/health.gd"},
    # CB-6: combat.gd — melee combat system (attached to Player)
    {"id": "s_combat", "path": "res://scripts/combat.gd"},
    # CB-1: quest manager autoload — registered in project.godot
    # CB-2: container.gd + door.gd are emitted via used_tag_scripts
    # CB-6: enemy.gd is emitted via used_tag_scripts
    #       (like pickup.gd/npc.gd), not via _SHELL_SCRIPTS.
]

# ── Shell node definitions ───────────────────────────────────────
# The compiler always emits these nodes.  P4 attaches the shell
# scripts; P5 wires pickup/talk/give components by tag.

_SHELL_NODES: List[dict] = [
    {"name": "Player", "type": "CharacterBody3D", "parent": ".", "script": "s_player"},
    {"name": "Camera3D", "type": "Camera3D", "parent": "Player"},
    {"name": "CarriedItem", "type": "Node3D", "parent": "Player/Camera3D"},
    {"name": "InteractionRaycast", "type": "Node3D", "parent": "Player/Camera3D", "script": "s_interact"},
    {"name": "HUD", "type": "Control", "parent": ".", "script": "s_hud"},
    {"name": "WinScreen", "type": "Control", "parent": ".", "script": "s_win"},
    # B2: day/night cycle runtime node
    {"name": "DayNight", "type": "Node", "parent": ".", "script": "s_day_night"},
    # CB-5: emergent events runtime
    {"name": "EventManager", "type": "Node", "parent": ".", "script": "s_event_mgr"},
    # CB-6: player health component
    {"name": "Health", "type": "Node", "parent": "Player", "script": "s_health"},
    # CB-6: melee combat system
    {"name": "Combat", "type": "Node", "parent": "Player", "script": "s_combat"},
]

# ── NPC body (P7: procedurally generated humanoid GLB) ──────────
# The NPC body is a pre-built GLB (generated by the Blender foundry
# and published into rpg/assets/).  The compiler instances it like
# any prop.  Uses rough_granite from the existing material palette
# (mottled stone — reads as a clay/golem figure).

_NPC_BODY_CATEGORY = "humanoid"
_NPC_BODY_MATERIAL = "rough_granite"

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

_LIGHT_DIRECTION = (-0.5, -0.75, 0.433013)  # DirectionalLight rotation basis
_LIGHT_HEIGHT = 8.0
_AMBIENT_COLOR = (0.15, 0.15, 0.2, 1.0)
_BACKGROUND_COLOR = (0.05, 0.05, 0.1, 1.0)
_INTERIOR_LIGHT_AREA_PER_LIGHT = 22.5  # m² per ceiling OmniLight3D (Quality A)

# Player spawn offset (FIX-1): player sits at (0, PLAYER_SPAWN_Y, 0)
# to be clear of the floor (top at y=0) and props.
_PLAYER_SPAWN_Y = 1.2  # capsule rests on floor (bottom at y≈0): centre = height/2 + radius = 0.9 + 0.3

# Props within this radius of (0,0,0) on the XZ plane are pushed away
# from the player spawn (FIX-1e).  1.0 m is enough to avoid sitting
# directly on the player.
_PLAYER_CLEAR_RADIUS = 1.0


# ── Helper functions (defined before data structures that use them) ─

def _fmt_pos(v: float) -> str:
    """Format a position value: 0.0 → 0, 1.0 → 1, 0.5 → 0.5."""
    if v == int(v):
        return str(int(v))
    return str(v)


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
) -> List[dict]:
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
    return [
    # Environment for WorldEnvironment (Item 1)
    # B2: Extended with ACES tonemap, SSAO, bloom, fog, exposure
    {"id": "world_env", "type": "Environment",
     "props": [
         "background_mode = 1",
         f"background_color = Color({bg[0]}, {bg[1]}, {bg[2]}, {bg[3]})",
         "ambient_light_source = 1",
         f"ambient_light_color = Color({amb[0]}, {amb[1]}, {amb[2]}, {amb[3]})",
         f"ambient_light_energy = {ambient_energy}",
         # B2: ACES tonemap
         "tonemap_mode = 3",
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
         "glow_intensity = 0.35",
         "glow_strength = 1.0",
         "glow_bloom = 0.0",
         "glow_blend_mode = 2",
         "glow_hdr_bleed_threshold = 1.0",
         "glow_hdr_bleed_scale = 2.0",
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
    # BoxMeshes for visible room shell (sized by room_w, room_d)
    {"id": "floor_vis_mesh", "type": "BoxMesh",
     "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(floor_t)}, {_fmt_pos(room_d)})"]},
    {"id": "wall_ns_mesh", "type": "BoxMesh",
     "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(room_h)}, {_fmt_pos(wall_t)})"]},
    {"id": "wall_ew_mesh", "type": "BoxMesh",
     "props": [f"size = Vector3({_fmt_pos(wall_t)}, {_fmt_pos(room_h)}, {_fmt_pos(room_d)})"]},
    {"id": "ceiling_mesh", "type": "BoxMesh",
     "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(floor_t)}, {_fmt_pos(room_d)})"]},
    # Fix-Batch-1 Task 4: Shell tileable texture sub_resources.
    # Each loads from res://assets/shell_*_*.png at scene-load time.
    # When the PNGs are missing, Godot falls back to a 1×1 white texture
    # so the albedo_color tint still renders a readable surface.
    {"id": "tex_floor_a", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_floor_albedo.png"']},
    {"id": "tex_floor_n", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_floor_normal.png"']},
    {"id": "tex_floor_o", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_floor_orm.png"']},
    {"id": "tex_wall_a", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_wall_albedo.png"']},
    {"id": "tex_wall_n", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_wall_normal.png"']},
    {"id": "tex_wall_o", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_wall_orm.png"']},
    {"id": "tex_ceil_a", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_ceiling_albedo.png"']},
    {"id": "tex_ceil_n", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_ceiling_normal.png"']},
    {"id": "tex_ceil_o", "type": "CompressedTexture2D",
     "props": ['load_path = "res://assets/shell_ceiling_orm.png"']},
    # StandardMaterial3Ds — E1: per-theme shell materials with roughness
    # uv1_scale set for tiling when baked textures are wired in.
    # Fix-Batch-1 Task 4: wire real textures (albedo + normal + ORM)
    # keeping per-theme albedo_color as a tint multiplier.
    {"id": "floor_mat", "type": "StandardMaterial3D",
     "props": [
         f"albedo_color = Color({sf['albedo'][0]}, {sf['albedo'][1]}, {sf['albedo'][2]}, 1)",
         "albedo_texture = SubResource(\"tex_floor_a\")",
         f"roughness = {sf['roughness']}",
         "roughness_texture = SubResource(\"tex_floor_o\")",
         "roughness_texture_channel = 1",
         "ao_texture = SubResource(\"tex_floor_o\")",
         "ao_texture_channel = 0",
         "normal_texture = SubResource(\"tex_floor_n\")",
         "uv1_scale = Vector3(10, 10, 10)",
     ]},
    {"id": "wall_mat", "type": "StandardMaterial3D",
     "props": [
         f"albedo_color = Color({sw['albedo'][0]}, {sw['albedo'][1]}, {sw['albedo'][2]}, 1)",
         "albedo_texture = SubResource(\"tex_wall_a\")",
         f"roughness = {sw['roughness']}",
         "roughness_texture = SubResource(\"tex_wall_o\")",
         "roughness_texture_channel = 1",
         "ao_texture = SubResource(\"tex_wall_o\")",
         "ao_texture_channel = 0",
         "normal_texture = SubResource(\"tex_wall_n\")",
         "uv1_scale = Vector3(10, 10, 10)",
         "cull_mode = 2",
     ]},
    {"id": "ceiling_mat", "type": "StandardMaterial3D",
     "props": [
         f"albedo_color = Color({sc['albedo'][0]}, {sc['albedo'][1]}, {sc['albedo'][2]}, 1)",
         "albedo_texture = SubResource(\"tex_ceil_a\")",
         f"roughness = {sc['roughness']}",
         "roughness_texture = SubResource(\"tex_ceil_o\")",
         "roughness_texture_channel = 1",
         "ao_texture = SubResource(\"tex_ceil_o\")",
         "ao_texture_channel = 0",
         "normal_texture = SubResource(\"tex_ceil_n\")",
         "uv1_scale = Vector3(10, 10, 10)",
         "cull_mode = 2",
     ]},
    # Player visible body (Item 4)
    {"id": "player_body_mesh", "type": "CapsuleMesh",
     "props": ["radius = 0.3", "height = 1.8"]},
    {"id": "player_body_mat", "type": "StandardMaterial3D",
     "props": ["albedo_color = Color(0.2, 0.3, 0.5, 1)"]},
    # CB-3: NavigationMesh for NPC pathfinding — covers the walkable floor
    # area (room_w × room_d, minus wall margins), at y=0.
    {"id": "nav_mesh", "type": "NavigationMesh",
     "props": [
         "vertices = PackedVector3Array("
         + f"{_fmt_pos(-room_w/2 + 1.2)}, 0, {_fmt_pos(-room_d/2 + 1.2)}, "
         + f"{_fmt_pos(room_w/2 - 1.2)}, 0, {_fmt_pos(-room_d/2 + 1.2)}, "
         + f"{_fmt_pos(room_w/2 - 1.2)}, 0, {_fmt_pos(room_d/2 - 1.2)}, "
         + f"{_fmt_pos(-room_w/2 + 1.2)}, 0, {_fmt_pos(room_d/2 - 1.2)})",
         "polygons = [\nPackedInt32Array(0, 1, 2),\nPackedInt32Array(0, 2, 3)\n]",
         "agent_radius = 0.3",
         "agent_height = 2.0",
         "agent_max_slope = 45.0",
         "agent_max_climb = 0.3",
         "cell_size = 0.3",
     ]},
    # CB-4: Door visual mesh + material (shared by all door entities)
    {"id": "door_mesh", "type": "BoxMesh",
     "props": ["size = Vector3(0.1, 2.4, 1.8)"]},
    {"id": "door_mat", "type": "StandardMaterial3D",
     "props": [
         "albedo_color = Color(0.35, 0.22, 0.12, 1)",
         "roughness = 0.8",
         "metallic = 0.0",
     ]},
    # Collision shapes for walls
    {"id": "wall_ns_shape", "type": "BoxShape3D",
     "props": [f"size = Vector3({_fmt_pos(room_w)}, {_fmt_pos(room_h)}, {_fmt_pos(wall_t)})"]},
    {"id": "wall_ew_shape", "type": "BoxShape3D",
     "props": [f"size = Vector3({_fmt_pos(wall_t)}, {_fmt_pos(room_h)}, {_fmt_pos(room_d)})"]},
]

# Quality A: Interior lighting — ceiling-mounted OmniLight3D nodes.
# Placed evenly across the ceiling to light the room interior.

def _build_interior_lights(
    room_w: float, room_d: float, room_h: float,
    interior_color: tuple, interior_energy: float,
) -> List[dict]:
    """Build interior OmniLight3D nodes for ceiling-mounted room lights.
    
    One light per ~_INTERIOR_LIGHT_AREA_PER_LIGHT m² (at least 1),
    placed near the ceiling (y = room_h - 0.4), with range ≈ room
    diagonal."""
    area = room_w * room_d
    n_lights = max(1, int(area / _INTERIOR_LIGHT_AREA_PER_LIGHT + 0.5))
    room_diag = (room_w * room_w + room_d * room_d) ** 0.5
    light_y = room_h - 0.4
    
    lights: list[dict] = []
    # Distribute lights in a grid: √n × √n
    grid = max(1, int(n_lights ** 0.5 + 0.5))
    # Recalculate so we get an even-ish grid
    cols = grid
    rows = max(1, (n_lights + cols - 1) // cols)
    for i in range(n_lights):
        col = i % cols
        row = i // cols
        # Even spacing across the room, shrinking margins for the grid
        x = (col - (cols - 1) / 2.0) * (room_w / max(cols, 1)) * 0.7
        z = (row - (rows - 1) / 2.0) * (room_d / max(rows, 1)) * 0.7
        light_name = f"InteriorLight{i}" if n_lights > 1 else "InteriorLight"
        lights.append({
            "name": light_name, "type": "OmniLight3D", "parent": ".",
            "props": [
                f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_fmt_pos(x)}, {_fmt_pos(light_y)}, {_fmt_pos(z)})",
                f"light_color = Color({interior_color[0]}, {interior_color[1]}, {interior_color[2]}, 1)",
                f"light_energy = {interior_energy}",
                f"omni_range = {_fmt_pos(room_diag)}",
                "shadow_enabled = true",
            ],
        })
    return lights


# ── Room node builder (Items 1-2) ─────────────────────────────────
# Built per-call so room_size can vary.

def _build_room_nodes(
    room_w: float, room_d: float,
    room_h: float = _ROOM_HEIGHT,
    directional_color: tuple | None = None,
    directional_energy: float | None = None,
    is_outdoor: bool = False,
) -> List[dict]:
    """Build the list of room nodes (lights, meshes, walls) for the
    given dimensions.

    P-G: *directional_color* and *directional_energy* override the
    default DirectionalLight3D (per-theme lighting).

    CB-7: When *is_outdoor* is True, skips walls and ceiling, and
    adds an outdoor ground plane MeshInstance3D."""
    light_nodes: list[dict] = [
    # WorldEnvironment (Item 1)
    {"name": "WorldEnvironment", "type": "WorldEnvironment", "parent": ".",
     "props": ['environment = SubResource("world_env")']},
    ]
    # DirectionalLight3D (Item 1) — P-G: per-theme colour + energy
    dl_props = [
        f"transform = Transform3D(0.866025, -0.433013, 0.25, 0, 0.5, 0.866025, -0.5, -0.75, 0.433013, 0, {_fmt_pos(_LIGHT_HEIGHT)}, 0)",
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

    if is_outdoor:
        # CB-7: Outdoor — ground plane only, no walls or ceiling
        return light_nodes + common_nodes + [
            {"name": "GroundPlane", "type": "MeshInstance3D", "parent": ".",
             "props": [
                 f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -{_fmt_pos(_OUTDOOR_GROUND_THICKNESS / 2)}, 0)",
                 'mesh = SubResource("floor_vis_mesh")',
                 'surface_material_override/0 = SubResource("floor_mat")',
             ]},
        ]

    return light_nodes + common_nodes + [
        # Visible floor mesh (child of existing Floor StaticBody3D)
        {"name": "FloorMesh", "type": "MeshInstance3D", "parent": "Floor",
         "props": [
             'mesh = SubResource("floor_vis_mesh")',
             'surface_material_override/0 = SubResource("floor_mat")',
         ]},
        # North wall (z = -room_d/2)
        {"name": "WallN", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {_fmt_pos(room_h / 2)}, {_fmt_pos(-room_d / 2)})",
         ]},
        # South wall (z = +room_d/2)
        {"name": "WallS", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {_fmt_pos(room_h / 2)}, {_fmt_pos(room_d / 2)})",
         ]},
        # East wall (x = +room_w/2)
        {"name": "WallE", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_fmt_pos(room_w / 2)}, {_fmt_pos(room_h / 2)}, 0)",
         ]},
        # West wall (x = -room_w/2)
        {"name": "WallW", "type": "StaticBody3D", "parent": ".",
         "props": [
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_fmt_pos(-room_w / 2)}, {_fmt_pos(room_h / 2)}, 0)",
         ]},
        # Ceiling
        {"name": "Ceiling", "type": "MeshInstance3D", "parent": ".",
         "props": [
             f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {_fmt_pos(room_h)}, 0)",
             'mesh = SubResource("ceiling_mesh")',
             'surface_material_override/0 = SubResource("ceiling_mat")',
         ]},
    ]

# ── Wall collision children definitions ───────────────────────────

_WALL_COLLISION_NODES: List[dict] = [
    {"name": "WallN_collision", "type": "CollisionShape3D", "parent": "WallN",
     "shape": "wall_ns_shape"},
    {"name": "WallS_collision", "type": "CollisionShape3D", "parent": "WallS",
     "shape": "wall_ns_shape"},
    {"name": "WallE_collision", "type": "CollisionShape3D", "parent": "WallE",
     "shape": "wall_ew_shape"},
    {"name": "WallW_collision", "type": "CollisionShape3D", "parent": "WallW",
     "shape": "wall_ew_shape"},
]

_WALL_MESH_NODES: List[dict] = [
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


def _resolve_unique_glbs(manifest: List[PlacedEntity]) -> List[Tuple[str, str]]:
    """Return sorted unique (category, material) pairs from the manifest."""
    seen: set[Tuple[str, str]] = set()
    result: list[Tuple[str, str]] = []
    for entry in manifest:
        pair = (entry.get("category", "?"), entry.get("material", "default"))
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    result.sort()
    return result


def resolve_unique_glbs_with_npc(manifest: List[PlacedEntity]) -> List[Tuple[str, str]]:
    """Return sorted unique (category, material) pairs INCLUDING the NPC body.

    This is the single source of truth for which GLBs a compiled scene
    references. Used by both compile_scene() (to emit ext_resource blocks)
    and scaffold.py (to copy the correct asset family per GLB).
    """
    unique = _resolve_unique_glbs(manifest)
    npc_pair = (_NPC_BODY_CATEGORY, _NPC_BODY_MATERIAL)
    if npc_pair not in unique:
        unique.append(npc_pair)
        unique.sort()
    return unique


def _ext_resource_block(unique_glbs: List[Tuple[str, str]], assets_subdir: str) -> str:
    """Build the [ext_resource] header block for unique GLBs.

    Omits the ``uid`` attribute intentionally — Godot auto-generates
    UIDs on import, and omitting them keeps the output deterministic
    (same input → byte-identical .tscn).
    """
    lines: list[str] = []
    for idx, (category, material) in enumerate(unique_glbs, start=1):
        path = _glb_res_path(category, material, assets_subdir)
        lines.append(
            f'[ext_resource type="PackedScene" path="{path}" id="{idx}"]'
        )
    return "\n".join(lines)


def _guard_player_spawn(x: float, z: float) -> Tuple[float, float]:
    """If (x,z) is too close to the player spawn at (0,0), push it away.

    Returns (adjusted_x, adjusted_z).  Safe to call with default values.
    """
    dist = (x * x + z * z) ** 0.5
    if dist < _PLAYER_CLEAR_RADIUS:
        if dist < 0.001:
            return (_PLAYER_CLEAR_RADIUS, 0.0)
        scale = _PLAYER_CLEAR_RADIUS / dist
        return (x * scale, z * scale)
    return (x, z)


def _prop_half_extents(category: str) -> Tuple[float, float, float]:
    """Return half-extents (hx, hy, hz) for a prop's AABB from its category."""
    sx, sy, sz = COLLISION_SIZES.get(category, COLLISION_SIZES["?"])
    return (sx / 2.0, sy / 2.0, sz / 2.0)


_NPC_CLEARANCE = 0.6  # Quality B1: min distance from NPC to prop/player/other NPC


def _find_open_npc_positions(
    quest_specs: list[dict],
    manifest: list[dict],
    room_w: float,
    room_d: float,
    seed: int = 42,
) -> list[tuple[float, float]]:
    """Quality B1: Find open-floor (x,z) positions for NPCs with clearance
    from prop footprints and player spawn (0,0).  Distributes NPCs across
    the room instead of clustering them on the back wall."""
    import random as _random
    _rng = _random.Random(seed)

    npc_hx, _, npc_hz = _prop_half_extents("humanoid")
    clearance = _NPC_CLEARANCE

    # Collect prop footprints: (x, z, half_x, half_z) for separable props
    prop_footprints: list[tuple[float, float, float, float]] = []
    for entry in manifest:
        if entry.get("surface") == "underlay" or entry.get("decor"):
            continue
        hx, _, hz = _prop_half_extents(entry.get("category", "?"))
        prop_footprints.append((
            entry.get("x", 0.0), entry.get("z", 0.0),
            hx + clearance, hz + clearance,
        ))

    def _overlaps(px: float, pz: float, ox: float, oz: float, ohx: float, ohz: float) -> bool:
        return abs(px - ox) < (npc_hx + ohx) and abs(pz - oz) < (npc_hz + ohz)

    def _valid_npc_spot(x: float, z: float, placed: list[tuple[float, float]]) -> bool:
        # Clear of player spawn
        if abs(x) < (_PLAYER_CLEAR_RADIUS + npc_hx) and abs(z) < (_PLAYER_CLEAR_RADIUS + npc_hz):
            return False
        # Clear of prop footprints
        for (px, pz, phx, phz) in prop_footprints:
            if _overlaps(x, z, px, pz, phx, phz):
                return False
        # Clear of other NPCs
        for (ox, oz) in placed:
            if _overlaps(x, z, ox, oz, npc_hx + clearance, npc_hz + clearance):
                return False
        return True

    n_npcs = len(quest_specs)
    positions: list[tuple[float, float]] = []

    # Try a set of candidate positions spread across the room
    half_w = room_w / 2.0 - 0.5
    half_d = room_d / 2.0 - 0.5
    # Generate candidates: spread across the room in a rough grid
    candidates: list[tuple[float, float]] = []
    for row in range(-2, 3):
        for col in range(-2, 3):
            x = col * half_w * 0.45
            z = row * half_d * 0.4
            candidates.append((x, z))
    _rng.shuffle(candidates)

    for _ in range(n_npcs):
        found = False
        for cx, cz in candidates:
            if (cx, cz) not in positions and _valid_npc_spot(cx, cz, positions):
                positions.append((cx, cz))
                found = True
                break
        if not found:
            # Fallback: place at back of room spread along X
            x = (_rng.random() * half_w * 1.5 - half_w * 0.75)
            z = -half_d + 0.8
            # Ensure not on top of another NPC
            attempts = 0
            while not _valid_npc_spot(x, z, positions) and attempts < 50:
                x = (_rng.random() * half_w * 1.5 - half_w * 0.75)
                z = -half_d + 0.8
                attempts += 1
            positions.append((x, z))

    return positions


def _resolve_prop_overlaps(
    manifest: List[dict],
    npc_x: float = 0.0,
    npc_z: float = -2.0,
    max_iterations: int = 20,
) -> List[dict]:
    """Deterministic AABB separation pass (Item 3).

    Pushes overlapping props apart so they don't intersect each other
    or the NPC.  Processes in sorted entity-id order for determinism.
    Uses axis-aligned bounding boxes from ``COLLISION_SIZES`` on the
    XZ plane (ignoring Y).

    Returns a **new** list of manifest entries with updated x,z
    positions.
    """
    # Work on a full copy — all entries returned, but only
    # separable entries (non-underlay, non-decor) participate in
    # collision checking.
    result: list[dict] = [dict(e) for e in manifest]

    # Indices of entries that participate in separation
    separable = [
        i for i, e in enumerate(result)
        if e.get("surface") != "underlay" and not e.get("decor")
    ]

    if len(separable) == 0:
        return result  # no separable props to check

    # NPC half-extents (humanoid)
    npc_hx, _, npc_hz = _prop_half_extents("humanoid")

    # Build list of (index, hx, hz) for quick lookup
    prop_data: list[Tuple[int, float, float]] = []
    for i, entry in enumerate(result):
        cat = entry.get("category", "?")
        hx, _, hz = _prop_half_extents(cat)
        prop_data.append((i, hx, hz))

    for _iteration in range(max_iterations):
        moved = False

        # Process only separable indices in sorted entity-id order
        separable_sorted = sorted(separable, key=lambda i: result[i].get("id", ""))

        for idx in separable_sorted:
            entry = result[idx]
            _, hx, hz = prop_data[idx]  # (i, half_x, half_z)
            px = entry.get("x", 0.0)
            pz = entry.get("z", 0.0)

            # Check against NPC.  NPC doesn't move, so push full overlap.
            # Use <= to handle same-position case deterministically.
            ox = (hx + npc_hx) - abs(px - npc_x)
            oz = (hz + npc_hz) - abs(pz - npc_z)
            if ox > 0 and oz > 0:
                moved = True
                if ox < oz:
                    push = ox + 0.01
                    if px <= npc_x:
                        entry["x"] = px - push
                    else:
                        entry["x"] = px + push
                else:
                    push = oz + 0.01
                    if pz <= npc_z:
                        entry["z"] = pz - push
                    else:
                        entry["z"] = pz + push
                px = entry.get("x", px)
                pz = entry.get("z", pz)

            # Check against previously placed separable props
            for other_idx in separable_sorted:
                if other_idx >= idx:
                    break
                other = result[other_idx]
                _, other_hx, other_hz = prop_data[other_idx]
                ox = (hx + other_hx) - abs(px - other.get("x", 0.0))
                oz = (hz + other_hz) - abs(pz - other.get("z", 0.0))
                if ox > 0 and oz > 0:
                    moved = True
                    if ox < oz:
                        push = ox / 2.0 + 0.01
                        if px < other.get("x", 0.0):
                            entry["x"] = px - push
                        else:
                            entry["x"] = px + push
                    else:
                        push = oz / 2.0 + 0.01
                        if pz < other.get("z", 0.0):
                            entry["z"] = pz - push
                        else:
                            entry["z"] = pz + push
                    px = entry.get("x", px)
                    pz = entry.get("z", pz)

        if not moved:
            break

    return result


def compile_scene(
    quest_specs: list[dict],
    manifest: List[PlacedEntity],
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
        room_type: "indoor" (walls+ceiling) or "outdoor" (terrain floor,
                   no walls, biome atmosphere).  CB-7.
        exterior_plan: For outdoor rooms, the ExteriorPlan dict from
                       exterior_planner (field, biome, scatter_placements).

    Returns:
        The *output_path* (so callers can assert the file was written).

    P-G: When *theme* is provided, derives DirectionalLight + ambient
    colours/energy from the per-theme LIGHTING_TABLE in room_control.
    """
    # C-4 backward compat: wrap single dict in list
    if isinstance(quest_specs, dict):
        quest_specs = [quest_specs]

    unique_glbs = resolve_unique_glbs_with_npc(manifest)

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
        from room_graph import get_doors_for_room, door_position_on_wall
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

    # ── P-G: Resolve per-theme lighting ─────────────────────
    ambient_override = None
    ambient_energy_override = 0.5
    background_override = None
    dir_color_override = None
    dir_energy_override = None
    interior_color_override: tuple = (1.0, 0.7, 0.35)
    interior_energy_override = 1.5
    fog_color_override = None
    fog_density_override = 0.015
    fog_light_energy_override = 0.5
    exposure_override = 1.0
    if theme:
        from room_control import get_lighting, get_shell_material
        lighting = get_lighting(theme)
        ambient_override = tuple(lighting["ambient_color"])
        ambient_energy_override = float(lighting.get("ambient_light_energy", 0.5))
        background_override = tuple(lighting["background_color"])
        dir_color_override = tuple(lighting["directional_color"])
        dir_energy_override = float(lighting["directional_energy"])
        # Quality A: interior lighting
        interior_color_override = tuple(lighting.get("interior_light_color", (1.0, 0.7, 0.35)))
        interior_energy_override = float(lighting.get("interior_light_energy", 1.5))
        # B2: per-theme fog + exposure
        fog_color_override = tuple(lighting.get("fog_color", (0.2, 0.18, 0.22, 1.0)))
        fog_density_override = float(lighting.get("fog_density", 0.015))
        fog_light_energy_override = float(lighting.get("fog_light_energy", 0.5))
        exposure_override = float(lighting.get("exposure", 1.0))

    # ── Build room resources for resolved dimensions ───────────
    # Quality A: build interior lights from resolved theme params
    interior_lights = _build_interior_lights(
        room_w, room_d, _ROOM_HEIGHT,
        interior_color_override, interior_energy_override,
    )
    # E1: per-theme shell materials
    shell_floor = None
    shell_wall = None
    shell_ceiling = None
    if theme:
        shell_floor = get_shell_material(theme, "floor")
        shell_wall = get_shell_material(theme, "wall")
        shell_ceiling = get_shell_material(theme, "ceiling")

    # CB-7: Outdoor atmosphere from exterior_plan biome
    if is_outdoor and exterior_plan:
        biome = exterior_plan.get("biome", {})
        atmos = biome.get("atmosphere", {})
        if atmos:
            fc = atmos.get("fog_color", (0.66, 0.72, 0.7))
            fog_color_override = tuple(fc) if len(fc) >= 3 else (fc[0], fc[1], fc[2])
            if len(fog_color_override) == 3:
                fog_color_override = (*fog_color_override, 1.0)
            fog_density_override = float(atmos.get("fog_density", 0.01))
            fog_light_energy_override = float(atmos.get("fog_light_energy", 0.8))
            exposure_override = float(atmos.get("exposure", 1.2))
            se = atmos.get("sun_energy", 1.2)
            if dir_energy_override is None:
                dir_energy_override = float(se)
            st = atmos.get("sky_tint", (0.62, 0.74, 0.88))
            if background_override is None:
                background_override = (*tuple(st), 1.0) if len(st) >= 3 else (st[0], st[1], st[2], 1.0)
            if ambient_override is None:
                ambient_override = (*tuple(st), 1.0) if len(st) >= 3 else (st[0], st[1], st[2], 1.0)
            if interior_color_override is None:
                interior_color_override = (0.9, 0.85, 0.7)
            if interior_energy_override is None:
                interior_energy_override = 1.2

    room_sub_resources = _build_room_sub_resources(
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
    )
    room_nodes = _build_room_nodes(
        room_w, room_d,
        directional_color=dir_color_override,
        directional_energy=dir_energy_override,
        is_outdoor=is_outdoor,
    )

    # ── No-clip placement pass (Item 3) ─────────────────────────
    # Deterministic AABB separation so props don't intersect each
    # other or the NPC.  Skips underlay and decor entries.
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

    # ── Write quest data as a JSON file alongside the .tscn ──────
    output_dir = str(Path(output_path).parent)
    tscn_stem = Path(output_path).stem
    data_filename = f"{tscn_stem}_quest_data.json"
    data_path = str(Path(output_dir) / data_filename)
    # C-3: world log path for NPC quest-state persistence
    world_log_filename = f"{tscn_stem}_world_log.jsonl"
    world_log_path = str(Path(output_dir) / world_log_filename)

    # C-4: Build per-NPC quest data and placements for the shared JSON.
    from soul import default_soul
    npcs_data: dict = {}
    
    # Quality B1: Compute NPC positions by finding open floor spots
    # with at least 0.6 m clearance from every prop footprint.
    npc_positions = _find_open_npc_positions(
        quest_specs, separated_manifest, room_w, room_d,
    )
    
    # CB-3: Generate per-NPC needs from npc_sim
    from npc_sim import generate_npc_needs
    npc_needs_list = generate_npc_needs(len(quest_specs))
    
    for i, spec in enumerate(quest_specs):
        npc_id = spec.get("npc_id", f"npc_{i}")
        npc_pos_x, npc_pos_z = npc_positions[i]
        # Spine Slice 3: bake soul into quest_data
        npc_soul = spec.get("soul", default_soul())
        # CB-3: attach needs to NPC data
        npc_needs = npc_needs_list[i]
        placement: dict = {
            "id": npc_id,
            "asset_hash": f"{_NPC_BODY_CATEGORY}_{_NPC_BODY_MATERIAL}",
            "attrs": {
                "role": spec.get("npc_role", "villager"),
                "npc_state": "idle",
                "x": npc_pos_x,
                "y": 0.0,
                "z": npc_pos_z,
            },
        }
        npcs_data[npc_id] = {
            **spec,
            "soul": npc_soul,
            "npc_placement": placement,
            "needs": npc_needs,  # CB-3: per-NPC needs
        }
        # C-3: Initialise the world log with this NPC's starting state
        _init_world_log(world_log_path, placement)

    # EB-6: Build examine flavour text for all props
    examine_flavour: dict[str, str] = {}
    from examine_validator import _category_fallback
    for entry in manifest:
        eid = entry.get("id", "")
        cat = entry.get("category", "?")
        examine_flavour[eid] = _category_fallback(cat)

    # CB-5: Generate emergent events for this room
    events_data: list[dict] = []
    from world_events import fire_events
    npc_ids = [spec.get("npc_id", f"npc_{i}") for i, spec in enumerate(quest_specs)]
    all_rooms = [(0, 0)]
    if room_graph:
        all_rooms = [tuple(r) for r in room_graph.get("rooms", [(0, 0)])]
    epicentre = current_room if current_room else (0, 0)
    manifest_entity_ids = [e.get("id", "") for e in manifest if not e.get("decor")]
    events_data = fire_events(
        num_events=1,
        time_of_day="day",  # default; runtime may override
        tick_count=0,
        needs=npc_needs_list[0] if npc_needs_list else None,
        epicentre=epicentre,
        all_rooms=all_rooms,
        existing_npc_ids=npc_ids,
        manifest_entities=manifest_entity_ids,
        seed=42,
    )

    quest_data: dict = {
        "npcs": npcs_data,
        "world_log_path": world_log_path,
        "examine": examine_flavour,
        "events": events_data,  # CB-5: emergent events
        "enemies": [
            {"enemy_id": e["id"], "archetype": "golem",
             "health": 50.0, "damage": 8.0,
             "x": e.get("x", 0), "z": e.get("z", 0)}
            for e in manifest if e.get("category") == "enemy"
        ],  # CB-6: enemy specs
    }
    Path(data_path).write_text(
        json.dumps(quest_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # ── Build GLB id map ────────────────────────────────────────
    glb_ids: dict[Tuple[str, str], str] = {}
    for i, (cat, mat) in enumerate(unique_glbs, start=1):
        glb_ids[(cat, mat)] = str(i)

    # ── Build collision shape data for each interactable ────────
    # Map entity id → (sub_resource_id, size_tuple)
    collision_info: dict[str, Tuple[str, Tuple[float, float, float]]] = {}
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

    # Count room shell sub-resources for load_steps
    num_room_sub_resources = len(room_sub_resources)

    total_load_steps = (
        len(unique_glbs)                     # GLB ext_resources
        + len(_SHELL_SCRIPTS)                # shell scripts
        + len(used_tag_scripts)              # component scripts
        + num_sub_resources                  # collision sub_resources
        + num_room_sub_resources             # Environment + meshes + materials + wall shapes
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
    # ExtResources: shell scripts (P4)
    for entry in _SHELL_SCRIPTS:
        lines.append(
            f'[ext_resource type="Script" path="{entry["path"]}" id="{entry["id"]}"]'
        )
    # ExtResources: tag-based component scripts (P5)
    for path, script_id in sorted(used_tag_scripts.items()):
        lines.append(
            f'[ext_resource type="Script" path="{path}" id="{script_id}"]'
        )
    lines.append("")

    # ── SubResources: collision shapes (FIX-1) ──────────────────
    # Floor: BoxShape3D sized by room dimensions
    lines.append(f'[sub_resource type="BoxShape3D" id="{floor_sub_id}"]')
    lines.append(f"size = Vector3({_fmt_pos(room_w)}, 1, {_fmt_pos(room_d)})")
    lines.append("")

    # Player: CapsuleShape3D
    lines.append(f'[sub_resource type="CapsuleShape3D" id="{player_sub_id}"]')
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

    # Root (no parent attribute — Godot 4 convention)
    lines.append('[node name="Root" type="Node3D"]')
    lines.append("")

    # ── Floor node (FIX-1b) ─────────────────────────────────────
    # StaticBody3D sized by room dimensions, top at y=0 → centre at y=-0.5
    lines.append('[node name="Floor" type="StaticBody3D" parent="."]')
    lines.append(
        "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.5, 0)"
    )
    lines.append(f'[node name="FloorCollision" type="CollisionShape3D" parent="Floor"]')
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
        # Emit wall collision child if this is a wall body
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
        # Emit wall mesh child if this is a wall body
        wall_mesh = next(
            (wm for wm in _WALL_MESH_NODES if wm["parent"] == room_node["name"]),
            None,
        )
        if wall_mesh:
            lines.append(
                f'[node name="{wall_mesh["name"]}" type="{wall_mesh["type"]}" '
                f'parent="{wall_mesh["parent"]}"]'
            )
            lines.append(f'mesh = SubResource("{wall_mesh["mesh"]}")')
            lines.append(
                f'surface_material_override/0 = SubResource("{wall_mesh["mat"]}")'
            )
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
        # CB-2/CB-6: Determine tag — openable→open, enemy→enemy, others→decor/pickup
        from category_registry import REGISTRY
        entry = REGISTRY.get(cat, {})
        if cat == "enemy":
            tag = "enemy"
        elif not is_decor and entry.get("openable"):
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
            f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{_fmt_pos(x)}, {_fmt_pos(y)}, {_fmt_pos(z)})"
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
        lines.append("")

        # B2: Light-emitting prop child (OmniLight3D)
        if cat in _LIGHT_EMITTING:
            le = _LIGHT_EMITTING[cat]
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

        lines.append(f'[node name="{npc_id}" type="StaticBody3D" parent="."]')
        lines.append(
            f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, "
            f"{_fmt_pos(npc_x)}, {_fmt_pos(npc_y)}, {_fmt_pos(npc_z)})"
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
        lines.append(f'[node name="Skeleton" type="Skeleton3D" parent="{npc_id}"]')
        lines.append("")

        # CB-7: AnimationPlayer for idle/walk animations
        lines.append(f'[node name="AnimationPlayer" type="AnimationPlayer" parent="{npc_id}"]')
        lines.append('root_node = NodePath("../Skeleton")')
        lines.append("")

        # CB-7: BoneAttachment3D on Hips bone — carries the GLB body mesh
        lines.append(f'[node name="HipsAttachment" type="BoneAttachment3D" parent="{npc_id}"]')
        lines.append('bone_name = "Hips"')
        lines.append(f'skeleton = NodePath("../Skeleton")')
        lines.append("")

        # NPC body GLB instance — now attached to the Hips bone
        lines.append(
            f'[node name="Body" parent="{npc_id}/HipsAttachment" instance=ExtResource("{npc_glb_id}")]'
        )
        lines.append("")

        # NPC nameplate
        lines.append(f'[node name="Nameplate" type="Label3D" parent="{npc_id}"]')
        lines.append(f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2.0, 0)")
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
        f'[node name="PlayerCollision" type="CollisionShape3D" parent="Player"]'
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
            f"transform = Transform3D({_fmt_pos(cos_y)}, 0, {_fmt_pos(-sin_y)}, 0, 1, 0, {_fmt_pos(sin_y)}, 0, {_fmt_pos(cos_y)}, "
            f"{_fmt_pos(dx)}, {_fmt_pos(dy)}, {_fmt_pos(dz)})"
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

def _init_world_log(log_path: str, npc_placement: dict) -> None:
    """C-3: Write the NPC's initial state as the first event in
    the world log.  npc.gd replays this on scene load to restore
    quest state across reloads."""
    import json as _json
    from pathlib import Path as _Path
    event = {
        "action": "replace",
        "placement": npc_placement,
    }
    _Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    # C-4: Append (don't overwrite) so multiple NPC initial states accumulate
    with open(log_path, "a", encoding="utf-8") as _f:
        _f.write(_json.dumps(event) + "\n")


def read_quest_data(tscn_path: str) -> dict | None:
    """Read the quest_data.json file alongside a compiled .tscn.

    Returns the parsed dict or None if the JSON file is missing.
    """
    tscn = Path(tscn_path)
    data_file = tscn.with_name(f"{tscn.stem}_quest_data.json")
    if not data_file.exists():
        return None
    return json.loads(data_file.read_text(encoding="utf-8"))
