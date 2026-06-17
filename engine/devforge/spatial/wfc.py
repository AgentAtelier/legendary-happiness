"""WFC Engine — Wave Function Collapse for dungeon/cave generation.

Constraint-based tile placement: adjacency rules define which tiles
can neighbor each other. The engine initialises a grid with all
possibilities, picks the lowest-entropy cell, collapses it, and
propagates constraints until the grid stabilises.

The LLM is a topologist — it never outputs a Vector3. It emits
dungeon specs (size, tile proportions, room count). The engine
runs WFC and resolves every cell into absolute transforms.

See SPATIAL-STAGE-3-5-PLAN.md §5 for the full design.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from devforge.compilation.ir.plan import (
    DevForgePlan,
    CreateEntityStep,
    SetPropertyStep,
)
from devforge.infrastructure.logger import logger

# ── Constants ────────────────────────────────────────────────────

_DEFAULT_SEED: int = 42
_DEFAULT_TILE_SIZE: float = 2.0

# Tile types and their greybox appearance
_TILE_DEFS: Dict[str, dict] = {
    "floor": {
        "label": "Floor",
        "mesh": "plane",
        "color": [0.35, 0.33, 0.30],
        "height": 0.1,
    },
    "wall": {
        "label": "Wall",
        "mesh": "box",
        "color": [0.55, 0.50, 0.45],
        "height": 3.0,
    },
    "corridor": {
        "label": "Corridor",
        "mesh": "plane",
        "color": [0.40, 0.38, 0.35],
        "height": 0.1,
    },
    "door": {
        "label": "Door",
        "mesh": "box",
        "color": [0.45, 0.35, 0.25],
        "height": 2.0,
    },
    "empty": {
        "label": "Empty",
        "mesh": None,  # no mesh, treated as void
        "color": [0, 0, 0],
        "height": 0,
    },
}

# Adjacency rules: for each tile, which tiles can be next to it.
# Symmetric: if A allows B, B must also allow A (enforced at init).
_ADJACENCY: Dict[str, Set[str]] = {
    "floor":    {"floor", "corridor", "door", "wall"},
    "wall":     {"wall", "floor", "door", "empty"},
    "corridor": {"corridor", "floor", "door"},
    "door":     {"door", "floor", "corridor", "wall"},
    "empty":    {"empty", "wall"},
}

# All tile types
_ALL_TILES: Tuple[str, ...] = ("floor", "wall", "corridor", "door", "empty")


# ── Data types ────────────────────────────────────────────────────


@dataclass
class DungeonSpec:
    """What kind of dungeon to generate."""
    width: int = 8         # grid columns
    depth: int = 8         # grid rows
    tile_size: float = _DEFAULT_TILE_SIZE
    seed: int = _DEFAULT_SEED


# ── Engine ────────────────────────────────────────────────────────


class WFCEngine:
    """Wave Function Collapse dungeon generator.

    Usage::

        wfc = WFCEngine()
        plan = wfc.compile_dungeon(dungeon_json, root_path="/root/Main")
        # plan.steps → floor planes + wall boxes + door boxes per tile
    """

    def __init__(self):
        self._tile_ids = list(_ALL_TILES)
        # Validate adjacency symmetry
        for t1 in _ALL_TILES:
            for t2 in _ADJACENCY[t1]:
                assert t1 in _ADJACENCY[t2], (
                    f"Adjacency asymmetry: {t1}→{t2} but {t2}↛{t1}"
                )

    # ── public API ────────────────────────────────────────────────

    def compile_dungeon(
        self,
        dungeon_json: dict,
        root_path: str = "/root/Main",
    ) -> DevForgePlan:
        """Compile a dungeon JSON into a DevForgePlan.

        Args:
            dungeon_json: LLM output with ``size`` (width, depth),
                          ``tile_size``, optional ``seed``.
            root_path: Godot node path to the scene root.

        Returns:
            DevForgePlan with CreateEntityStep + SetPropertyStep for
            each non-empty tile in the dungeon.
        """
        size_spec = dungeon_json.get("size", {})
        spec = DungeonSpec(
            width=int(size_spec.get("width", 8)),
            depth=int(size_spec.get("depth", 8)),
            tile_size=float(dungeon_json.get("tile_size", _DEFAULT_TILE_SIZE)),
            seed=int(dungeon_json.get("seed", _DEFAULT_SEED)),
        )

        # Run WFC to get the tile map
        tile_map = self._wfc_collapse(spec.width, spec.depth, spec.seed)

        # Compile tiles into plan steps
        steps: List = []
        tile_count = 0

        for row in range(spec.depth):
            for col in range(spec.width):
                tile = tile_map[row][col]
                if tile == "empty":
                    continue

                tile_def = _TILE_DEFS.get(tile)
                if tile_def is None or tile_def.get("mesh") is None:
                    continue

                tile_count += 1
                name = f"{tile}_{col}_{row}"
                node_path = f"{root_path}/{name}"

                steps.append(CreateEntityStep(
                    name=name,
                    node_type="MeshInstance3D",
                    parent=root_path,
                ))

                # Position: centre of grid cell
                x = (col + 0.5) * spec.tile_size
                z = (row + 0.5) * spec.tile_size
                height = tile_def["height"]
                y = height / 2  # sit on ground

                steps.append(SetPropertyStep(
                    node=node_path,
                    property="position",
                    value={"x": x, "y": y, "z": z},
                ))

                # Mesh
                mesh_type = tile_def["mesh"]
                if mesh_type == "plane":
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
                elif mesh_type == "box":
                    steps.append(SetPropertyStep(
                        node=node_path,
                        property="mesh",
                        value={
                            "__class__": "BoxMesh",
                            "size": {
                                "x": spec.tile_size * 0.9,  # slight gap
                                "y": height,
                                "z": spec.tile_size * 0.9,
                            },
                        },
                    ))

                # Material
                color = tile_def["color"]
                steps.append(SetPropertyStep(
                    node=node_path,
                    property="material_override",
                    value={
                        "__class__": "StandardMaterial3D",
                        "albedo_color": {
                            "r": color[0], "g": color[1], "b": color[2], "a": 1.0,
                        },
                    },
                ))

        logger.info(
            "wfc",
            f"Compiled dungeon: {spec.width}×{spec.depth}, "
            f"{tile_count} tiles ({spec.tile_size:.1f}m per tile)",
        )

        return DevForgePlan(
            goal=f"WFC dungeon: {spec.width}×{spec.depth} ({tile_count} tiles)",
            steps=steps,
        )

    # ── WFC algorithm ─────────────────────────────────────────────

    def _wfc_collapse(
        self, width: int, depth: int, seed: int,
    ) -> List[List[str]]:
        """Run WFC to produce a tile map of (depth × width)."""
        rng = random.Random(seed)

        # Initialise: every cell can be any tile
        wave: List[List[Set[str]]] = [
            [set(_ALL_TILES) for _ in range(width)]
            for _ in range(depth)
        ]

        # ── Initialise edges as walls (scaffold) ──
        for col in range(width):
            self._collapse_cell(wave, col, 0, "wall", width, depth)
            self._collapse_cell(wave, col, depth - 1, "wall", width, depth)
        for row in range(1, depth - 1):
            self._collapse_cell(wave, 0, row, "wall", width, depth)
            self._collapse_cell(wave, width - 1, row, "wall", width, depth)

        # ── Seed the interior with a floor tile ──
        if width > 2 and depth > 2:
            cx = width // 2
            cz = depth // 2
            self._collapse_cell(wave, cx, cz, "floor", width, depth)

            # Expand a room cluster from centre
            for dx in range(-1, 2):
                for dz in range(-1, 2):
                    nx, nz = cx + dx, cz + dz
                    if 0 < nx < width - 1 and 0 < nz < depth - 1:
                        if wave[nz][nx] == set(_ALL_TILES):
                            self._collapse_cell(wave, nx, nz, "floor", width, depth)

        # ── Collapse remaining cells ──
        for _ in range(10):  # multiple propagation passes
            changed = False
            for row in range(1, depth - 1):
                for col in range(1, width - 1):
                    cell = wave[row][col]
                    if len(cell) == 0:
                        # Dead cell → make it a wall
                        wave[row][col] = {"wall"}
                        changed = True
                    elif len(cell) == 1:
                        continue  # already collapsed
                    else:
                        # Reduce possibilities based on neighbors
                        prev = len(cell)
                        self._propagate_constraints(wave, col, row, width, depth)
                        if len(wave[row][col]) < prev:
                            changed = True
            if not changed:
                break

        # ── Collapse remaining unresolved cells ──
        for row in range(1, depth - 1):
            for col in range(1, width - 1):
                cell = wave[row][col]
                if len(cell) > 1:
                    # Pick from remaining possibilities, weighted toward floor
                    options = list(cell)
                    if "floor" in options and rng.random() < 0.7:
                        chosen = "floor"
                    elif "corridor" in options and rng.random() < 0.5:
                        chosen = "corridor"
                    else:
                        chosen = rng.choice(options)
                    self._collapse_cell(wave, col, row, chosen, width, depth)

        # ── Carve corridors between floor clusters ──
        self._carve_corridors(wave, width, depth)

        # Convert sets to strings
        result: List[List[str]] = []
        for row in range(depth):
            line: List[str] = []
            for col in range(width):
                cell = wave[row][col]
                if len(cell) == 1:
                    line.append(next(iter(cell)))
                else:
                    line.append("wall")  # fallback
            result.append(line)

        return result

    def _collapse_cell(
        self,
        wave: List[List[Set[str]]],
        col: int, row: int,
        tile: str,
        width: int, depth: int,
    ) -> None:
        """Set a cell to a specific tile and propagate constraints."""
        wave[row][col] = {tile}
        self._propagate_constraints(wave, col, row, width, depth)

    def _propagate_constraints(
        self,
        wave: List[List[Set[str]]],
        col: int, row: int,
        width: int, depth: int,
    ) -> None:
        """Propagate adjacency constraints from a cell to its neighbors."""
        cell = wave[row][col]
        if len(cell) == 0:
            return

        # What adjacency union does this cell allow?
        allowed_neighbors: Set[str] = set()
        for t in cell:
            allowed_neighbors |= _ADJACENCY.get(t, set())

        # Constrain each neighbor
        for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nc, nr = col + dc, row + dr
            if 0 <= nc < width and 0 <= nr < depth:
                neighbor = wave[nr][nc]
                if len(neighbor) > 1:
                    # Restrict neighbor to tiles compatible with this cell
                    new_neighbor = neighbor & allowed_neighbors
                    if new_neighbor != neighbor:
                        wave[nr][nc] = new_neighbor
                        if len(new_neighbor) == 1:
                            # Recurse to propagate further
                            self._propagate_constraints(
                                wave, nc, nr, width, depth,
                            )

    def _carve_corridors(
        self,
        wave: List[List[Set[str]]],
        width: int, depth: int,
    ) -> None:
        """Connect isolated floor regions with corridor paths."""
        # Simple horizontal/vertical connection scan
        for row in range(1, depth - 1):
            for col in range(2, width - 2):
                cell = wave[row][col]
                if len(cell) == 1:
                    continue
                # If neighbors on both sides are floor → make corridor
                left = wave[row][col - 2]
                right = wave[row][col + 2]
                if (len(left) == 1 and "floor" in left and
                        len(right) == 1 and "floor" in right):
                    # Don't punch a doorway into a cell already resolved as a
                    # room FLOOR — that fragments the room. Walls / unresolved
                    # cells are fine to carve through (that IS the corridor's
                    # job). (Fix 2026-06-16: the prior guard's `continue`
                    # skipped the inner loop, not the carve, so it was a no-op.)
                    if any(wave[row][col + dc] == {"floor"} for dc in (-1, 1)):
                        continue
                    self._collapse_cell(wave, col - 1, row, "door", width, depth)
                    self._collapse_cell(wave, col, row, "corridor", width, depth)
                    self._collapse_cell(wave, col + 1, row, "door", width, depth)

        for col in range(1, width - 1):
            for row in range(2, depth - 2):
                cell = wave[row][col]
                if len(cell) == 1:
                    continue
                top = wave[row - 2][col]
                bottom = wave[row + 2][col]
                if (len(top) == 1 and "floor" in top and
                        len(bottom) == 1 and "floor" in bottom):
                    # Same floor-preservation guard as the horizontal scan.
                    if any(wave[row + dr][col] == {"floor"} for dr in (-1, 1)):
                        continue
                    self._collapse_cell(wave, col, row - 1, "door", width, depth)
                    self._collapse_cell(wave, col, row, "corridor", width, depth)
                    self._collapse_cell(wave, col, row + 1, "door", width, depth)
