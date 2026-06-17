"""Spatial layout gauntlet tests — migrated from gauntlet.py spatial-v1 set.

Room generation via the layout planner: pattern selection, slot→asset
assignment, non-clipping placement from greybox primitives.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class SpatialS1Kitchen(Test):
    id = "spatial.S1_kitchen"
    category = "capability"
    title = "Spatial: basic kitchen"
    description = "Medium kitchen with stove, fridge, counter, and center table."
    suites = ["everything", "spatial-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build a medium kitchen with a stove, a fridge, and a counter along the north wall. Put a table in the center.",
            "layout",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 5, "min_spatial_assets": 3, "no_overlap": True}, raw)


@register
class SpatialS2LKitchen(Test):
    id = "spatial.S2_L_kitchen"
    category = "capability"
    title = "Spatial: L-shaped kitchen"
    description = "L-shaped kitchen with cooking wing and dining wing."
    suites = ["everything", "spatial-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build an L-shaped kitchen. Put a stove and counter in the main cooking wing, and a table with two chairs in the dining wing.",
            "layout",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 5, "min_spatial_assets": 5, "no_overlap": True}, raw)


@register
class SpatialS3Corridor(Test):
    id = "spatial.S3_corridor"
    category = "capability"
    title = "Spatial: corridor"
    description = "10-metre corridor with shelves along both walls."
    suites = ["everything", "spatial-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a long corridor, 10 metres. Place shelves along both walls.", "layout")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 3, "min_spatial_assets": 2, "no_overlap": True}, raw)


@register
class SpatialS4Adjacency(Test):
    id = "spatial.S4_adjacency"
    category = "capability"
    title = "Spatial: ARCS adjacency"
    description = "Stove immediately to the right of the fridge via ARCS override."
    suites = ["everything", "spatial-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build a kitchen and place the stove immediately to the right of the fridge using an ARCS override.",
            "layout",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 4, "min_spatial_assets": 2, "no_overlap": True}, raw)
