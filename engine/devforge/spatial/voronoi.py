"""Voronoi Engine — district/town generation via Voronoi tessellation.

Partitions a region into N districts (Voronoi cells) by placing seed
points, then assigning every tile to its nearest seed.  District boundaries
become roads, and each district gets a cluster of buildings.

The LLM is a topologist — it never outputs a Vector3.  It emits
town specs (region size, district count).  The engine computes
Voronoi cells and resolves everything into absolute transforms.

This is the "outside" macro scale — Engine 5 of 5.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from devforge.compilation.ir.plan import (
    DevForgePlan,
    CreateEntityStep,
    SetPropertyStep,
)
from devforge.infrastructure.logger import logger

# ── Constants ────────────────────────────────────────────────────

_DEFAULT_SEED: int = 42
_DEFAULT_TILE_SIZE: float = 4.0
_DEFAULT_DISTRICTS: int = 5

# District type → colour
_DISTRICT_COLORS: Dict[str, List[float]] = {
    "residential":   [0.35, 0.55, 0.85],  # blue-grey
    "commercial":    [0.90, 0.45, 0.30],  # warm orange
    "industrial":    [0.55, 0.50, 0.45],  # grey
    "park":          [0.30, 0.65, 0.35],  # green
    "civic":         [0.85, 0.80, 0.55],  # sandstone
    "waterfront":    [0.25, 0.50, 0.70],  # deep blue
    "default":       [0.60, 0.55, 0.50],  # neutral earth
}

# Building dimensions per district type (min/max width, depth, height)
_BUILDING_DIMS: Dict[str, Tuple[float, float, float, float, float]] = {
    "residential":   (2.0, 4.0, 2.0, 3.0, 2.0, 3.0),
    "commercial":    (3.0, 6.0, 2.5, 4.0, 3.0, 6.0),
    "industrial":    (4.0, 8.0, 3.0, 5.0, 3.0, 8.0),
    "park":          (1.0, 2.0, 1.0, 2.0, 1.0, 2.0),
    "civic":         (4.0, 8.0, 3.0, 6.0, 4.0, 10.0),
    "waterfront":    (2.0, 5.0, 2.0, 4.0, 2.0, 5.0),
    "default":       (2.0, 4.0, 2.0, 3.0, 2.0, 4.0),
}

# Buildings per district
_BUILDINGS_PER_DISTRICT: Dict[str, Tuple[int, int]] = {
    "residential":   (4, 8),
    "commercial":    (2, 5),
    "industrial":    (1, 3),
    "park":          (1, 3),
    "civic":         (1, 2),
    "waterfront":    (2, 4),
    "default":       (2, 4),
}


# ── Data types ────────────────────────────────────────────────────


@dataclass
class TownSpec:
    """What kind of town to generate."""
    width: int = 80        # region width in metres
    depth: int = 80        # region depth in metres
    districts: int = _DEFAULT_DISTRICTS
    tile_size: float = _DEFAULT_TILE_SIZE
    seed: int = _DEFAULT_SEED


# ── Engine ────────────────────────────────────────────────────────


class VoronoiEngine:
    """Voronoi town/district generator.

    Usage::

        v = VoronoiEngine()
        plan = v.compile_town(town_json, root_path="/root/Main")
        # plan.steps → roads + district grounds + buildings
    """

    def __init__(self):
        pass

    # ── public API ────────────────────────────────────────────────

    def compile_town(
        self,
        town_json: dict,
        root_path: str = "/root/Main",
    ) -> DevForgePlan:
        """Compile a town JSON into a DevForgePlan.

        Args:
            town_json: LLM output with ``region`` (width, depth),
                       ``districts`` (count), optional ``tile_size``, ``seed``.
            root_path: Godot node path to the scene root.

        Returns:
            DevForgePlan with CreateEntityStep + SetPropertyStep for
            district grounds, roads, and buildings.
        """
        region = town_json.get("region", {})
        spec = TownSpec(
            width=int(region.get("width", 80)),
            depth=int(region.get("depth", 80)),
            districts=int(town_json.get("districts", _DEFAULT_DISTRICTS)),
            tile_size=float(town_json.get("tile_size", _DEFAULT_TILE_SIZE)),
            seed=int(town_json.get("seed", _DEFAULT_SEED)),
        )
        rng = random.Random(spec.seed)

        # Place Voronoi seed points (jittered grid)
        seeds = self._place_seeds(spec, rng)

        # Assign district types
        district_types = self._assign_types(spec.districts, rng)

        # Build Voronoi cell map
        cols = max(1, int(spec.width / spec.tile_size))
        rows = max(1, int(spec.depth / spec.tile_size))
        cell_map: List[List[int]] = [[0] * cols for _ in range(rows)]
        for row in range(rows):
            for col in range(cols):
                cx = (col + 0.5) * spec.tile_size
                cz = (row + 0.5) * spec.tile_size
                # Nearest seed
                best_i = 0
                best_d2 = float("inf")
                for i, (sx, sz) in enumerate(seeds):
                    d2 = (cx - sx) ** 2 + (cz - sz) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best_i = i
                cell_map[row][col] = best_i

        # Identify road cells (where neighbors differ)
        road: List[List[bool]] = [
            [False] * cols for _ in range(rows)
        ]
        for row in range(rows):
            for col in range(cols):
                d = cell_map[row][col]
                for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < cols and 0 <= nr < rows:
                        if cell_map[nr][nc] != d:
                            road[row][col] = True
                            break

        # Collect buildings per district
        district_buildings: Dict[int, List[Tuple[float, float, float, float, float, List[float]]]] = {}
        for i in range(spec.districts):
            district_buildings[i] = []
            dtype = district_types[i]
            dims = _BUILDING_DIMS.get(dtype, _BUILDING_DIMS["default"])
            bcount = _BUILDINGS_PER_DISTRICT.get(dtype, _BUILDINGS_PER_DISTRICT["default"])
            n = rng.randint(*bcount)
            color = _DISTRICT_COLORS.get(dtype, _DISTRICT_COLORS["default"])

            # Find cells belonging to this district
            district_cells: List[Tuple[int, int]] = []
            for row in range(rows):
                for col in range(cols):
                    if cell_map[row][col] == i and not road[row][col]:
                        district_cells.append((col, row))

            # Place buildings in random district cells
            rng.shuffle(district_cells)
            placed = 0
            for col, row in district_cells:
                if placed >= n:
                    break
                bw = rng.uniform(dims[0], dims[1])
                bd = rng.uniform(dims[2], dims[3])
                bh = rng.uniform(dims[4], dims[5])
                # Jitter within cell to avoid exact cell centers
                cx_base = (col + 0.5) * spec.tile_size
                cz_base = (row + 0.5) * spec.tile_size
                jx = rng.uniform(-0.3, 0.3) * spec.tile_size
                jz = rng.uniform(-0.3, 0.3) * spec.tile_size
                district_buildings[i].append((
                    cx_base + jx, cz_base + jz, bw, bd, bh, color,
                ))
                placed += 1

        # ── Compile into plan ──
        steps: List = []
        node_count = 0

        # Single shared ground plane for the entire town
        steps.append(CreateEntityStep(
            name="TownGround",
            node_type="MeshInstance3D",
            parent=root_path,
        ))
        steps.append(SetPropertyStep(
            node=f"{root_path}/TownGround",
            property="position",
            value={"x": spec.width / 2, "y": -0.01, "z": spec.depth / 2},
        ))
        steps.append(SetPropertyStep(
            node=f"{root_path}/TownGround",
            property="mesh",
            value={
                "__class__": "PlaneMesh",
                "size": {"x": spec.width, "y": spec.depth},
            },
        ))
        steps.append(SetPropertyStep(
            node=f"{root_path}/TownGround",
            property="material_override",
            value={
                "__class__": "StandardMaterial3D",
                "albedo_color": {
                    "r": 0.28, "g": 0.42, "b": 0.22, "a": 1.0,
                },
            },
        ))
        node_count += 1

        # Road tiles
        road_step = 0
        for row in range(rows):
            for col in range(cols):
                if road[row][col]:
                    name = f"road_{col}_{row}"
                    node_path = f"{root_path}/{name}"
                    cx = (col + 0.5) * spec.tile_size
                    cz = (row + 0.5) * spec.tile_size

                    steps.append(CreateEntityStep(
                        name=name,
                        node_type="MeshInstance3D",
                        parent=root_path,
                    ))
                    steps.append(SetPropertyStep(
                        node=node_path,
                        property="position",
                        value={"x": cx, "y": 0.02, "z": cz},
                    ))
                    steps.append(SetPropertyStep(
                        node=node_path,
                        property="mesh",
                        value={
                            "__class__": "PlaneMesh",
                            "size": {
                                "x": spec.tile_size,
                                "y": spec.tile_size,
                            },
                        },
                    ))
                    steps.append(SetPropertyStep(
                        node=node_path,
                        property="material_override",
                        value={
                            "__class__": "StandardMaterial3D",
                            "albedo_color": {
                                "r": 0.25, "g": 0.24, "b": 0.23, "a": 1.0,
                            },
                        },
                    ))
                    road_step += 1

        node_count += road_step

        # Buildings
        for i, buildings in district_buildings.items():
            dtype = district_types[i]
            for bi, (bx, bz, bw, bd, bh, bcolor) in enumerate(buildings):
                name = f"bld_{dtype}_{i}_{bi}"
                node_path = f"{root_path}/{name}"

                steps.append(CreateEntityStep(
                    name=name,
                    node_type="MeshInstance3D",
                    parent=root_path,
                ))
                steps.append(SetPropertyStep(
                    node=node_path,
                    property="position",
                    value={"x": bx, "y": bh / 2, "z": bz},
                ))
                steps.append(SetPropertyStep(
                    node=node_path,
                    property="mesh",
                    value={
                        "__class__": "BoxMesh",
                        "size": {"x": bw, "y": bh, "z": bd},
                    },
                ))
                steps.append(SetPropertyStep(
                    node=node_path,
                    property="material_override",
                    value={
                        "__class__": "StandardMaterial3D",
                        "albedo_color": {
                            "r": bcolor[0] * 0.8,
                            "g": bcolor[1] * 0.8,
                            "b": bcolor[2] * 0.8,
                            "a": 1.0,
                        },
                    },
                ))
                node_count += 1

        logger.info(
            "voronoi",
            f"Compiled town: {spec.width}×{spec.depth}m, "
            f"{spec.districts} districts ({cols}×{rows} tiles), "
            f"{road_step} roads, {node_count} nodes",
        )

        return DevForgePlan(
            goal=f"Voronoi town: {spec.width}×{spec.depth}m, "
                 f"{spec.districts} districts ({node_count} nodes)",
            steps=steps,
        )

    # ── internals ─────────────────────────────────────────────────

    def _place_seeds(self, spec: TownSpec, rng: random.Random) -> List[Tuple[float, float]]:
        """Place N seed points in the region using jittered grid."""
        n = spec.districts
        if n <= 1:
            return [(spec.width / 2, spec.depth / 2)]

        # Approximate grid: sqrt(N) cells per axis
        grid_cols = max(1, int(n ** 0.5))
        grid_rows = max(1, (n + grid_cols - 1) // grid_cols)
        cell_w = spec.width / grid_cols
        cell_d = spec.depth / grid_rows

        seeds: List[Tuple[float, float]] = []
        for i in range(n):
            gx = i % grid_cols
            gy = i // grid_cols
            cx = (gx + 0.5) * cell_w
            cz = (gy + 0.5) * cell_d
            # Jitter within cell (keep 10% margin from edges)
            jx = rng.uniform(-0.35, 0.35) * cell_w
            jz = rng.uniform(-0.35, 0.35) * cell_d
            seeds.append((
                max(cell_w * 0.1, min(spec.width - cell_w * 0.1, cx + jx)),
                max(cell_d * 0.1, min(spec.depth - cell_d * 0.1, cz + jz)),
            ))

        return seeds

    def _assign_types(self, n: int, rng: random.Random) -> List[str]:
        """Assign district types with weighted distribution."""
        weights = [
            ("residential", 4),
            ("commercial", 2),
            ("industrial", 1),
            ("park", 2),
            ("civic", 1),
        ]
        pool = []
        for t, w in weights:
            pool.extend([t] * w)

        types: List[str] = []
        for i in range(n):
            if i == 0:
                types.append("civic")  # centre is civic
            else:
                types.append(rng.choice(pool))

        return types
