"""Deterministic room layout: (room plan) → placed-entity manifest.

No LLM. Floor furniture goes on a non-overlapping grid clear of the player
spawn (origin) and the NPC slot; rugs are floor underlays (overlap intended);
paintings hang on walls. Over-capacity is a Decision Point, never a clip.
"""
from __future__ import annotations

from typing import List, Tuple

from category_registry import FURNITURE, CARRYABLES, FURNITURE_TOP_Y
from decisions import Choice, DecisionPoint, make_decision

CELL = 1.8            # grid cell pitch (m) — one furniture item per cell.
                      # Wider than the worst-case furniture footprint (~1.2 m)
                      # AND than the non-overlap proxy in the tests (1.6 m), so
                      # adjacent cells are robustly clear (no FP-boundary clips).
WALL_MARGIN = 0.8     # keep furniture this far from walls
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
    and the NPC slot (back-centre).

    T-5: For small rooms, scale CELL down so the grid still produces
    ≥4 cells (enough for a minimal furnished room)."""
    usable_w = w - 2 * WALL_MARGIN
    usable_d = d - 2 * WALL_MARGIN
    # T-5: scale CELL for small rooms so we always get ≥2 cols and ≥2 rows
    scaled_cell = min(CELL, max(0.6, min(usable_w, usable_d) / 2.5))
    n_cols = max(1, int(usable_w // scaled_cell))
    n_rows = max(1, int(usable_d // scaled_cell))
    npc_z = -d / 2.0 + NPC_Z_INSET
    cells = []
    for r in range(n_rows):
        for c in range(n_cols):
            x = -(n_cols - 1) * scaled_cell / 2.0 + c * scaled_cell
            z = -(n_rows - 1) * scaled_cell / 2.0 + r * scaled_cell
            if abs(x) < scaled_cell / 2.0 and abs(z) < scaled_cell / 2.0:
                continue                       # player spawn at origin
            if abs(x) < scaled_cell / 2.0 and abs(z - npc_z) < scaled_cell / 2.0:
                continue                       # NPC slot
            cells.append((x, z))
    return cells


def layout_room(plan: dict, seed: int | None = None, npc_count: int = 1) -> Tuple[List[dict], dict, List[DecisionPoint]]:
    room_size = plan["room_size"]
    w, d = float(room_size["w"]), float(room_size["d"])
    entities = _expand(plan.get("props", []))
    decisions: List[DecisionPoint] = []
    manifest: List[dict] = []

    furniture = [e for e in entities if e["category"] in FURNITURE]
    rugs = [e for e in entities if e["category"] == "rug"]
    paintings = [e for e in entities if e["category"] == "painting"]
    carryables = [e for e in entities if e["category"] in CARRYABLES]

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
    walls = [("back", 0.0, -d / 2.0 + 0.05, 1.5708),
             ("left", -w / 2.0 + 0.05, 0.0, 1.5708),
             ("right", w / 2.0 - 0.05, 0.0, -1.5708)]
    for i, e in enumerate(paintings):
        _, wx, wz, yaw = walls[i % len(walls)]
        manifest.append({"id": f"painting_{i}", "category": "painting",
                         "material": e["material"], "x": round(wx, 3), "y": 1.5,
                         "z": round(wz, 3), "yaw": yaw, "surface": "wall",
                         "decor": True})

    # ── P-E: Carryables placed on furniture surfaces ─────────
    # Each carryable is placed on a furniture top if available,
    # else on the floor.  surface="on" with y offset above the furniture top.
    _FURNITURE_TOP_Y = FURNITURE_TOP_Y
    for i, e in enumerate(carryables):
        # Place on the i-th furniture item (wrap around)
        if i < len(placed):
            parent_entry = manifest[i]  # furniture was placed first
            px, pz = parent_entry["x"], parent_entry["z"]
            pcat = parent_entry["category"]
            top_y = _FURNITURE_TOP_Y.get(pcat, 0.8)
            # Small random offset on the surface (deterministic: use i as seed)
            ox = (i % 3 - 1) * 0.1
            oz = ((i // 3) % 3 - 1) * 0.1
            manifest.append({
                "id": f"{e['category']}_{i}",
                "category": e["category"],
                "material": e["material"],
                "x": round(px + ox, 3),
                "y": round(top_y + 0.02, 3),
                "z": round(pz + oz, 3),
                "yaw": 0.0,
                "surface": "on",
                "decor": False,
            })
        else:
            # No furniture left — place on floor near origin
            fx = (i * 0.15) % 1.0 - 0.5
            fz = ((i * 0.15) // 1.0) * 0.15 - 0.3
            manifest.append({
                "id": f"{e['category']}_{i}",
                "category": e["category"],
                "material": e["material"],
                "x": round(fx, 3),
                "y": 0.02,
                "z": round(fz, 3),
                "yaw": 0.0,
                "surface": "floor",
                "decor": False,
            })

    # ── EB-7: Guarantee ≥npc_count distinct carryables ────────
    # Multi-NPC rooms need at least npc_count pickable carryables
    # so each NPC can have a unique quest target. If the plan didn't
    # produce enough (or any), inject distinct items with different
    # categories and spaced positions.
    carryable_count = sum(
        1 for e in manifest if e["category"] in CARRYABLES and not e.get("decor")
    )
    needed = max(0, npc_count - carryable_count)
    if needed > 0:
        placed_furniture = [e for e in manifest if e["category"] in FURNITURE]
        # Rotate through carryable categories for variety
        avail_cats = [c for c in CARRYABLES if c not in {
            e["category"] for e in manifest if e["category"] in CARRYABLES
        }]
        # Also vary materials from the palette
        used_mats = {e["material"] for e in manifest}
        alt_mats = ["wrought_iron", "dark_walnut", "rough_granite",
                     "weathered_pine", "worn_oak"]
        avail_mats = [m for m in alt_mats if m not in used_mats]
        if not avail_mats:
            avail_mats = alt_mats
        for i in range(needed):
            cat = avail_cats[i % len(avail_cats)] if avail_cats else CARRYABLES[i % len(CARRYABLES)]
            mat = avail_mats[i % len(avail_mats)]
            # Position: distribute across furniture surfaces, or floor if none
            if placed_furniture:
                fi = i % len(placed_furniture)
                p = placed_furniture[fi]
                ox = (i % 3 - 1) * 0.15
                oz = ((i // 3) % 3 - 1) * 0.15
                ix = round(p["x"] + ox, 3)
                iy = round(_FURNITURE_TOP_Y.get(p["category"], 0.8) + 0.02, 3)
                iz = round(p["z"] + oz, 3)
                surf = "on"
            else:
                # Spread along X at z=1.0, offset by index
                ix = round((i - (needed - 1) / 2.0) * 0.4, 3)
                iy = 0.02
                iz = 1.0 + (i * 0.15)
                surf = "floor"
            # Unique ID: use category + auto + index to avoid collisions
            eid = f"{cat}_auto_{i}"
            manifest.append({
                "id": eid, "category": cat, "material": mat,
                "x": ix, "y": iy, "z": iz, "yaw": 0.0,
                "surface": surf, "decor": False,
            })

    # ── U-4: Chairs-around-tables relational placement ───────
    # After grid placement, if both chairs and tables are present,
    # cluster chairs around the nearest table, facing inward.
    tables_in_manifest = [e for e in manifest if e["category"] == "table"]
    if tables_in_manifest and any(e["category"] == "chair" for e in manifest):
        for e in manifest:
            if e["category"] == "chair":
                nearest = min(tables_in_manifest,
                              key=lambda t: (e["x"] - t["x"])**2 + (e["z"] - t["z"])**2)
                tx, tz = nearest["x"], nearest["z"]
                # Place chair near table edge, facing toward table
                dx = e["x"] - tx
                dz = e["z"] - tz
                dist = (dx*dx + dz*dz) ** 0.5
                if dist > 0.01:
                    # Pull chair to table edge (0.7 m from centre)
                    scale = 0.7 / dist
                    e["x"] = round(tx + dx * scale, 3)
                    e["z"] = round(tz + dz * scale, 3)
                    # Chair faces table: yaw = atan2 toward table
                    import math
                    e["yaw"] = round(math.atan2(tz - e["z"], tx - e["x"]), 3)

    return manifest, {"w": w, "d": d}, decisions
