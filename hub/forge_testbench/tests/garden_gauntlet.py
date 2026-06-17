"""Scatter garden gauntlet tests — migrated from gauntlet.py garden-v1 set.

Outdoor scatter: Poisson-disk tree/bush/flower/rock placement with
keep-out zones. LLM emits species + counts; deterministic engine
samples positions.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class GardenG1Simple(Test):
    id = "garden.G1_simple_garden"
    category = "capability"
    title = "Scatter: simple garden"
    description = "5 trees + 10 bushes with spacing constraints."
    suites = ["everything", "garden-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Scatter 5 trees and 10 bushes around the area. Space trees 4m apart and bushes 2m apart.", "scatter"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 10, "min_scatter_items": 15, "scatter_in_bounds": True}, raw)


@register
class GardenG2FlowerBed(Test):
    id = "garden.G2_flower_bed"
    category = "capability"
    title = "Scatter: flower bed"
    description = "20 flowers at 1m spacing in a 10×10m garden."
    suites = ["everything", "garden-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Plant a flower bed with 20 flowers spaced 1m apart in a 10x10 metre garden.", "scatter"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 15, "min_scatter_items": 15, "scatter_in_bounds": True}, raw)


@register
class GardenG3Mixed(Test):
    id = "garden.G3_mixed_garden"
    category = "capability"
    title = "Scatter: mixed garden"
    description = "Trees + bushes + flowers + rocks in a 20×20m region."
    suites = ["everything", "garden-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Create a garden with 3 trees (4m spacing), 8 bushes (2m spacing), 12 flowers (1.5m spacing), and 5 rocks (2m spacing). Keep the area 20x20 metres.",
            "scatter",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 20, "min_scatter_items": 25, "scatter_in_bounds": True}, raw)
