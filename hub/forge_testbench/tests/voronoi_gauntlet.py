"""Voronoi town gauntlet tests — migrated from gauntlet.py voronoi-v1 set.

Voronoi district/town generation: LLM picks region size + district count;
deterministic engine computes Voronoi cells, roads, and buildings.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class VoronoiV1Village(Test):
    id = "voronoi.V1_village"
    category = "capability"
    title = "Voronoi: village"
    description = "Small village with 4 districts in 60×60m region."
    suites = ["everything", "voronoi-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a small village with 4 districts. Use a 60x60 metre region.", "voronoi")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 20, "min_voronoi_roads": 5, "voronoi_in_bounds": True, "voronoi_has_districts": 4},
            raw,
        )


@register
class VoronoiV2Town(Test):
    id = "voronoi.V2_town"
    category = "capability"
    title = "Voronoi: medium town"
    description = "6-district town in 80×80m region with 4m tile size."
    suites = ["everything", "voronoi-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Generate a medium town with 6 districts. Use an 80x80 metre region and 4m tile size.", "voronoi"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 30, "min_voronoi_roads": 10, "voronoi_in_bounds": True, "voronoi_has_districts": 6},
            raw,
        )


@register
class VoronoiV3City(Test):
    id = "voronoi.V3_city"
    category = "capability"
    title = "Voronoi: small city"
    description = "10-district city in 100×100m region."
    suites = ["everything", "voronoi-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a small city with 10 districts in a 100x100 metre region.", "voronoi")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 40, "min_voronoi_roads": 15, "voronoi_in_bounds": True, "voronoi_has_districts": 10},
            raw,
        )


@register
class VoronoiV4Industrial(Test):
    id = "voronoi.V4_industrial"
    category = "capability"
    title = "Voronoi: industrial park"
    description = "5-district industrial park in 100×80m region."
    suites = ["everything", "voronoi-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Create an industrial park with 5 districts in a 100x80 metre region.", "voronoi"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {"min_nodes": 15, "min_voronoi_roads": 5, "voronoi_in_bounds": True, "voronoi_has_districts": 5},
            raw,
        )
