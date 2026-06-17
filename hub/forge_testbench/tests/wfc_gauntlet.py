"""WFC dungeon gauntlet tests — migrated from gauntlet.py wfc-v1 set.

Wave Function Collapse dungeon/cave generation: LLM picks grid size +
tile size; deterministic WFC engine collapses tilemap with adjacency
constraints. Covers small dungeon, large dungeon, caves, and corridors.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class WfcW1SmallDungeon(Test):
    id = "wfc.W1_small_dungeon"
    category = "capability"
    title = "WFC: small dungeon"
    description = "8×8 dungeon with rooms and corridors, 2m tiles."
    suites = ["everything", "wfc-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Generate a small 8x8 dungeon with rooms and connecting corridors. Use tile size 2.0m.", "wfc"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 20, "min_wfc_tiles": 20, "wfc_in_bounds": True, "wfc_has_walls": True, "wfc_has_floor": True},
            raw,
        )


@register
class WfcW2LargeDungeon(Test):
    id = "wfc.W2_large_dungeon"
    category = "capability"
    title = "WFC: large dungeon"
    description = "12×12 dungeon with multiple rooms, 2m tiles."
    suites = ["everything", "wfc-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a large 12x12 dungeon with multiple rooms. Tile size 2.0m.", "wfc")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 40, "min_wfc_tiles": 40, "wfc_in_bounds": True, "wfc_has_walls": True, "wfc_has_floor": True},
            raw,
        )


@register
class WfcW3Caves(Test):
    id = "wfc.W3_caves"
    category = "capability"
    title = "WFC: cave system"
    description = "8×8 cave system with 2.5m tiles for larger chambers."
    suites = ["everything", "wfc-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Create a cave system. 8x8 grid with 2.5m tile size for larger chambers.", "wfc")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id, {"min_nodes": 15, "min_wfc_tiles": 15, "wfc_in_bounds": True, "wfc_has_floor": True}, raw
        )


@register
class WfcW4Corridors(Test):
    id = "wfc.W4_corridors"
    category = "capability"
    title = "WFC: corridor maze"
    description = "12×12 tight corridor maze with 1.5m tiles."
    suites = ["everything", "wfc-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Generate a tight corridor maze. 12x12 dungeon with 1.5m tile size.", "wfc")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 30, "min_wfc_tiles": 30, "wfc_in_bounds": True, "wfc_has_walls": True, "wfc_has_floor": True},
            raw,
        )
