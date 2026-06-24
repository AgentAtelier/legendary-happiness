"""foundry.lighting_resolve — lighting cascade resolution for the scene compiler.

Extracted from scene_compiler.py (Phase 1.4).  Collapses the 6×
``if X is None or lighting_plan is None`` cascade into a single
``_resolve_lighting()`` call that returns a flat dict of resolved
overrides.  Also provides a module-level ``DEFAULT_LIGHTING_ENV``
for consistent fallback defaults.

ROADMAP 1.5 / AUDIT-03 Q4.
"""

from __future__ import annotations

from comp_tags import _INTERIOR_LIGHT_AREA_PER_LIGHT
from tscn_writer import fmt_float, transform3d

# ═══════════════════════════════════════════════════════════════════
#  Default lighting environment (module-level constant)
# ═══════════════════════════════════════════════════════════════════

DEFAULT_LIGHTING_ENV: dict = {
    "ambient_color": (0.15, 0.15, 0.2, 1.0),
    "ambient_energy": 0.5,
    "background_color": (0.05, 0.05, 0.1, 1.0),
    "directional_color": None,
    "directional_energy": None,
    "fog_color": (0.2, 0.18, 0.22, 1.0),
    "fog_density": 0.015,
    "fog_light_energy": 0.5,
    "exposure": 1.0,
    "tonemap_mode": 3,
    "interior_light_color": (1.0, 0.7, 0.35),
    "interior_light_energy": 1.5,
}

# ═══════════════════════════════════════════════════════════════════
#  Interior light builder (grid-based ceiling lights)
# ═══════════════════════════════════════════════════════════════════


def _build_interior_lights(
    room_w: float, room_d: float, room_h: float,
    interior_color: tuple, interior_energy: float,
) -> list[dict]:
    """Build interior OmniLight3D nodes for ceiling-mounted room lights.

    One light per ~_INTERIOR_LIGHT_AREA_PER_LIGHT m² (at least 1),
    placed near the ceiling (y = room_h - 0.4), with range ≈ room
    diagonal.
    """
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
                f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (x, light_y, z))}",
                f"light_color = Color({interior_color[0]}, {interior_color[1]}, {interior_color[2]}, 1)",
                f"light_energy = {interior_energy}",
                f"omni_range = {fmt_float(room_diag)}",
                "shadow_enabled = false",
            ],
        })
    return lights


# ═══════════════════════════════════════════════════════════════════
#  Lighting cascade resolver
# ═══════════════════════════════════════════════════════════════════


def _resolve_lighting(
    lighting_plan: dict | None,
    theme: str | None,
    is_outdoor: bool,
    exterior_plan: dict | None,
    room_w: float,
    room_d: float,
    room_h: float = 3.0,
) -> dict:
    """Resolve all environment lighting overrides into a flat dict.

    Collapses the 6× ``if X is None or lighting_plan is None`` cascade
    that was previously inlined in ``compile_scene()``.  Priority:

    1. Default hard-wired values
    2. Generative lighting plan overrides (Task 3)
    3. Per-theme lighting table overrides
    4. Outdoor biome atmosphere overrides (CB-7)

    Returns a flat dict with keys matching the local variable names
    originally used by ``compile_scene``.
    """
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
    # Generative lighting plan overrides (Task 3)
    _plan_tonemap = None
    if lighting_plan is not None:
        lpenv = lighting_plan.get("environment", {})
        lpsun = lighting_plan.get("sun", {})
        ambient_override = (lpenv.get("ambient_color", (0.40, 0.40, 0.45)))[:3] + (1.0,)
        ambient_energy_override = float(lpenv.get("ambient_energy", 0.6))
        fog_color_override = (lpenv.get("fog_color", (0.15, 0.15, 0.20)))[:3] + (1.0,)
        fog_light_energy_override = float(lpenv.get("fog_energy", 0.1))
        exposure_override = float(lpenv.get("exposure", 1.2))
        # sun override: color + energy (keep the existing transform for direction)
        sun_color = lpsun.get("color", (0.5, 0.6, 0.85))
        dir_color_override = (sun_color[0], sun_color[1], sun_color[2])
        dir_energy_override = float(lpsun.get("energy", 0.8))
        # tonemap from plan
        _plan_tonemap = int(lpenv.get("tonemap", 2))
        # Build interior source lights from the plan (instead of grid-based ceiling lights)
        plan_sources = lighting_plan.get("sources", [])
        plan_omni_lights: list[dict] = []
        for i, src in enumerate(plan_sources):
            pos = src.get("pos", (0, 0, 0))
            color = src.get("color", (1, 1, 1))
            light_name = f"PlanLight{i}"
            plan_omni_lights.append({
                "name": light_name, "type": "OmniLight3D", "parent": ".",
                "props": [
                    f"transform = {transform3d((1,0,0,0,1,0,0,0,1), (pos[0], pos[1], pos[2]))}",
                    f"light_color = Color({color[0]}, {color[1]}, {color[2]}, 1)",
                    f"light_energy = {src.get('energy', 1.0)}",
                    f"omni_range = {src.get('range', 4.0)}",
                    "shadow_enabled = true",
                ],
            })
    else:
        plan_omni_lights = []

    if theme:
        from room_control import get_lighting
        lighting = get_lighting(theme)
        if ambient_override is None or lighting_plan is None:
            ambient_override = tuple(lighting["ambient_color"])
            ambient_energy_override = float(lighting.get("ambient_light_energy", 0.5))
        if background_override is None or lighting_plan is None:
            background_override = tuple(lighting["background_color"])
        if dir_color_override is None or lighting_plan is None:
            dir_color_override = tuple(lighting["directional_color"])
            dir_energy_override = float(lighting["directional_energy"])
        # Quality A: interior lighting (only when no lighting_plan)
        if lighting_plan is None:
            interior_color_override = tuple(lighting.get("interior_light_color", (1.0, 0.7, 0.35)))
            interior_energy_override = float(lighting.get("interior_light_energy", 1.5))
        # B2: per-theme fog + exposure (only when no lighting_plan override)
        if fog_color_override is None or lighting_plan is None:
            fog_color_override = tuple(lighting.get("fog_color", (0.2, 0.18, 0.22, 1.0)))
            fog_density_override = float(lighting.get("fog_density", 0.015))
            fog_light_energy_override = float(lighting.get("fog_light_energy", 0.5))
            exposure_override = float(lighting.get("exposure", 1.0))

    # Build interior lights from resolved properties
    if lighting_plan is not None:
        interior_lights = plan_omni_lights
    else:
        interior_lights = _build_interior_lights(
            room_w, room_d, room_h,
            interior_color_override, interior_energy_override,
        )

    # E1: per-theme shell materials
    shell_floor = None
    shell_wall = None
    shell_ceiling = None
    if theme:
        from room_control import get_shell_material
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

    return {
        "ambient_override": ambient_override,
        "ambient_energy_override": ambient_energy_override,
        "background_override": background_override,
        "dir_color_override": dir_color_override,
        "dir_energy_override": dir_energy_override,
        "fog_color_override": fog_color_override,
        "fog_density_override": fog_density_override,
        "fog_light_energy_override": fog_light_energy_override,
        "exposure_override": exposure_override,
        "interior_lights": interior_lights,
        "shell_floor": shell_floor,
        "shell_wall": shell_wall,
        "shell_ceiling": shell_ceiling,
        "_plan_tonemap": _plan_tonemap,
    }
