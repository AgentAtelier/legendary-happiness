"""Deterministic room layout: (room plan) → placed-entity manifest.

No LLM. Floor furniture goes on a non-overlapping grid clear of the player
spawn (origin) and the NPC slot; rugs are floor underlays (overlap intended);
paintings hang on walls. Over-capacity is a Decision Point, never a clip.
"""
from __future__ import annotations

from typing import List, Tuple

from decisions import Choice, DecisionPoint, make_decision

CELL = 1.8            # grid cell pitch (m) — one furniture item per cell.
                      # Wider than the worst-case furniture footprint (~1.2 m)
                      # AND than the non-overlap proxy in the tests (1.6 m), so
                      # adjacent cells are robustly clear (no FP-boundary clips).
WALL_MARGIN = 0.8     # keep furniture this far from walls
FURNITURE = ("table", "chair", "shelf", "cabinet")
NPC_Z_INSET = 0.6     # NPC sits this far in from the back wall


def _expand(props: List[dict]) -> List[dict]:
    """props with counts → flat list of single entities, stable order."""
    out = []
    for p in props:
        for _ in range(int(p["count"])):
            out.append({"category": p["category"], "material": p["material"]})
    return out


def _grid_cells(w: float, d: float) -> List[Tuple[float, float]]:
    """Cell centres inside the room, excluding the player spawn (origin)
    and the NPC slot (back-centre)."""
    n_cols = max(1, int((w - 2 * WALL_MARGIN) // CELL))
    n_rows = max(1, int((d - 2 * WALL_MARGIN) // CELL))
    npc_z = -d / 2.0 + NPC_Z_INSET
    cells = []
    for r in range(n_rows):
        for c in range(n_cols):
            x = -(n_cols - 1) * CELL / 2.0 + c * CELL
            z = -(n_rows - 1) * CELL / 2.0 + r * CELL
            if abs(x) < CELL / 2.0 and abs(z) < CELL / 2.0:
                continue                       # player spawn at origin
            if abs(x) < CELL / 2.0 and abs(z - npc_z) < CELL / 2.0:
                continue                       # NPC slot
            cells.append((x, z))
    return cells


def layout_room(plan: dict) -> Tuple[List[dict], dict, List[DecisionPoint]]:
    room_size = plan["room_size"]
    w, d = float(room_size["w"]), float(room_size["d"])
    entities = _expand(plan.get("props", []))
    decisions: List[DecisionPoint] = []
    manifest: List[dict] = []

    furniture = [e for e in entities if e["category"] in FURNITURE]
    rugs = [e for e in entities if e["category"] == "rug"]
    paintings = [e for e in entities if e["category"] == "painting"]

    # ── Floor furniture on the grid ──────────────────────────
    cells = _grid_cells(w, d)
    placed = furniture[: len(cells)]
    dropped = len(furniture) - len(placed)
    for i, (e, (x, z)) in enumerate(zip(placed, cells)):
        manifest.append({"id": f"{e['category']}_{i}", "category": e["category"],
                         "material": e["material"], "x": round(x, 3), "y": 0.0,
                         "z": round(z, 3), "yaw": 0.0, "surface": "floor",
                         "decor": False})
    if dropped > 0:
        decisions.append(make_decision(
            "room.over_capacity", stage="room", severity="ambiguous",
            context={"placed": len(placed), "requested": len(furniture),
                     "dropped": dropped, "w": w, "d": d},
            choices=[Choice(label="Use a larger room",
                            plain="Grow the room to fit the furniture",
                            apply={"field": "room_size"}),
                     Choice(label="Reduce the prop count",
                            plain="Ask for fewer furnishings",
                            apply={"field": "props"})],
        ))

    # ── Rugs: floor underlays, centred, overlap intended ─────
    for i, e in enumerate(rugs):
        manifest.append({"id": f"rug_{i}", "category": "rug", "material": e["material"],
                         "x": 0.0, "y": 0.01, "z": 0.0, "yaw": 0.0,
                         "surface": "underlay", "decor": True})

    # ── Paintings: hung on walls, facing inward ──────────────
    # Distribute along the back wall (z = -d/2), then side walls.
    walls = [("back", 0.0, -d / 2.0 + 0.05, 0.0),
             ("left", -w / 2.0 + 0.05, 0.0, 1.5708),
             ("right", w / 2.0 - 0.05, 0.0, -1.5708)]
    for i, e in enumerate(paintings):
        _, wx, wz, yaw = walls[i % len(walls)]
        manifest.append({"id": f"painting_{i}", "category": "painting",
                         "material": e["material"], "x": round(wx, 3), "y": 1.5,
                         "z": round(wz, 3), "yaw": yaw, "surface": "wall",
                         "decor": True})

    return manifest, {"w": w, "d": d}, decisions
