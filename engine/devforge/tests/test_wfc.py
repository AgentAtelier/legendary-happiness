"""Unit tests for the WFC (Wave Function Collapse) dungeon engine.

Mirrors test_scatter.py / test_ssp.py. No LLM — the engine is fully
deterministic given a seed. Covers: adjacency symmetry, DungeonSpec defaults,
seed determinism, tile compilation (meshes/positions/bounds/edges), empty-skip,
and the corridor-carving floor-preservation guard.
"""

from __future__ import annotations

import pytest

from devforge.spatial.wfc import (
    WFCEngine,
    DungeonSpec,
    _ALL_TILES,
    _ADJACENCY,
    _TILE_DEFS,
)


@pytest.fixture
def engine():
    return WFCEngine()


def _create_steps(plan):
    return [s for s in plan.steps if getattr(s, "step_type", "") == "create_entity"]


def _prop(plan, suffix, prop):
    for s in plan.steps:
        if (getattr(s, "step_type", "") == "set_property"
                and getattr(s, "property", "") == prop
                and s.node.endswith(suffix)):
            return s.value
    return None


# ── Imports ──────────────────────────────────────────────────────

class TestWFCImports:
    def test_engine_importable(self):
        assert WFCEngine is not None

    def test_dungeonspec_importable(self):
        assert DungeonSpec is not None

    def test_engine_constructs(self, engine):
        assert isinstance(engine, WFCEngine)


# ── Adjacency validation ─────────────────────────────────────────

class TestAdjacencyValidation:
    def test_adjacency_is_symmetric(self):
        """If A allows B as a neighbor, B must allow A (the engine asserts
        this at init; verify the table directly too)."""
        for a in _ALL_TILES:
            for b in _ADJACENCY[a]:
                assert a in _ADJACENCY[b], f"{a}->{b} but {b}!->{a}"

    def test_engine_init_accepts_current_table(self):
        # __init__ runs the symmetry assertion; must not raise.
        WFCEngine()

    def test_every_tile_has_adjacency_and_def(self):
        for t in _ALL_TILES:
            assert t in _ADJACENCY
            assert t in _TILE_DEFS


# ── DungeonSpec ──────────────────────────────────────────────────

class TestDungeonSpec:
    def test_defaults(self):
        spec = DungeonSpec()
        assert spec.width == 8 and spec.depth == 8
        assert spec.tile_size == 2.0
        assert spec.seed == 42

    def test_override(self):
        spec = DungeonSpec(width=12, depth=10, tile_size=1.5, seed=7)
        assert (spec.width, spec.depth, spec.tile_size, spec.seed) == (12, 10, 1.5, 7)


# ── Seed determinism ─────────────────────────────────────────────

class TestSeedDeterminism:
    def _names_positions(self, plan):
        out = []
        for s in plan.steps:
            if getattr(s, "step_type", "") == "set_property" and s.property == "position":
                out.append((s.node, s.value["x"], s.value["z"]))
        return out

    def test_same_seed_is_identical(self, engine):
        j = {"size": {"width": 8, "depth": 8}, "tile_size": 2.0, "seed": 123}
        a = engine.compile_dungeon(dict(j))
        b = engine.compile_dungeon(dict(j))
        assert self._names_positions(a) == self._names_positions(b)

    def test_grid_shape_is_deterministic(self, engine):
        grid = engine._wfc_collapse(8, 6, seed=5)
        assert len(grid) == 6  # depth rows
        assert all(len(row) == 8 for row in grid)  # width cols

    def test_every_cell_is_a_valid_tile(self, engine):
        grid = engine._wfc_collapse(10, 7, seed=99)
        for row in grid:
            for cell in row:
                assert cell in _ALL_TILES


# ── Tile compilation ─────────────────────────────────────────────

class TestCompileDungeon:
    def test_produces_nodes(self, engine):
        plan = engine.compile_dungeon({"size": {"width": 8, "depth": 8}, "seed": 1})
        assert len(_create_steps(plan)) > 0

    def test_all_nodes_are_meshinstance3d(self, engine):
        plan = engine.compile_dungeon({"size": {"width": 6, "depth": 6}, "seed": 1})
        for s in _create_steps(plan):
            assert s.node_type == "MeshInstance3D"

    def test_floor_uses_plane_wall_uses_box(self, engine):
        plan = engine.compile_dungeon({"size": {"width": 8, "depth": 8}, "seed": 3})
        floor_mesh = _prop(plan, _first_name(plan, "floor"), "mesh") if _has(plan, "floor") else None
        wall_mesh = _prop(plan, _first_name(plan, "wall"), "mesh") if _has(plan, "wall") else None
        if floor_mesh:
            assert floor_mesh["__class__"] == "PlaneMesh"
        if wall_mesh:
            assert wall_mesh["__class__"] == "BoxMesh"

    def test_edges_are_walls(self, engine):
        """The scaffold collapses the grid border to walls."""
        grid = engine._wfc_collapse(8, 8, seed=2)
        w, d = 8, 8
        for col in range(w):
            assert grid[0][col] == "wall"
            assert grid[d - 1][col] == "wall"
        for row in range(d):
            assert grid[row][0] == "wall"
            assert grid[row][w - 1] == "wall"

    def test_positions_within_bounds(self, engine):
        w, d, ts = 8, 8, 2.0
        plan = engine.compile_dungeon({"size": {"width": w, "depth": d}, "tile_size": ts, "seed": 4})
        for s in plan.steps:
            if getattr(s, "step_type", "") == "set_property" and s.property == "position":
                assert 0 <= s.value["x"] <= w * ts
                assert 0 <= s.value["z"] <= d * ts

    def test_tile_size_scales_positions(self, engine):
        plan = engine.compile_dungeon({"size": {"width": 6, "depth": 6}, "tile_size": 4.0, "seed": 1})
        # any tile at col c, row r → position ((c+0.5)*4, _, (r+0.5)*4); all on the 2.0 grid
        for s in plan.steps:
            if getattr(s, "step_type", "") == "set_property" and s.property == "position":
                # (val/4 - 0.5) must be a whole number (integer grid cell)
                cx = s.value["x"] / 4.0 - 0.5
                assert abs(cx - round(cx)) < 1e-6

    def test_no_empty_tiles_emitted(self, engine):
        plan = engine.compile_dungeon({"size": {"width": 8, "depth": 8}, "seed": 6})
        for s in _create_steps(plan):
            assert not s.name.startswith("empty_")

    def test_small_grid_does_not_crash(self, engine):
        for w, d in ((3, 3), (4, 4), (2, 2), (12, 12)):
            engine.compile_dungeon({"size": {"width": w, "depth": d}, "seed": 1})


# ── Corridor carving guard ───────────────────────────────────────

class TestCorridorCarving:
    def test_carve_preserves_resolved_room_floor(self, engine):
        """A carved doorway must NOT overwrite a cell already resolved to a
        room floor (that fragments the room). Regression: the original guard's
        `continue` skipped the inner loop, not the carve, so it was a no-op."""
        W, D = 7, 3
        wave = [[set(_ALL_TILES) for _ in range(W)] for _ in range(D)]
        # Horizontal carve site at row 1, col 3: flanking floors at col 1 and 5.
        wave[1][1] = {"floor"}   # col-2 (left cluster)
        wave[1][5] = {"floor"}   # col+2 (right cluster)
        wave[1][2] = {"floor"}   # col-1: a RESOLVED ROOM FLOOR — must survive
        engine._carve_corridors(wave, W, D)
        assert wave[1][2] == {"floor"}, (
            f"carved doorway overwrote a room floor: {wave[1][2]}")

    def test_carve_through_walls_still_works(self, engine):
        """Carving must still punch a corridor when the gap is walls/unresolved
        (that's its whole job) — the floor guard must not over-block."""
        W, D = 7, 3
        wave = [[set(_ALL_TILES) for _ in range(W)] for _ in range(D)]
        wave[1][1] = {"floor"}
        wave[1][5] = {"floor"}
        wave[1][2] = {"wall"}     # col-1 is a wall — carving through is allowed
        wave[1][3] = set(_ALL_TILES)  # center unresolved
        wave[1][4] = {"wall"}
        engine._carve_corridors(wave, W, D)
        assert wave[1][3] == {"corridor"}, f"corridor not carved: {wave[1][3]}"

    def test_carve_does_not_crash_on_full_grid(self, engine):
        wave = [[set(_ALL_TILES) for _ in range(10)] for _ in range(10)]
        engine._carve_corridors(wave, 10, 10)


# ── small helpers for the mesh test ──────────────────────────────

def _has(plan, tile):
    return any(s.name.startswith(tile + "_") for s in _create_steps(plan))


def _first_name(plan, tile):
    for s in _create_steps(plan):
        if s.name.startswith(tile + "_"):
            return s.name
    return tile
