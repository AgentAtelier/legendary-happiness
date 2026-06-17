"""forge-hub capability gauntlet — measure what the pipeline can actually build.

Unlike the shootout (one fixed prompt, pass/fail vs a rigid spec), the gauntlet
runs a SET of escalating prompts, each pushing ONE capability axis (nesting
depth, breadth, prop saturation, collider/mesh children, scripts+signals, mixed
2D/3D/UI, integration, adversarial), and reports COVERAGE — built vs requested —
so you can see WHERE the pipeline degrades, not just whether it passed.

Stage 4 (Variety Dashboard): Adds variety:repeat_diversity,
variety:intent_coverage, variety:descriptor_entropy, and fidelity:llm_judge
check types. When --runs N > 1, the aggregation block computes diversity
metrics across runs and surfaces them beside correctness.

Prompt sets live in data/gauntlet/sets/*.json (editable; add your own over time).
Results persist to data/gauntlet/gauntlet-<ts>.json so progress is diffable.

CLI:
  python gauntlet.py --list                     # available sets
  python gauntlet.py --run capability-v1        # run a set (current model)
  python gauntlet.py --run capability-v1 --only G4_children,G7_integration
  python gauntlet.py --run variety-v1 --runs 10 # variety dashboard sweep
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from scenarios import _devforge_call, _get_scene_snapshot, DATA_DIR
import bench  # reuse the disposable probe-scene helpers + env read

GAUNTLET_DIR = DATA_DIR / "gauntlet"
SETS_DIR = GAUNTLET_DIR / "sets"
GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)
SETS_DIR.mkdir(parents=True, exist_ok=True)

# property name (as emitted by set_property ops) → capability axis bucket
_PROP_AXIS = {
    "mesh": "mesh",
    "shape": "shape",
    "material_override": "color",
    "albedo_color": "color",
    "color": "color",
    "position": "position",
    "transform": "position",
    "text": "text",
}


# ── prompt sets ──────────────────────────────────────────────────

def list_sets() -> list[dict]:
    """All prompt sets (id, title, description, prompt count)."""
    out = []
    for f in sorted(SETS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out.append({"id": d.get("id", f.stem), "title": d.get("title", f.stem),
                        "description": d.get("description", ""),
                        "count": len(d.get("prompts", [])), "file": f.name})
        except Exception:
            continue
    return out


def load_set(set_id: str) -> dict | None:
    for f in SETS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("id") == set_id or f.stem == set_id:
            return d
    return None


# ── measurement ──────────────────────────────────────────────────

def _depth(path: str) -> int:
    """Nesting depth relative to the scene root (/Main = 0, /Main/X = 1)."""
    return max(path.count("/") - 1, 0)


def _add_spatial_checks(expect: dict, ops: list, add_check) -> None:
    """Add spatial-specific checks: asset count and AABB overlap detection.

    Scans set_property position operations to build bounding boxes for
    placed nodes and checks for overlap. Only runs when spatial expect
    keys are present (min_spatial_assets, no_overlap).
    """
    if "min_spatial_assets" not in expect and not expect.get("no_overlap"):
        return

    # Build placed-asset boxes. A "placed asset" is a node that carries a
    # set_property position AND is renderable — either a MeshInstance3D itself
    # (the arch path positions the mesh directly) or a container whose child is
    # a MeshInstance3D (the layout/SpatialCompiler path positions the furniture
    # container and parents the mesh at local origin). Counting only positioned
    # MeshInstance3Ds — as this check used to — misses every layout-built asset,
    # which is why a correctly-placed kitchen scored 0/3 here.
    boxes: list[dict] = []  # [{name, x, z, half_w, half_d}]
    positions: dict[str, dict] = {}   # node_path → set_property position value
    mesh_nodes: set[str] = set()      # MeshInstance3D paths
    mesh_parents: set[str] = set()    # parents that own a MeshInstance3D child

    for o in ops:
        if o.get("type") == "add_node":
            parent = o.get("parent", "")
            name = o.get("name", "")
            node_type = o.get("node_type", "")
            path = f"{parent}/{name}" if parent and name else ""
            if path and node_type == "MeshInstance3D":
                mesh_nodes.add(path)
                if parent:
                    mesh_parents.add(parent)
        elif o.get("type") == "set_property" and o.get("property") == "position":
            np = o.get("node", "")
            if np:
                positions[np] = o.get("value", {})

    # Convert positioned, renderable nodes to boxes (default half-width 0.5).
    # EXCLUDE structural shell nodes (floor/ceiling/walls): they are
    # room-spanning planes that legitimately cover the whole footprint, so
    # AABB-testing them against furniture produces false overlaps on every
    # valid room. The no_overlap check is about FURNITURE clipping.
    _SHELL = ("floor", "ceiling", "wall", "shell", "room")
    for path, pos in positions.items():
        if not (isinstance(pos, dict) and "x" in pos):
            continue
        if path not in mesh_nodes and path not in mesh_parents:
            continue  # positioned but not renderable (logic/root/container-only)
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        if any(k in name.lower() for k in _SHELL):
            continue
        boxes.append({
            "name": name,
            "x": float(pos.get("x", 0)),
            "z": float(pos.get("z", 0)),
            "half_w": 0.5,
            "half_d": 0.5,
        })

    # Check spatial asset count
    if "min_spatial_assets" in expect:
        spatial_count = len(boxes)
        add_check(
            "spatial:assets",
            spatial_count >= expect["min_spatial_assets"],
            f"{spatial_count}/{expect['min_spatial_assets']} placed MeshInstance3Ds"
        )

    # Check for overlap
    if expect.get("no_overlap"):
        overlaps = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                dx = abs(a["x"] - b["x"])
                dz = abs(a["z"] - b["z"])
                if dx < (a["half_w"] + b["half_w"]) and dz < (a["half_d"] + b["half_d"]):
                    overlaps.append(f"{a['name']} ↔ {b['name']}")
        if overlaps:
            add_check(
                "spatial:overlap",
                False,
                f"Overlaps: {', '.join(overlaps[:5])}"
            )
        else:
            add_check(
                "spatial:overlap",
                True,
                "no AABB overlaps detected"
            )


def _rects_overlap(a: dict, b: dict) -> bool:
    """Check AABB overlap on the XZ plane."""
    return (
        a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"]
        and a["z"] < b["z"] + b["d"] and a["z"] + a["d"] > b["z"]
    )


def _collect_rooms(node: dict, origin: tuple, size: tuple) -> list[dict]:
    """Recursively collect leaf rooms from a BSP split tree into rect dicts.

    Mirrors BSPPartitioner._partition — pure arithmetic, no dependency on
    devforge. Each rect has keys: name, x, z, w, d.
    """
    if not isinstance(node, dict) or not node:
        return []

    if "room" in node:
        return [{
            "name": node.get("room", "room"),
            "x": origin[0], "z": origin[1],
            "w": size[0], "d": size[1],
        }]

    # Malformed node guard — align with BSPPartitioner._partition
    if "axis" not in node:
        return []

    ox, oz = origin
    w, d = size
    axis = node.get("axis", "x")
    ratio = max(0.1, min(0.9, float(node.get("ratio", 0.5))))

    if axis == "x":
        left_w = w * ratio
        rooms = _collect_rooms(node.get("left", {}), (ox, oz), (left_w, d))
        rooms += _collect_rooms(node.get("right", {}), (ox + left_w, oz), (w - left_w, d))
    else:
        left_d = d * ratio
        rooms = _collect_rooms(node.get("left", {}), (ox, oz), (w, left_d))
        rooms += _collect_rooms(node.get("right", {}), (ox, oz + left_d), (w, d - left_d))
    return rooms


def _add_building_checks(expect: dict, ops: list, artifact: dict, add_check) -> None:
    """Add building-specific checks when building:* expect keys are present.

    Inspects the arch_delta._building split tree to count rooms, verify
    no AABB overlap, check all rooms are within the footprint, and count
    partition walls.
    """
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    building_json = arch_delta.get("_building")
    if not building_json or not isinstance(building_json, dict):
        return

    tree = building_json.get("tree", {})
    footprint = building_json.get("footprint", {})
    fp_w = float(footprint.get("width", 0))
    fp_d = float(footprint.get("depth", 0))

    # Collect leaf room rects from the split tree
    rooms = _collect_rooms(tree, (0.0, 0.0), (fp_w, fp_d))

    # ── building:rooms ──
    if "min_rooms" in expect:
        add_check(
            "building:rooms",
            len(rooms) >= expect["min_rooms"],
            f"{len(rooms)}/{expect['min_rooms']} leaf rooms",
        )

    # ── building:no_overlap ──
    if expect.get("building_no_overlap"):
        overlaps: list[str] = []
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                if _rects_overlap(rooms[i], rooms[j]):
                    overlaps.append(f"{rooms[i]['name']}↔{rooms[j]['name']}")
        if overlaps:
            add_check(
                "building:no_overlap",
                False,
                f"Overlaps: {', '.join(overlaps[:5])}",
            )
        else:
            add_check(
                "building:no_overlap",
                True,
                f"{len(rooms)} rooms, no overlaps",
            )

    # ── building:in_bounds ──
    if expect.get("building_in_bounds"):
        oob: list[str] = []
        for r in rooms:
            x, z, w, d = r["x"], r["z"], r["w"], r["d"]
            if x < -0.001 or z < -0.001 or x + w > fp_w + 0.001 or z + d > fp_d + 0.001:
                oob.append(r["name"])
        if oob:
            add_check(
                "building:in_bounds",
                False,
                f"Out of bounds: {', '.join(oob[:5])}",
            )
        else:
            add_check(
                "building:in_bounds",
                True,
                f"All rooms within {fp_w:.0f}×{fp_d:.0f} footprint",
            )

    # ── building:walls ──
    if "min_walls" in expect:
        wall_count = sum(
            1 for o in ops
            if isinstance(o, dict)
            and o.get("type") == "add_node"
            and "Wall_" in str(o.get("name", ""))
        )
        add_check(
            "building:walls",
            wall_count >= expect["min_walls"],
            f"{wall_count}/{expect['min_walls']} wall segments",
        )


def _add_scatter_checks(expect: dict, ops: list, artifact: dict, add_check) -> None:
    """Add scatter-specific checks when scatter:* expect keys are present.

    Inspects the arch_delta._scatter garden JSON to verify item counts
    and that all positions fall within the region bounds.
    """
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    garden_json = arch_delta.get("_scatter")
    if not garden_json or not isinstance(garden_json, dict):
        return

    region = garden_json.get("region", {})
    rw = float(region.get("width", 20))
    rd = float(region.get("depth", 20))

    # ── scatter:items ──
    if "min_scatter_items" in expect:
        # Count total items requested in species list
        total_requested = sum(
            int(s.get("count", 0))
            for s in garden_json.get("species", [])
        )
        # Count actually placed (in ops — mesh nodes for plant assets)
        plant_created = 0
        for o in ops:
            if o.get("type") == "add_node":
                name = str(o.get("name", ""))
                if any(prefix in name for prefix in ("tree_", "bush_", "flower_", "rock_")):
                    plant_created += 1

        add_check(
            "scatter:items",
            plant_created >= expect["min_scatter_items"],
            f"{plant_created}/{expect['min_scatter_items']} placed (LLM requested {total_requested})",
        )

    # ── scatter:in_bounds ──
    if expect.get("scatter_in_bounds"):
        positions: list[dict] = []
        for o in ops:
            if o.get("type") == "set_property" and o.get("property") == "position":
                val = o.get("value", {})
                if isinstance(val, dict) and "x" in val and "z" in val:
                    node = o.get("node", "")
                    if any(prefix in node for prefix in ("tree_", "bush_", "flower_", "rock_")):
                        positions.append(val)

        oob_count = sum(
            1 for p in positions
            if p.get("x", 0) < -0.01 or p.get("x", 0) > rw + 0.01
            or p.get("z", 0) < -0.01 or p.get("z", 0) > rd + 0.01
        )
        if oob_count:
            add_check(
                "scatter:in_bounds",
                False,
                f"{oob_count}/{len(positions)} items out of bounds",
            )
        else:
            add_check(
                "scatter:in_bounds",
                True,
                f"All {len(positions)} items within {rw:.0f}×{rd:.0f} region",
            )


def _add_wfc_checks(expect: dict, ops: list, artifact: dict, add_check) -> None:
    """Add WFC-specific checks when wfc:* expect keys are present.

    Inspects the arch_delta._wfc dungeon JSON to verify tile counts,
    wall presence, floor presence, and boundary containment.
    """
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    dungeon_json = arch_delta.get("_wfc")
    if not dungeon_json or not isinstance(dungeon_json, dict):
        return

    size_spec = dungeon_json.get("size", {})
    w = int(size_spec.get("width", 8))
    d = int(size_spec.get("depth", 8))
    tile_size = float(dungeon_json.get("tile_size", 2.0))

    # Collect placed tile names and positions from ops
    tile_data: list[dict] = []  # [{name, tile_type, col, row, x, z}]
    positions: dict[str, dict] = {}
    for o in ops:
        if o.get("type") == "add_node":
            name = str(o.get("name", ""))
            if "_" in name:
                parts = name.split("_")
                if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                    tile_data.append({
                        "name": name,
                        "tile_type": parts[0],
                        "col": int(parts[-2]),
                        "row": int(parts[-1]),
                    })
        elif o.get("type") == "set_property" and o.get("property") == "position":
            np = o.get("node", "")
            val = o.get("value", {})
            if isinstance(val, dict) and "x" in val:
                positions[np] = val

    # Attach positions to tile entries
    for td in tile_data:
        name = td["name"]
        for path, pos in positions.items():
            if path.endswith(name) or path.endswith(f"/{name}"):
                td["x"] = float(pos.get("x", 0))
                td["z"] = float(pos.get("z", 0))
                break

    # ── wfc:min_tiles ──
    if "min_wfc_tiles" in expect:
        tile_count = len(tile_data)
        add_check(
            "wfc:tiles",
            tile_count >= expect["min_wfc_tiles"],
            f"{tile_count}/{expect['min_wfc_tiles']} tiles placed",
        )

    # ── wfc:in_bounds ──
    if expect.get("wfc_in_bounds"):
        max_x = w * tile_size
        max_z = d * tile_size
        oob = [
            td["name"] for td in tile_data
            if td.get("x") is not None and (
                td["x"] < -0.01 or td["x"] > max_x + 0.01
                or td.get("z", 0) < -0.01 or td.get("z", 0) > max_z + 0.01
            )
        ]
        if oob:
            add_check(
                "wfc:in_bounds",
                False,
                f"{len(oob)}/{len(tile_data)} tiles out of bounds: {', '.join(oob[:5])}",
            )
        else:
            add_check(
                "wfc:in_bounds",
                True,
                f"All tiles within {w}×{d} grid ({max_x:.0f}×{max_z:.0f}m)",
            )

    # ── wfc:has_walls ──
    if "wfc_has_walls" in expect:
        wall_count = sum(1 for td in tile_data if td.get("tile_type") == "wall")
        add_check(
            "wfc:walls",
            wall_count > 0,
            f"{wall_count} wall tiles",
        )

    # ── wfc:has_floor ──
    if "wfc_has_floor" in expect:
        floor_count = sum(1 for td in tile_data if td.get("tile_type") == "floor")
        add_check(
            "wfc:floor",
            floor_count > 0,
            f"{floor_count} floor tiles",
        )


def _add_voronoi_checks(expect: dict, ops: list, artifact: dict, add_check) -> None:
    """Add Voronoi-specific checks when voronoi:* expect keys are present.

    Inspects the arch_delta._voronoi town JSON to verify district count,
    road presence, and boundary containment.
    """
    arch_delta = artifact.get("arch_delta", {}) if isinstance(artifact, dict) else {}
    town_json = arch_delta.get("_voronoi")
    if not town_json or not isinstance(town_json, dict):
        return

    region = town_json.get("region", {})
    rw = float(region.get("width", 80))
    rd = float(region.get("depth", 80))
    expected_districts = int(town_json.get("districts", 5))

    # Count roads and district nodes
    road_count = 0
    district_names: set = set()
    positions: dict[str, dict] = {}

    for o in ops:
        if o.get("type") == "add_node":
            name = str(o.get("name", ""))
            if name.startswith("road_"):
                road_count += 1
            elif name.startswith("district_"):
                district_names.add(name)
        elif o.get("type") == "set_property" and o.get("property") == "position":
            np = o.get("node", "")
            val = o.get("value", {})
            if isinstance(val, dict) and "x" in val:
                positions[np] = val

    # ── voronoi:has_districts ──
    if "voronoi_has_districts" in expect:
        add_check(
            "voronoi:districts",
            len(district_names) >= expect["voronoi_has_districts"],
            f"{len(district_names)}/{expect['voronoi_has_districts']} district nodes (LLM requested {expected_districts})",
        )

    # ── min_voronoi_roads ──
    if "min_voronoi_roads" in expect:
        add_check(
            "voronoi:roads",
            road_count >= expect["min_voronoi_roads"],
            f"{road_count}/{expect['min_voronoi_roads']} road tiles",
        )

    # ── voronoi:in_bounds ──
    if expect.get("voronoi_in_bounds"):
        oob: list[str] = []
        for node, pos in positions.items():
            if not isinstance(pos, dict):
                continue
            x = float(pos.get("x", 0))
            z = float(pos.get("z", 0))
            # District centroids should be within the region
            if "district_" in node:
                if x < -0.01 or z < -0.01 or x > rw + 0.01 or z > rd + 0.01:
                    oob.append(node)
        if oob:
            add_check(
                "voronoi:in_bounds",
                False,
                f"{len(oob)} district nodes out of {rw:.0f}×{rd:.0f}m bounds",
            )
        else:
            add_check(
                "voronoi:in_bounds",
                True,
                f"All district nodes within {rw:.0f}×{rd:.0f}m region",
            )


def _compute_diversity(run_data: list[dict]) -> dict:
    """Compute diversity metrics across multiple runs of the same prompt.

    Returns a dict with:
      - jaccard_distance: 1.0 − |intersection| / |union| of node name sets
        (0.0 = identical, 1.0 = completely different)
      - asset_similarity: how similar the asset multisets are (0-1, lower=more diverse)
      - position_variance: mean variance of asset positions across runs
      - distinct_outputs: number of unique outputs (by node set hash)
      - total_runs: number of runs compared
    """
    if len(run_data) < 2:
        return {
            "jaccard_distance": 0.0,
            "asset_similarity": 1.0,
            "position_variance": 0.0,
            "distinct_outputs": 1,
            "total_runs": len(run_data),
        }

    # Extract node name sets from each run
    node_sets: list[set] = []
    asset_multisets: list[dict] = []

    for run in run_data:
        names = set()
        asset_counts = {}

        # Extract from the full operations list if available
        full_ops = run.get("_ops", [])
        for o in (full_ops if full_ops else []):
            if isinstance(o, dict) and o.get("type") == "add_node":
                name = str(o.get("name", ""))
                if name:
                    names.add(name)
                    # Track asset type from node name prefix
                    parts = name.split("_")
                    if parts:
                        asset_type = parts[0]
                        asset_counts[asset_type] = asset_counts.get(asset_type, 0) + 1

        # Fallback: use nodes_sample if no full ops
        if not names:
            names = set(run.get("nodes_sample", []))

        node_sets.append(names)
        asset_multisets.append(asset_counts)

    # Jaccard distance: 1 − |intersection|/|union|
    all_union = set()
    all_intersection = node_sets[0].copy() if node_sets else set()
    for ns in node_sets:
        all_union |= ns
        all_intersection &= ns
    jaccard = 1.0 - (len(all_intersection) / max(len(all_union), 1))

    # Asset multiset similarity: average pairwise Jaccard of asset type counts
    asset_sims = []
    for i in range(len(asset_multisets)):
        for j in range(i + 1, len(asset_multisets)):
            a_keys = set(asset_multisets[i].keys()) | set(asset_multisets[j].keys())
            if not a_keys:
                asset_sims.append(1.0)
                continue
            matches = sum(
                min(asset_multisets[i].get(k, 0), asset_multisets[j].get(k, 0))
                for k in a_keys
            )
            totals = sum(
                max(asset_multisets[i].get(k, 0), asset_multisets[j].get(k, 0))
                for k in a_keys
            )
            asset_sims.append(matches / max(totals, 1))
    asset_similarity = sum(asset_sims) / max(len(asset_sims), 1) if asset_sims else 1.0

    # Count distinct outputs by hashing node sets
    node_hashes = set()
    for ns in node_sets:
        node_hashes.add(hash(frozenset(ns)))
    distinct = len(node_hashes)

    return {
        "jaccard_distance": round(jaccard, 3),
        "asset_similarity": round(asset_similarity, 3),
        "distinct_outputs": distinct,
        "total_runs": len(run_data),
    }


def _add_variety_checks(
    expect: dict, run_data: list[dict], artifact: dict,
    add_check, results: list[dict] | None = None,
) -> None:
    """Add variety-specific checks when variety:* or fidelity:* expect keys are present.

    variety:repeat_diversity  — N runs of one prompt → distinct-output ratio
    variety:intent_coverage   — vary one descriptor field at a time → % of fields
                                that measurably change the output
    variety:descriptor_entropy — distinct descriptors LLM emits over N runs
    fidelity:llm_judge         — judge model rates 1-5 "does it match intent?"
    """
    # ── variety:repeat_diversity ──
    if "variety_min_diversity" in expect:
        div = _compute_diversity(run_data) if run_data else {"jaccard_distance": 0}
        diversity_score = div.get("jaccard_distance", 0)
        target = expect["variety_min_diversity"]
        add_check(
            "variety:repeat_diversity",
            diversity_score >= target,
            f"Jaccard distance {diversity_score:.2f}/{target} "
            f"({div.get('distinct_outputs', 1)}/{div.get('total_runs', 1)} distinct)",
        )

    # ── variety:intent_coverage ──
    if "variety_min_intent_fields" in expect:
        # Compare adjacent result pairs — each pair should differ
        # (each result corresponds to a different intent field variant)
        if results and len(results) >= 2:
            changed = 0
            for i in range(len(results) - 1):
                ni = set(results[i].get("nodes_sample", []))
                nj = set(results[i + 1].get("nodes_sample", []))
                if ni != nj:
                    changed += 1
            field_count = expect["variety_min_intent_fields"]
            add_check(
                "variety:intent_coverage",
                changed >= field_count,
                f"{changed}/{field_count} adjacent pairs differ",
            )

    # ── variety:descriptor_entropy ──
    if "variety_min_entropy" in expect:
        # Count distinct arch_delta descriptors across runs
        descriptors = set()
        for run in run_data:
            ad = run.get("_arch_delta", {})
            if isinstance(ad, dict):
                # Hash the room/ssp descriptor
                for key in ("_room", "_ssp"):
                    desc = ad.get(key)
                    if isinstance(desc, dict):
                        descriptors.add(json.dumps(desc, sort_keys=True, default=str))
        entropy = len(descriptors) / max(len(run_data), 1)
        target = expect["variety_min_entropy"]
        add_check(
            "variety:descriptor_entropy",
            entropy >= target,
            f"{len(descriptors)}/{len(run_data)} distinct ({entropy:.2f}/{target})",
        )

    # ── fidelity:llm_judge ── (deferred — requires live LLM wiring)
    # NOTE: _fidelity_judge() exists but is not called from run_gauntlet().
    # When wired, it should be called in the aggregation block and store
    # the result in artifact["_fidelity_judge"] before _add_variety_checks.
    if "fidelity_expect_rating" in expect:
        add_check(
            "fidelity:llm_judge",
            False,
            "fidelity_judge not wired — run from aggregation block first",
        )
    """Build a capability profile for one prompt: what was built vs requested.

    `after_types` is the post-apply snapshot (path → {name,type}).
    """
    expect = spec.get("expect", {})
    after = set(after_types.keys())
    added = sorted(after - before)
    types_present = {after_types[p].get("type", "") for p in added}
    ops = artifact.get("operations", []) if isinstance(artifact, dict) else []
    ops = [o for o in ops if isinstance(o, dict)]
    files = artifact.get("files", []) if isinstance(artifact, dict) else []

    # prop coverage from set_property ops
    prop_counts: dict[str, int] = {}
    for o in ops:
        if o.get("type") == "set_property":
            axis = _PROP_AXIS.get(str(o.get("property", "")), None)
            if axis:
                prop_counts[axis] = prop_counts.get(axis, 0) + 1

    scripts = [f for f in files if isinstance(f, dict) and str(f.get("path", "")).endswith(".gd")]
    attached = sum(1 for o in ops if o.get("type") == "attach_script")
    signals = sum(1 for o in ops if o.get("type") == "connect_signal")
    errors = raw.get("errors") or []
    err_count = len(errors)

    built_depth = max((_depth(p) for p in added), default=0)

    data = dict(
        built_nodes=len(added), built_depth=built_depth,
        applied=raw.get("applied"), operations_total=raw.get("operations_total"),
        error_count=err_count, errors=errors[:6],
        props=prop_counts, scripts=len(scripts), attached=attached, signals=signals,
        latency_ms=ms, nodes_sample=added[:20],
        # B3/N8: surface truncated flag from artifact for A/B thinking-config comparison
        truncated=artifact.get("truncated", False) if isinstance(artifact, dict) else False,
    )

    # ── coverage checks ──
    checks: list[dict] = []

    def add_check(label, ok, detail):
        checks.append({"label": label, "ok": bool(ok), "detail": detail})

    if "min_nodes" in expect:
        add_check("nodes", len(added) >= expect["min_nodes"],
                  f"{len(added)}/{expect['min_nodes']}")
    if "min_depth" in expect:
        add_check("depth", built_depth >= expect["min_depth"],
                  f"{built_depth}/{expect['min_depth']}")
    for axis, need in (expect.get("props") or {}).items():
        got = prop_counts.get(axis, 0)
        add_check(f"prop:{axis}", got >= need, f"{got}/{need}")
    if "min_scripts" in expect:
        add_check("scripts", len(scripts) >= expect["min_scripts"],
                  f"{len(scripts)}/{expect['min_scripts']}")
    if "min_attached" in expect:
        add_check("attached", attached >= expect["min_attached"],
                  f"{attached}/{expect['min_attached']}")
    if "min_signals" in expect:
        add_check("signals", signals >= expect["min_signals"],
                  f"{signals}/{expect['min_signals']}")
    if "types" in expect:
        for t in expect["types"]:
            add_check(f"type:{t}", t in types_present,
                      "present" if t in types_present else "MISSING")
    if expect.get("expect_errors"):
        # Adversarial: we WANT it to reject bad ops gracefully (errors) but not crash.
        add_check("rejected-bad-ops", err_count > 0, f"{err_count} errors (expected)")
        add_check("no-crash", not crashed, "no crash" if not crashed else "CRASHED")

    # ── Spatial checks (for spatial-v1 gauntlet set) ──
    _add_spatial_checks(expect, ops, add_check)

    # ── Building checks (for building-v1 gauntlet set) ──
    _add_building_checks(expect, ops, artifact, add_check)

    # ── Scatter checks (for garden-v1 gauntlet set) ──
    _add_scatter_checks(expect, ops, artifact, add_check)

    # ── WFC checks (for wfc-v1 gauntlet set) ──
    _add_wfc_checks(expect, ops, artifact, add_check)

    # ── Voronoi checks (for voronoi-v1 gauntlet set) ──
    _add_voronoi_checks(expect, ops, artifact, add_check)

    met = sum(1 for c in checks if c["ok"])
    total = len(checks) or 1
    coverage = round(met / total * 100)
    data["checks"] = checks
    data["coverage"] = coverage

    if crashed and not expect.get("expect_errors"):
        verdict = "broke"
    elif err_count and not expect.get("expect_errors"):
        verdict = "broke" if not added else "partial"
    elif coverage == 100:
        verdict = "full"
    elif coverage >= 50:
        verdict = "partial"
    else:
        verdict = "broke"
    data["verdict"] = verdict
    return data


async def _with_heartbeat(coro, emit, label, interval=5.0):
    t0 = time.time()
    task = asyncio.ensure_future(coro)
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            break
        emit(f"    …{label} ({int(time.time()-t0)}s)")
    return await task


# ── runner ───────────────────────────────────────────────────────

async def run_gauntlet(set_id: str, emit: Callable[[str], None] | None = None,
                       only: list[str] | None = None,
                       runs: int = 1) -> dict:
    def log(m: str) -> None:
        if emit:
            emit(m)

    s = load_set(set_id)
    if not s:
        return {"error": f"prompt set '{set_id}' not found"}

    prompts = s.get("prompts", [])
    if only:
        prompts = [p for p in prompts if p.get("id") in set(only)]
    if not prompts:
        return {"error": "no prompts to run"}

    ts = time.strftime("%Y%m%d-%H%M%S")
    model = bench.read_env().get("MODEL_ALIAS", "?")
    log(f"[gauntlet] set={set_id} model={model} prompts={len(prompts)} runs={runs}")

    results: list[dict] = []
    out = GAUNTLET_DIR / f"gauntlet-{ts}.json"

    def persist(done: bool) -> dict:
        card = {"kind": "gauntlet",
               "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "set": set_id,
                "set_title": s.get("title", set_id), "model": model,
                "status": "complete" if done else "running",
                "total": len(prompts), "done": len(results), "results": results}
        out.write_text(json.dumps(card, indent=2))
        return card

    persist(False)

    for i, spec in enumerate(prompts):
        pid = spec.get("id", f"P{i+1}")
        log(f"[gauntlet:prompt] {i+1}/{len(prompts)} {pid} ×{runs}")
        log(f"▶ {pid} — {spec.get('axis','')}")

        run_data: list[dict] = []
        for rn in range(1, runs + 1):
            if runs > 1:
                log(f"  run {rn}/{runs}")
            await bench._probe_scene_reset()
            before = await bench._scene_paths()
            t0 = time.time()
            crashed = False
            raw: dict = {}
            artifact: dict = {}
            apply_args: dict = {"prompt": spec.get("prompt", ""), "temperature": 0.2}
            set_planner = s.get("planner")
            prompt_planner = spec.get("planner")
            planner = prompt_planner or set_planner
            if planner:
                apply_args["planner"] = planner
            try:
                raw = await _with_heartbeat(
                    _devforge_call("apply_spec", apply_args, timeout_s=300),
                    log, f"{pid} R{rn} planning+executing")
                aid = raw.get("artifact_id")
                artifact = raw
                if aid:
                    try:
                        artifact = await _devforge_call("read_artifact", {"artifact_id": aid}, timeout_s=30)
                    except Exception:
                        artifact = raw
            except Exception as e:
                crashed = True
                raw = {"errors": [f"apply_spec crashed: {type(e).__name__}: {e}"]}
            ms = int((time.time() - t0) * 1000)

            after_snap = await _get_scene_snapshot()
            prof = _measure(spec, before, after_snap, artifact, raw, ms, crashed)
            prof.update(id=pid, axis=spec.get("axis", ""), prompt=spec.get("prompt", ""))
            if prof.get("verdict") in ("broke", "partial"):
                try:
                    plugin_logs = await bench._godot_ai_call("logs_read", {"source": "plugin", "count": 15})
                    prof["plugin_logs"] = (plugin_logs.get("lines", []) if isinstance(plugin_logs, dict) else [])[:15]
                except Exception:
                    pass
            # Store full ops for diversity computation
            prof["_ops"] = [o for o in artifact.get("operations", []) if isinstance(o, dict)]
            prof["_arch_delta"] = artifact.get("arch_delta", {})

            run_data.append(prof)
            if runs > 1:
                log(f"    [{prof['verdict']}] {prof['coverage']}% "
                    f"({prof['built_nodes']}n {ms//1000}s)")

        # Aggregate across runs: keep first run's full profile + add stats
        if runs == 1:
            agg = run_data[0]
        else:
            coverages = [r["coverage"] for r in run_data]
            latencies = [r["latency_ms"] for r in run_data]
            mean_cov = round(sum(coverages) / len(coverages))
            std_cov = round((sum((c - mean_cov) ** 2 for c in coverages) / len(coverages)) ** 0.5)
            mean_lat = round(sum(latencies) / len(latencies))
            agg = dict(run_data[0])  # copy to avoid self-referential runs list
            agg["runs"] = run_data
            agg["mean_coverage"] = mean_cov
            agg["stddev_coverage"] = std_cov
            agg["mean_latency_ms"] = mean_lat
            # Stage 4: diversity metrics
            diversity = _compute_diversity(run_data)
            agg["diversity"] = diversity
            # Stage 4: variety checks — pass both run_data (per-prompt runs)
            # and results (all sibling prompt results for intent_coverage)
            _add_variety_checks(
                spec.get("expect", {}), run_data, artifact,
                lambda label, ok, detail: agg.setdefault("variety_checks", []).append(
                    {"label": label, "ok": ok, "detail": detail}),
                results=results,
            )
        results.append(agg)
        persist(False)
        lat = agg.get('mean_latency_ms', agg.get('latency_ms', 0))
        log(f"  [{agg['verdict']}] {agg['coverage']}% — nodes {agg['built_nodes']}, "
            f"depth {agg['built_depth']}, props {agg.get('props',{})}, "
            f"scripts {agg.get('scripts',0)}, err {agg['error_count']} ({lat//1000}s)")

    # restore the real game scene
    try:
        await bench._godot_ai_call("scene_open", {"path": bench.PROBE_SCENE})
        await bench._godot_ai_call("scene_open", {"path": bench.PROBE_BASE_SCENE})
    except Exception:
        pass

    card = persist(True)
    full = sum(1 for r in results if r["verdict"] == "full")
    partial = sum(1 for r in results if r["verdict"] == "partial")
    broke = sum(1 for r in results if r["verdict"] == "broke")
    avg = round(sum(r["coverage"] for r in results) / (len(results) or 1))
    log(f"[gauntlet:done] {full} full / {partial} partial / {broke} broke · "
        f"avg coverage {avg}% → {out.name}")
    card["summary"] = {"full": full, "partial": partial, "broke": broke, "avg_coverage": avg}
    out.write_text(json.dumps(card, indent=2))

    # Stage 4: variety scorecard when runs > 1
    if runs > 1:
        vf = sum(1 for r in results if r.get("variety_checks"))
        if vf > 0:
            log(f"[variety scorecard]")
            for r in results:
                vc = r.get("variety_checks", [])
                dv = r.get("diversity", {})
                if vc:
                    log(f"  {r.get('id', '?')}:")
                    for c in vc:
                        icon = "✓" if c["ok"] else "✗"
                        log(f"    {icon} {c['label']}: {c['detail']}")
                if dv:
                    log(f"    diversity: Jaccard={dv.get('jaccard_distance', 0):.2f} "
                        f"({dv.get('distinct_outputs', 0)}/{dv.get('total_runs', 0)} distinct)")
    return card


def history(limit: int = 30) -> list[dict]:
    runs = []
    for f in sorted(GAUNTLET_DIR.glob("gauntlet-*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(f.read_text())
            runs.append({"file": f.name, "ts": d.get("ts"), "set": d.get("set"),
                         "model": d.get("model"), "summary": d.get("summary"),
                         "status": d.get("status")})
        except Exception:
            continue
    return runs


def get_run(ts: str) -> dict | None:
    fp = GAUNTLET_DIR / f"gauntlet-{ts}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


# ── CLI ──────────────────────────────────────────────────────────

def _cli() -> None:
    args = sys.argv[1:]
    if not args or "--list" in args:
        print("Prompt sets:")
        for s in list_sets():
            print(f"  {s['id']:18} {s['count']:2} prompts  — {s['title']}")
        print("\nRun: python gauntlet.py --run <set-id> [--only G1_depth,G4_children]")
        return
    if "--run" in args:
        set_id = args[args.index("--run") + 1]
        only = None
        runs = 1
        if "--only" in args:
            only = args[args.index("--only") + 1].split(",")
        if "--runs" in args:
            runs = int(args[args.index("--runs") + 1])
        asyncio.run(run_gauntlet(set_id, lambda l: print(l) if not l.startswith("[gauntlet:prompt]") else None, only, runs=runs))
        return
    print("usage: python gauntlet.py [--list | --run <set-id> [--only ids] [--runs N]]")


if __name__ == "__main__":
    _cli()
