"""SSP gauntlet tests — migrated from gauntlet.py ssp-v1 set.

Semantic room generation via SSP engine: archetype selection with
sensible defaults. LLM picks a room type; engine fills in furniture.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class Ssp1Kitchen(Test):
    id = "ssp.SSP1_kitchen"
    category = "capability"
    title = "SSP: kitchen"
    description = "Kitchen with stove, fridge, and table via SSP archetype."
    suites = ["everything", "ssp-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a kitchen with a stove, a fridge, and a table", "ssp")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 5, "min_spatial_assets": 3, "no_overlap": True}, raw)


@register
class Ssp2Living(Test):
    id = "ssp.SSP2_living"
    category = "capability"
    title = "SSP: living room"
    description = "Living room with table and chairs via SSP archetype."
    suites = ["everything", "ssp-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a living room with a table and chairs", "ssp")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 5, "min_spatial_assets": 3, "no_overlap": True}, raw)


@register
class Ssp3Bedroom(Test):
    id = "ssp.SSP3_bedroom"
    category = "capability"
    title = "SSP: bedroom"
    description = "Small bedroom with table and cabinet via SSP archetype."
    suites = ["everything", "ssp-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a small bedroom with a table and a cabinet", "ssp")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 4, "min_spatial_assets": 2, "no_overlap": True}, raw)


@register
class Ssp4Dining(Test):
    id = "ssp.SSP4_dining"
    category = "capability"
    title = "SSP: dining room"
    description = "Dining room with table and four chairs via SSP archetype."
    suites = ["everything", "ssp-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(ctx, "Build a dining room with a table and four chairs", "ssp")

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 6, "min_spatial_assets": 5, "no_overlap": True}, raw)
