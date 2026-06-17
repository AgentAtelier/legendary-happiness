"""Capability gauntlet tests — migrated from gauntlet.py capability-v1 set.

Escalating prompts pushing one capability axis at a time:
depth, breadth, prop saturation, children/colliders, scripts/signals,
mixed 2D/3D/UI, integration ceiling, and adversarial graceful-failure.
"""

from __future__ import annotations

from ..catalog import register
from ..context import Context
from ..result import ScoredResult
from ..test import Test
from ._gauntlet_measure import gauntlet_run, gauntlet_score


@register
class CapG1Depth(Test):
    id = "cap.G1_depth"
    category = "capability"
    title = "Nesting depth"
    description = "8-level nested Node3D chain under /Main."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Under /Main create a chain of nested Node3D nodes: LvlA as a child of /Main, LvlB under LvlA, LvlC under LvlB, LvlD under LvlC, LvlE under LvlD, LvlF under LvlE, LvlG under LvlF, and LvlH under LvlG.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 8, "min_depth": 8}, raw)


@register
class CapG3Props(Test):
    id = "cap.G3_props"
    category = "capability"
    title = "Prop saturation"
    description = "5 MeshInstance3D nodes, each with distinct mesh + color + position."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Under /Main create five MeshInstance3D nodes: BoxNode (box mesh, red, position -4 0 0), SphereNode (sphere mesh, green, position -2 0 0), CapsuleNode (capsule mesh, blue, position 0 0 0), CylinderNode (cylinder mesh, yellow, position 2 0 0), and PlaneNode (plane mesh, white, position 4 0 0).",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 5, "props": {"mesh": 5, "color": 5, "position": 5}}, raw)


@register
class CapG4Children(Test):
    id = "cap.G4_children"
    category = "capability"
    title = "Collider/mesh children"
    description = "Area3D nodes each with CollisionShape3D + MeshInstance3D children."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Under /Main create a Node3D named Pickups. Under it create three Area3D nodes named P1, P2, P3. Each Area3D must have a CollisionShape3D child with a sphere shape AND a MeshInstance3D child with a sphere mesh, each colored differently.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id, {"min_nodes": 10, "min_depth": 3, "props": {"shape": 3, "mesh": 3, "color": 3}}, raw
        )


@register
class CapG5ScriptsSignals(Test):
    id = "cap.G5_scripts_signals"
    category = "capability"
    title = "Scripts + signal wiring"
    description = "CharacterBody3D with WASD movement script + Timer signal connection."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Under /Main create a CharacterBody3D named Hero with a movement system that reads WASD input and moves it. Also create a Timer named SpawnTimer, and a spawner system; connect the SpawnTimer timeout signal to the spawner.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 2, "min_scripts": 1, "min_attached": 1, "min_signals": 1}, raw)


@register
class CapG6Mixed(Test):
    id = "cap.G6_mixed"
    category = "capability"
    title = "Mixed 3D + 2D/UI"
    description = "CharacterBody3D + CanvasLayer with Buttons and Label."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Under /Main create a CharacterBody3D named Player. Also create a CanvasLayer named HUD; under HUD a VBoxContainer named Menu; under Menu three Button nodes named StartBtn, OptionsBtn, QuitBtn, and a Label named Title with text 'Main Menu'.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {
                "min_nodes": 7,
                "min_depth": 3,
                "types": ["CanvasLayer", "VBoxContainer", "Button", "Label", "CharacterBody3D"],
                "props": {"text": 1},
            },
            raw,
        )


@register
class CapG7Integration(Test):
    id = "cap.G7_integration"
    category = "capability"
    title = "Integration ceiling"
    description = "Full collectible arena: player + camera + coins with colliders + UI."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Build a collectible arena under /Main. Create a Node3D Arena. Under Arena: a CharacterBody3D Player at 0 1 0 with a WASD movement script and a Camera3D child PlayerCam at 0 3 6; a Node3D Coins containing six Area3D coins (Coin1..Coin6), each with a CollisionShape3D sphere-shape child and a MeshInstance3D sphere-mesh child colored distinctly, each coin with a collect script that frees itself and adds score; and a CanvasLayer UI containing a Label ScoreLabel with text 'Score: 0'.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(
            self.id,
            {
                "min_nodes": 25,
                "min_depth": 4,
                "props": {"shape": 6, "mesh": 6, "color": 6, "text": 1},
                "min_scripts": 2,
                "min_attached": 2,
            },
            raw,
        )


@register
class CapG8Adversarial(Test):
    id = "cap.G8_adversarial"
    category = "capability"
    title = "Adversarial / graceful failure"
    description = "Rejects bad ops (camera mesh, phantom parent) while building 20 valid nodes."
    suites = ["everything", "capability-v1"]
    needs_reset = True
    expect_break = True
    repeatable = True

    async def run(self, ctx: Context) -> dict:
        return await gauntlet_run(
            ctx,
            "Create a Camera3D named BadCam and give it a box mesh. Create a Node3D named Orphan as a child of a node named Ghost. Then create twenty Node3D nodes named Filler1 through Filler20 under /Main.",
            "",
        )

    def score(self, raw: dict) -> ScoredResult:
        return gauntlet_score(self.id, {"min_nodes": 20, "expect_errors": True}, raw)
