"""foundry.lighting_planner — deterministic motivated-lighting plan.

Derives interior light sources (hearth, torches, candles) + window openings +
environment from the Brief + room geometry + manifest. Engine-agnostic data,
consumed by build_room_shell (windows), scene_compiler (realtime rig + bake
scene_desc), and bake_lighting (interior emitters). Deterministic.
"""
from __future__ import annotations

_WARM_HEARTH = (1.0, 0.6, 0.3)
_WARM_TORCH = (1.0, 0.7, 0.4)
_WARM_CANDLE = (1.0, 0.8, 0.5)
_TABLE_CATS = {"table", "shelf", "desk", "cabinet"}
_TORCH_SPACING_M = 3.5
_CANDLE_MAX = 3
_TORCH_H = 2.2
_CANDLE_TOP_Y = 0.8


def plan_lighting(brief: dict, room_size: dict, manifest: list, seed: int = 0) -> dict:
    w = float(room_size["w"])
    d = float(room_size["d"])
    # Hearth on the longest wall (deterministic): N if w>=d else E.
    hearth_wall = "N" if w >= d else "E"
    sources: list[dict] = []

    # ── hearth ────────────────────────────────────────────────
    sources.append({
        "type": "hearth",
        "pos": _wall_point(hearth_wall, 0.5, w, d, y=0.5),
        "color": _WARM_HEARTH, "energy": 6.0, "range": 6.0, "flicker": True,
    })

    # ── torches: evenly spaced around the perimeter ───────────
    perim = 2 * (w + d)
    n_torch = max(2, int(perim / _TORCH_SPACING_M))
    for i in range(n_torch):
        wall, t = _perimeter_param(i / n_torch, w, d)
        sources.append({
            "type": "torch",
            "pos": _wall_point(wall, t, w, d, y=_TORCH_H),
            "color": _WARM_TORCH, "energy": 3.0, "range": 4.0, "flicker": True,
        })

    # ── candles on table-like surfaces (sorted for determinism) ─
    tables = sorted(
        (e for e in manifest if e.get("category") in _TABLE_CATS),
        key=lambda e: e.get("id", ""),
    )[:_CANDLE_MAX]
    for e in tables:
        sources.append({
            "type": "candle",
            "pos": (float(e.get("x", 0.0)), _CANDLE_TOP_Y, float(e.get("z", 0.0))),
            "color": _WARM_CANDLE, "energy": 1.2, "range": 1.5, "flicker": False,
        })

    # ── windows on the two walls perpendicular to the hearth ──
    win_walls = (["E", "W"] if hearth_wall in ("N", "S") else ["N", "S"])
    windows = [{
        "wall": wll, "center": 0.5,
        "width": min(1.2, (d if wll in ("E", "W") else w) - 1.0),
        "height": 1.4, "sill": 1.2,
    } for wll in win_walls]

    return {
        "sources": sources,
        "windows": windows,
        "sun": {"color": (0.5, 0.6, 0.85), "energy": 0.8,
                "direction": (-0.3, -0.6, -0.5)},
        "sky": {"top": (0.4, 0.45, 0.6), "ambient_energy": 0.4},
        "environment": {"ambient_color": (0.40, 0.40, 0.45), "ambient_energy": 0.6,
                        "fog_color": (0.15, 0.15, 0.20), "fog_energy": 0.1,
                        "tonemap": 2, "exposure": 1.2},
        "_hearth_wall": hearth_wall,
    }


def _wall_point(wall: str, t: float, w: float, d: float, y: float):
    """A point on `wall` at parameter t∈[0,1] along it, inset 0.15 m off the face."""
    inset = 0.15
    if wall == "N":   return (-w / 2 + t * w, y, -d / 2 + inset)
    if wall == "S":   return (-w / 2 + t * w, y, d / 2 - inset)
    if wall == "E":   return (w / 2 - inset, y, -d / 2 + t * d)
    return (-w / 2 + inset, y, -d / 2 + t * d)  # W


def _perimeter_param(frac: float, w: float, d: float):
    """Map frac∈[0,1) around the perimeter to (wall, t-along-wall)."""
    perim = 2 * (w + d)
    s = frac * perim
    if s < w:            return "N", s / w
    s -= w
    if s < d:            return "E", s / d
    s -= d
    if s < w:            return "S", s / w
    s -= w
    return "W", s / d
