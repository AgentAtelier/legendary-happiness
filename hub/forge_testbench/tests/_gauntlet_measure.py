"""Shared gauntlet measurement helpers — used by all gauntlet-v1 test plug-ins.

Provides _gauntlet_run() (apply_spec + capture) and _gauntlet_score()
(coverage computation with typed metrics) matching gauntlet.py's _measure().
"""

from __future__ import annotations

import time
from typing import Any

from ..context import Context
from ..metric import Metric
from ..result import ScoredResult, Status

# ── Property axis mapping ──────────────────────────────────────

_PROP_AXIS: dict[str, str] = {
    "mesh": "mesh",
    "shape": "shape",
    "material_override": "color",
    "albedo_color": "color",
    "color": "color",
    "position": "position",
    "transform": "position",
    "text": "text",
}

# ── Shared run() ───────────────────────────────────────────────


async def gauntlet_run(ctx: Context, prompt: str, planner: str) -> dict[str, Any]:
    """Run apply_spec for a gauntlet prompt and capture raw observations."""
    t0 = time.time()

    raw = await ctx.apply_spec(prompt, planner=planner)
    artifact = raw
    if raw.get("artifact_id"):
        try:
            artifact = await ctx.read_artifact(raw["artifact_id"])
        except Exception:
            pass

    return {
        "raw": raw,
        "artifact": artifact,
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ── Shared score() ─────────────────────────────────────────────


def gauntlet_score(test_id: str, expect: dict[str, Any], data: dict[str, Any]) -> ScoredResult:
    """Compute coverage from gauntlet run data, producing typed metrics.

    Evaluates generic checks (nodes, depth, props, scripts, types) plus
    engine-specific checks (spatial, building, scatter, wfc, voronoi)
    driven by the expect block in each prompt spec.
    """
    raw = data.get("raw", {})
    artifact = data.get("artifact", {}) if isinstance(data.get("artifact"), dict) else {}

    # ── Extract observations ──
    ops = [o for o in artifact.get("operations", []) if isinstance(o, dict)]
    adds = [o for o in ops if o.get("type") == "add_node"]
    added_names = sorted({o.get("name", "") for o in adds if o.get("name")})

    # Prop counts by axis
    prop_counts: dict[str, int] = {}
    for o in ops:
        if o.get("type") == "set_property":
            axis = _PROP_AXIS.get(str(o.get("property", "")), None)
            if axis:
                prop_counts[axis] = prop_counts.get(axis, 0) + 1

    # Files, scripts, signals
    files = artifact.get("files", [])
    scripts = [f for f in files if isinstance(f, dict) and str(f.get("path", "")).endswith(".gd")]
    attached = sum(1 for o in ops if o.get("type") == "attach_script")
    signals = sum(1 for o in ops if o.get("type") == "connect_signal")

    # Node types present
    types_present: set[str] = set()
    for o in adds:
        nt = o.get("node_type", "")
        if nt:
            types_present.add(nt)

    # Errors
    errors = raw.get("errors", [])
    err_count = raw.get("error_count", len(errors))

    # ── Run checks ──
    checks: list[dict] = []

    if "min_nodes" in expect:
        n = len(adds)
        checks.append({"label": "nodes", "ok": n >= expect["min_nodes"], "detail": f"{n}/{expect['min_nodes']}"})

    if "min_depth" in expect:
        paths = [o.get("parent", "") + "/" + o.get("name", "") for o in adds]
        max_depth = max((p.count("/") for p in paths), default=0)
        checks.append(
            {"label": "depth", "ok": max_depth >= expect["min_depth"], "detail": f"{max_depth}/{expect['min_depth']}"}
        )

    for axis, need in (expect.get("props") or {}).items():
        got = prop_counts.get(axis, 0)
        checks.append({"label": f"prop:{axis}", "ok": got >= need, "detail": f"{got}/{need}"})

    if "min_scripts" in expect:
        checks.append(
            {
                "label": "scripts",
                "ok": len(scripts) >= expect["min_scripts"],
                "detail": f"{len(scripts)}/{expect['min_scripts']}",
            }
        )

    if "min_attached" in expect:
        checks.append(
            {
                "label": "attached",
                "ok": attached >= expect["min_attached"],
                "detail": f"{attached}/{expect['min_attached']}",
            }
        )

    if "min_signals" in expect:
        checks.append(
            {"label": "signals", "ok": signals >= expect["min_signals"], "detail": f"{signals}/{expect['min_signals']}"}
        )

    if "types" in expect:
        for t in expect["types"]:
            ok = t in types_present
            checks.append({"label": f"type:{t}", "ok": ok, "detail": "present" if ok else "MISSING"})

    if expect.get("expect_errors"):
        checks.append({"label": "rejected-bad-ops", "ok": err_count > 0, "detail": f"{err_count} errors (expected)"})
        checks.append({"label": "no-crash", "ok": True, "detail": "no crash"})

    # ── Spatial checks ──
    _add_spatial_checks(expect, ops, checks)

    # ── Building checks ──
    _add_building_checks(expect, ops, artifact, checks)

    # ── Scatter checks ──
    _add_scatter_checks(expect, ops, artifact, checks)

    # ── WFC checks ──
    _add_wfc_checks(expect, ops, artifact, checks)

    # ── Voronoi checks ──
    _add_voronoi_checks(expect, ops, artifact, checks)

    # ── Compute verdict ──
    met = sum(1 for c in checks if c["ok"])
    total = max(len(checks), 1)
    coverage = round(met / total * 100)

    if expect.get("expect_errors") and err_count > 0 and coverage >= 50:
        status: Status = "ok"  # adversarial: errors expected
    elif coverage == 100:
        status = "ok"
    elif coverage >= 50:
        status = "partial"
    else:
        status = "broke"

    metrics: dict[str, Metric] = {
        "coverage": Metric.percent(float(coverage), "coverage"),
        "nodes": Metric.count(len(adds), "nodes built"),
        "errors": Metric.count(err_count, "errors", higher_is_better=False),
    }

    return ScoredResult(
        test_id, status, score=coverage, metrics=metrics, raw=data, errors=errors[:3] if err_count else []
    )


# ── Spatial checks ─────────────────────────────────────────────


def _add_spatial_checks(expect: dict, ops: list, checks: list) -> None:
    """Spatial: count positioned MeshInstance3Ds and check AABB overlap."""
    if "min_spatial_assets" not in expect and not expect.get("no_overlap"):
        return

    positions: dict[str, dict] = {}
    mesh_nodes: set[str] = set()
    mesh_parents: set[str] = set()

    for o in ops:
        if o.get("type") == "add_node":
            parent = o.get("parent", "")
            name = o.get("name", "")
            node_type = o.get("node_type", "")
            if node_type == "MeshInstance3D":
                path = f"{parent}/{name}" if parent and name else ""
                if path:
                    mesh_nodes.add(path)
                if parent:
                    mesh_parents.add(parent)
        elif o.get("type") == "set_property" and o.get("property") == "position":
            np = o.get("node", "")
            if np:
                positions[np] = o.get("value", {})

    # Build AABB boxes for positioned, renderable nodes (exclude shell)
    _SHELL = ("floor", "ceiling", "wall", "shell", "room")
    boxes: list[dict] = []
    for path, pos in positions.items():
        if not (isinstance(pos, dict) and "x" in pos):
            continue
        if path not in mesh_nodes and path not in mesh_parents:
            continue
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        if any(k in name.lower() for k in _SHELL):
            continue
        boxes.append(
            {"name": name, "x": float(pos.get("x", 0)), "z": float(pos.get("z", 0)), "half_w": 0.5, "half_d": 0.5}
        )

    if "min_spatial_assets" in expect:
        spatial_count = len(boxes)
        checks.append(
            {
                "label": "spatial:assets",
                "ok": spatial_count >= expect["min_spatial_assets"],
                "detail": f"{spatial_count}/{expect['min_spatial_assets']} placed assets",
            }
        )

    if expect.get("no_overlap"):
        overlaps = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if abs(a["x"] - b["x"]) < (a["half_w"] + b["half_w"]) and abs(a["z"] - b["z"]) < (
                    a["half_d"] + b["half_d"]
                ):
                    overlaps.append(f"{a['name']}↔{b['name']}")
        checks.append(
            {
                "label": "spatial:overlap",
                "ok": not overlaps,
                "detail": "no AABB overlaps" if not overlaps else f"Overlaps: {', '.join(overlaps[:3])}",
            }
        )


# ── Building checks ────────────────────────────────────────────


def _add_building_checks(expect: dict, ops: list, artifact: dict, checks: list) -> None:
    """Building: inspect arch_delta._building for rooms, overlap, bounds, walls."""
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    building_json = arch_delta.get("_building")
    if not building_json or not isinstance(building_json, dict):
        return

    tree = building_json.get("tree", {})
    footprint = building_json.get("footprint", {})
    fp_w = float(footprint.get("width", 0))
    fp_d = float(footprint.get("depth", 0))

    # Collect leaf rooms (mirrors BSPPartitioner._partition)
    rooms = _collect_bsp_rooms(tree, (0.0, 0.0), (fp_w, fp_d))

    if "min_rooms" in expect:
        checks.append(
            {
                "label": "building:rooms",
                "ok": len(rooms) >= expect["min_rooms"],
                "detail": f"{len(rooms)}/{expect['min_rooms']} leaf rooms",
            }
        )

    if expect.get("building_no_overlap"):
        overlaps = []
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                if _aabb_overlap(rooms[i], rooms[j]):
                    overlaps.append(f"{rooms[i]['name']}↔{rooms[j]['name']}")
        checks.append(
            {
                "label": "building:no_overlap",
                "ok": not overlaps,
                "detail": f"{len(rooms)} rooms, no overlaps"
                if not overlaps
                else f"Overlaps: {', '.join(overlaps[:3])}",
            }
        )

    if expect.get("building_in_bounds"):
        oob = [
            r["name"]
            for r in rooms
            if r["x"] < -0.01 or r["z"] < -0.01 or r["x"] + r["w"] > fp_w + 0.01 or r["z"] + r["d"] > fp_d + 0.01
        ]
        checks.append(
            {
                "label": "building:in_bounds",
                "ok": not oob,
                "detail": f"All rooms within {fp_w:.0f}×{fp_d:.0f} footprint" if not oob else f"OOB: {', '.join(oob)}",
            }
        )

    if "min_walls" in expect:
        wall_count = sum(
            1 for o in ops if isinstance(o, dict) and o.get("type") == "add_node" and "Wall_" in str(o.get("name", ""))
        )
        checks.append(
            {
                "label": "building:walls",
                "ok": wall_count >= expect["min_walls"],
                "detail": f"{wall_count}/{expect['min_walls']} wall segments",
            }
        )


def _collect_bsp_rooms(node: dict, origin: tuple, size: tuple) -> list[dict]:
    """Recursively collect leaf rooms from a BSP split tree."""
    if not isinstance(node, dict) or not node:
        return []
    if "room" in node:
        return [{"name": node.get("room", "room"), "x": origin[0], "z": origin[1], "w": size[0], "d": size[1]}]
    if "axis" not in node:
        return []
    ox, oz = origin
    w, d = size
    axis = node.get("axis", "x")
    ratio = max(0.1, min(0.9, float(node.get("ratio", 0.5))))
    if axis == "x":
        left_w = w * ratio
        return _collect_bsp_rooms(node.get("left", {}), (ox, oz), (left_w, d)) + _collect_bsp_rooms(
            node.get("right", {}), (ox + left_w, oz), (w - left_w, d)
        )
    else:
        left_d = d * ratio
        return _collect_bsp_rooms(node.get("left", {}), (ox, oz), (w, left_d)) + _collect_bsp_rooms(
            node.get("right", {}), (ox, oz + left_d), (w, d - left_d)
        )


def _aabb_overlap(a: dict, b: dict) -> bool:
    return (
        a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and a["z"] < b["z"] + b["d"] and a["z"] + a["d"] > b["z"]
    )


# ── Scatter checks ─────────────────────────────────────────────


def _add_scatter_checks(expect: dict, ops: list, artifact: dict, checks: list) -> None:
    """Scatter: count placed items and check bounds."""
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    garden_json = arch_delta.get("_scatter")
    if not garden_json or not isinstance(garden_json, dict):
        return

    region = garden_json.get("region", {})
    rw = float(region.get("width", 20))
    rd = float(region.get("depth", 20))

    # Count placed plant/rock nodes
    plant_prefixes = ("tree_", "bush_", "flower_", "rock_")
    plant_created = sum(
        1
        for o in ops
        if o.get("type") == "add_node" and any(str(o.get("name", "")).startswith(p) for p in plant_prefixes)
    )

    if "min_scatter_items" in expect:
        checks.append(
            {
                "label": "scatter:items",
                "ok": plant_created >= expect["min_scatter_items"],
                "detail": f"{plant_created}/{expect['min_scatter_items']} placed",
            }
        )

    if expect.get("scatter_in_bounds"):
        positions = []
        for o in ops:
            if o.get("type") == "set_property" and o.get("property") == "position":
                val = o.get("value", {})
                if isinstance(val, dict) and "x" in val and "z" in val:
                    node = o.get("node", "")
                    if any(str(node).startswith(p) for p in plant_prefixes):
                        positions.append(val)
        oob = sum(
            1
            for p in positions
            if p.get("x", 0) < -0.01 or p.get("x", 0) > rw + 0.01 or p.get("z", 0) < -0.01 or p.get("z", 0) > rd + 0.01
        )
        checks.append(
            {
                "label": "scatter:in_bounds",
                "ok": oob == 0,
                "detail": f"All {len(positions)} within {rw:.0f}×{rd:.0f} region"
                if oob == 0
                else f"{oob}/{len(positions)} OOB",
            }
        )


# ── WFC checks ─────────────────────────────────────────────────


def _add_wfc_checks(expect: dict, ops: list, artifact: dict, checks: list) -> None:
    """WFC: count tiles and check bounds/features."""
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    dungeon_json = arch_delta.get("_wfc")
    if not dungeon_json or not isinstance(dungeon_json, dict):
        return

    # Collect tile entries from add_node ops (name pattern: type_col_row)
    tile_data: list[dict] = []
    for o in ops:
        if o.get("type") == "add_node":
            name = str(o.get("name", ""))
            parts = name.split("_")
            if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                tile_data.append({"name": name, "tile_type": parts[0]})

    if "min_wfc_tiles" in expect:
        checks.append(
            {
                "label": "wfc:tiles",
                "ok": len(tile_data) >= expect["min_wfc_tiles"],
                "detail": f"{len(tile_data)}/{expect['min_wfc_tiles']} tiles",
            }
        )

    if "wfc_has_walls" in expect:
        wall_count = sum(1 for td in tile_data if td.get("tile_type") == "wall")
        checks.append({"label": "wfc:walls", "ok": wall_count > 0, "detail": f"{wall_count} wall tiles"})

    if "wfc_has_floor" in expect:
        floor_count = sum(1 for td in tile_data if td.get("tile_type") == "floor")
        checks.append({"label": "wfc:floor", "ok": floor_count > 0, "detail": f"{floor_count} floor tiles"})

    if expect.get("wfc_in_bounds"):
        size_spec = dungeon_json.get("size", {})
        w = int(size_spec.get("width", 8))
        d = int(size_spec.get("depth", 8))
        tile_size = float(dungeon_json.get("tile_size", 2.0))
        max_x = w * tile_size
        max_z = d * tile_size
        # Collect positions for tile nodes
        positions: dict[str, dict] = {}
        for o in ops:
            if o.get("type") == "set_property" and o.get("property") == "position":
                np = o.get("node", "")
                val = o.get("value", {})
                if isinstance(val, dict) and "x" in val:
                    positions[np] = val
        # Count out-of-bounds tiles (matching name pattern)
        oob_count = 0
        for td in tile_data:
            name = td["name"]
            pos = None
            for path, p in positions.items():
                if path.endswith(name) or path.endswith(f"/{name}"):
                    pos = p
                    break
            if pos:
                x = float(pos.get("x", 0))
                z = float(pos.get("z", 0))
                if x < -0.01 or z < -0.01 or x > max_x + 0.01 or z > max_z + 0.01:
                    oob_count += 1
        checks.append(
            {
                "label": "wfc:in_bounds",
                "ok": oob_count == 0,
                "detail": f"All tiles within {w}×{d} grid ({max_x:.0f}×{max_z:.0f}m)"
                if oob_count == 0
                else f"{oob_count} tiles out of bounds",
            }
        )


# ── Voronoi checks ─────────────────────────────────────────────


def _add_voronoi_checks(expect: dict, ops: list, artifact: dict, checks: list) -> None:
    """Voronoi: count districts and roads."""
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    town_json = arch_delta.get("_voronoi")
    if not town_json or not isinstance(town_json, dict):
        return

    road_count = sum(1 for o in ops if o.get("type") == "add_node" and str(o.get("name", "")).startswith("road_"))
    district_count = len(
        {o.get("name") for o in ops if o.get("type") == "add_node" and str(o.get("name", "")).startswith("district_")}
    )

    if "voronoi_has_districts" in expect:
        checks.append(
            {
                "label": "voronoi:districts",
                "ok": district_count >= expect["voronoi_has_districts"],
                "detail": f"{district_count}/{expect['voronoi_has_districts']} district nodes",
            }
        )

    if "min_voronoi_roads" in expect:
        checks.append(
            {
                "label": "voronoi:roads",
                "ok": road_count >= expect["min_voronoi_roads"],
                "detail": f"{road_count}/{expect['min_voronoi_roads']} road tiles",
            }
        )

    if expect.get("voronoi_in_bounds"):
        region = town_json.get("region", {})
        rw = float(region.get("width", 80))
        rd = float(region.get("depth", 80))
        # Collect district positions
        district_positions: dict[str, dict] = {}
        for o in ops:
            if o.get("type") == "set_property" and o.get("property") == "position":
                np = o.get("node", "")
                val = o.get("value", {})
                if isinstance(val, dict) and "x" in val and "district_" in str(np):
                    district_positions[np] = val
        oob = [
            n
            for n, p in district_positions.items()
            if float(p.get("x", 0)) < -0.01
            or float(p.get("z", 0)) < -0.01
            or float(p.get("x", 0)) > rw + 0.01
            or float(p.get("z", 0)) > rd + 0.01
        ]
        checks.append(
            {
                "label": "voronoi:in_bounds",
                "ok": not oob,
                "detail": f"All districts within {rw:.0f}×{rd:.0f}m"
                if not oob
                else f"{len(oob)} districts out of bounds",
            }
        )
