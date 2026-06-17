"""BSP building gauntlet tests — migrated from gauntlet.py building-v1 set.

Multi-room building generation via BSP split trees → room rects →
per-room furniture via SpatialCompiler + partition walls with doorways.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class BuildingB1SmallHouse(Test):
    id = "building.B1_small_house"
    category = "capability"
    title = "Building: small house"
    description = "3-room house: living room, kitchen, bedroom with furniture."
    suites = ["everything", "building-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build a small house with a living room, a kitchen, and a bedroom. Put a table in the living room, a stove and fridge in the kitchen, and a table in the bedroom.",
            "building",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {
                "min_nodes": 4,
                "min_rooms": 3,
                "min_spatial_assets": 3,
                "building_no_overlap": True,
                "building_in_bounds": True,
                "min_walls": 1,
            },
            raw,
        )


@register
class BuildingB2Studio(Test):
    id = "building.B2_studio"
    category = "capability"
    title = "Building: studio apartment"
    description = "Single-room studio with bed and table."
    suites = ["everything", "building-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx, "Build a tiny studio apartment — just one room. Put a bed and a small table in it.", "building"
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {
                "min_nodes": 3,
                "min_rooms": 1,
                "min_spatial_assets": 1,
                "building_no_overlap": True,
                "building_in_bounds": True,
            },
            raw,
        )


@register
class BuildingB3TwoBedroom(Test):
    id = "building.B3_two_bedroom"
    category = "capability"
    title = "Building: two-bedroom house"
    description = "4-room house: living room, kitchen, two bedrooms."
    suites = ["everything", "building-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build a house with a living room, a kitchen, and two bedrooms. Put a table in the living room, a stove and a counter in the kitchen, a bed in each bedroom.",
            "building",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {
                "min_nodes": 5,
                "min_rooms": 4,
                "min_spatial_assets": 4,
                "building_no_overlap": True,
                "building_in_bounds": True,
                "min_walls": 1,
            },
            raw,
        )
