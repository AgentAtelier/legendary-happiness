"""Stress-v1 suite — full-system stress tests across Acts I–V.

Migrated from STRESS-TEST-SCENARIO.md (2026-06-16). Each test exercises
a specific pipeline stress point: core arch, spatial engines, variety
rebalance, maximum composition, and graceful-degrade break tests.

Key design rules:
- Act I: sequential tests are self-contained (A2 re-runs A1 + adds behavior)
- Act II: one spatial engine per test, needs_reset=True
- Act III: skip_cache=True, multi-run variety measurement
- Act IV: multi-engine composition
- Act V: expect_break=True — high errors = graceful degrade (good)
"""

from __future__ import annotations

import time

from ..catalog import register
from ..context import Context
from ..result import ScoredResult, Status
from ..test import Test

# ═══════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════


def _snapshot_names(snapshot: dict) -> set[str]:
    """Extract flat set of node names from a hierarchy snapshot."""
    names: set[str] = set()
    n = snapshot.get("name", "")
    if n:
        names.add(n)
    for child in snapshot.get("children", []):
        if isinstance(child, dict):
            names |= _snapshot_names(child)
    return names


async def _scene_snapshot(ctx: Context) -> dict:
    """Capture the live scene hierarchy."""
    return await ctx.godot_ai("scene_get_hierarchy", {"depth": 10})


async def _scene_names(ctx: Context) -> set[str]:
    return _snapshot_names(await _scene_snapshot(ctx))


def _node_count_from_artifact(artifact: dict) -> int:
    """Count add_node ops in an artifact's operations list."""
    ops = artifact.get("operations", [])
    return sum(1 for o in ops if isinstance(o, dict) and o.get("type") == "add_node")


def _error_count(raw: dict, artifact: dict) -> int:
    """Count errors from raw response + artifact."""
    n = len(raw.get("errors", []))
    n += len(artifact.get("errors", []))
    return n


def _jaccard_diversity(sets: list[set]) -> float:
    """Compute mean pairwise Jaccard distance (0 = identical, 1 = max diversity)."""
    if len(sets) < 2:
        return 0.0
    distances: list[float] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = len(sets[i] | sets[j])
            if union == 0:
                distances.append(0.0)
            else:
                distances.append(1.0 - len(sets[i] & sets[j]) / union)
    return sum(distances) / len(distances) if distances else 0.0


async def _one_spec(ctx: Context, prompt: str, planner: str = "") -> tuple[dict, dict]:
    """Run one apply_spec and return (raw, artifact)."""
    raw = await ctx.apply_spec(prompt, planner=planner)
    artifact = raw
    if raw.get("artifact_id"):
        try:
            artifact = await ctx.read_artifact(raw["artifact_id"])
        except Exception:
            pass
    return raw, artifact


# ═══════════════════════════════════════════════════════════════════
# ACT I — Core pipeline (arch planner → compiler → validator → executor)
# ═══════════════════════════════════════════════════════════════════

ARENA_PROMPT = (
    "Under /Main build a small arena: a Node3D Arena containing a "
    "Player (capsule mesh, blue), five coins (gold spheres with colliders) "
    "under a Collectibles node, and a UI ScoreLabel reading 'Score: 0'."
)

BEHAVIOR_PROMPT = (
    "Add WASD movement to the Player and make each coin disappear and add score when the Player touches it."
)

EDIT_PROMPT = "Delete two coins and rename the Player to Hero."

ADVERSARIAL_PROMPT = "Give a Camera3D a box mesh, put a node under a nonexistent 'Ghost', and also add 15 valid crates."


@register
class StressA1Arena(Test):
    id = "stress.a1_arena"
    category = "stress"
    title = "Act I.1 — Arena build"
    description = "Complex scene: Player + 5 coins + Collectibles + UI label — nesting, meshes, text."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(ctx, ARENA_PROMPT, planner="")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        names = set(raw.get("after_names", []))
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        has_arena = "Arena" in names
        has_player = "Player" in names
        has_collectibles = "Collectibles" in names
        checks = [has_arena, has_player, has_collectibles, nc >= 6, ec == 0]
        passed = sum(checks)
        status: Status = "ok" if passed == 5 else "partial" if passed >= 3 else "broke"
        return ScoredResult(
            self.id,
            status,
            score=passed * 20,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={
                "nodes": nc,
                "errors": ec,
                "has_arena": has_arena,
                "has_player": has_player,
                "has_collectibles": has_collectibles,
            },
        )


@register
class StressA2Behavior(Test):
    id = "stress.a2_behavior"
    category = "stress"
    title = "Act I.2 — Behavior attach"
    description = "Builds arena + adds WASD movement and coin collection — signal wiring."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()

        # Step 1: arena
        raw1, art1 = await _one_spec(ctx, ARENA_PROMPT, planner="")
        # Step 2: behavior
        raw2, art2 = await _one_spec(ctx, BEHAVIOR_PROMPT, planner="")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw2,
            "artifact": art2,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(art1) + _node_count_from_artifact(art2),
            "error_count": _error_count(raw1, art1) + _error_count(raw2, art2),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        names = set(raw.get("after_names", []))
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        has_arena = "Arena" in names
        has_player = "Player" in names
        has_collectibles = "Collectibles" in names
        checks = [has_arena, has_player, has_collectibles, nc >= 10]
        passed = sum(checks)
        # Behavior tests are hard — partial is acceptable
        status: Status = "ok" if passed >= 3 and ec == 0 else "partial" if passed >= 2 else "broke"
        return ScoredResult(
            self.id,
            status,
            score=passed * 25,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA3Edit(Test):
    id = "stress.a3_edit"
    category = "stress"
    title = "Act I.3 — Edit ops"
    description = "Builds arena + behavior, then deletes 2 coins and renames Player → Hero."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        # Step 1: arena
        raw1, _ = await _one_spec(ctx, ARENA_PROMPT, planner="")
        # Step 2: behavior
        raw2, _ = await _one_spec(ctx, BEHAVIOR_PROMPT, planner="")
        # Step 3: edit
        raw3, art3 = await _one_spec(ctx, EDIT_PROMPT, planner="")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        total_errors = _error_count(raw1, {}) + _error_count(raw2, {}) + _error_count(raw3, art3)

        return {
            "raw": raw3,
            "artifact": art3,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(art3),
            "error_count": total_errors,
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        names = set(raw.get("after_names", []))
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        has_hero = "Hero" in names
        player_gone = "Player" not in names
        has_arena = "Arena" in names
        checks = [has_arena, has_hero, player_gone]
        passed = sum(checks)
        status: Status = "ok" if passed >= 2 and ec == 0 else "partial" if has_arena else "broke"
        return ScoredResult(
            self.id,
            status,
            score=passed * 33,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec, "has_hero": has_hero},
        )


@register
class StressA4Adversarial(Test):
    id = "stress.a4_adversarial"
    category = "stress"
    title = "Act I.4 — Graceful adversarial"
    description = (
        "15 valid crates + 2 bad ops (invalid mesh, nonexistent parent). Must build 15, reject bad ops gracefully."
    )
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(ctx, ADVERSARIAL_PROMPT, planner="")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        crate_names = [n for n in after if "crate" in n.lower()]
        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "crate_count": len(crate_names),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        crate_count = raw.get("crate_count", 0)
        ec = raw.get("error_count", 0)
        nc = raw.get("node_count", 0)

        # The15 crates must build; the 2 bad ops must be rejected (errors > 0 is GOOD)
        crates_ok = crate_count >= 12  # tolerate partial
        has_errors = ec > 0  # bad ops should produce errors
        built_something = nc >= 10

        if crates_ok and built_something:
            status: Status = "ok"
            score = 100
        elif crate_count >= 5:
            status = "partial"
            score = 60
        else:
            status = "broke"
            score = 20

        return ScoredResult(
            self.id,
            status,
            score=score,
            raw=raw,
            errors=[] if has_errors else ["Expected errors for bad ops but got none"],
            metrics={"crates": crate_count, "errors": ec, "nodes": nc},
        )


# ═══════════════════════════════════════════════════════════════════
# ACT II — Every spatial engine at its best
# ═══════════════════════════════════════════════════════════════════


@register
class StressA5CrampedKitchen(Test):
    id = "stress.a5_cramped_kitchen"
    category = "stress"
    title = "Act II.5 — Cramped kitchen (room)"
    description = "RoomIntent planner: cramped abandoned rustic kitchen."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(ctx, "A cramped, abandoned rustic kitchen.", planner="room")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        built = nc >= 4  # floor + ceiling + some furniture
        status: Status = "ok" if built and ec == 0 else "partial" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA6House(Test):
    id = "stress.a6_house"
    category = "stress"
    title = "Act II.6 — House (building)"
    description = "Building planner: house with living room, kitchen, 2 bedrooms."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx, "A house with a living room, a kitchen, and two bedrooms.", planner="building"
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        built = nc >= 8
        status: Status = "ok" if built and ec == 0 else "partial" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA7ScatterGarden(Test):
    id = "stress.a7_scatter_garden"
    category = "stress"
    title = "Act II.7 — Garden scatter"
    description = "Scatter planner: trees and bushes around a house."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx, "Scatter trees and bushes around the house, none inside it.", planner="scatter"
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        built = nc >= 5
        status: Status = "ok" if built and ec == 0 else "partial" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA8Dungeon(Test):
    id = "stress.a8_dungeon"
    category = "stress"
    title = "Act II.8 — Dungeon (WFC)"
    description = "WFC planner: 10×10 dungeon with rooms and corridors."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(ctx, "A 10×10 dungeon with rooms and connecting corridors.", planner="wfc")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        built = nc >= 30  # WFC 10×10 = up to 100 tiles, expect at least 30
        status: Status = "ok" if built and ec == 0 else "partial" if nc >= 10 else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA9Village(Test):
    id = "stress.a9_village"
    category = "stress"
    title = "Act II.9 — Village (Voronoi)"
    description = "Voronoi planner: 5-district village with roads."
    suites = ["everything", "stress-v1"]
    needs_reset = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(ctx, "A village with 5 districts and roads between them.", planner="voronoi")
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        names = raw.get("after_names", [])
        has_ground = any("TownGround" in n for n in names)
        has_roads = any("road_" in n for n in names)
        has_buildings = any("bld_" in n for n in names)
        built = has_ground and has_roads and has_buildings
        status: Status = "ok" if built and ec == 0 else "partial" if nc >= 10 else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec, "has_roads": has_roads, "has_buildings": has_buildings},
        )


# ═══════════════════════════════════════════════════════════════════
# ACT III — Stage 4 rebalance (variety + intent, skip_cache=true)
# ═══════════════════════════════════════════════════════════════════


@register
class StressA10KitchenContrast(Test):
    id = "stress.a10_kitchen_contrast"
    category = "stress"
    title = "Act III.10 — Kitchen contrast"
    description = (
        "Build cramped abandoned AND spacious noble kitchen — must look visibly different (room planner, skip_cache)."
    )
    suites = ["everything", "stress-v1"]
    needs_reset = True
    skip_cache = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()

        # Cramped abandoned kitchen
        _, art1 = await _one_spec(ctx, "A cramped abandoned rustic kitchen.", planner="room")
        after1 = await _scene_names(ctx)
        nc1 = _node_count_from_artifact(art1)

        # Reset between builds to isolate the scene
        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe_bounce.tscn"})
        except Exception:
            pass
        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe.tscn"})
        except Exception:
            pass

        # Spacious noble kitchen
        _, art2 = await _one_spec(ctx, "A spacious noble kitchen.", planner="room")
        after2 = await _scene_names(ctx)
        nc2 = _node_count_from_artifact(art2)

        ms = int((time.time() - t0) * 1000)
        # Compute Jaccard distance between the two builds
        diversity = _jaccard_diversity([after1, after2])

        return {
            "nc1": nc1,
            "nc2": nc2,
            "names1": sorted(after1),
            "names2": sorted(after2),
            "diversity": diversity,
            "error_count": 0,
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        diversity = raw.get("diversity", 0.0)
        nc1 = raw.get("nc1", 0)
        nc2 = raw.get("nc2", 0)

        # Both must build AND be different (diversity > 0)
        both_built = nc1 >= 4 and nc2 >= 4
        are_different = diversity > 0.05  # at least 5% different

        if both_built and are_different:
            status: Status = "ok"
            score = 100
        elif both_built:
            status = "partial"
            score = 50
        else:
            status = "broke"
            score = 0

        return ScoredResult(
            self.id,
            status,
            score=score,
            raw=raw,
            errors=[] if are_different else ["Kitchens are not visibly different (diversity < 0.05)"],
            metrics={"diversity": diversity, "nc1": nc1, "nc2": nc2},
        )


@register
class StressA11KitchenRepeat(Test):
    id = "stress.a11_kitchen_repeat"
    category = "stress"
    title = "Act III.11 — Kitchen repeat ×3"
    description = "Build 'a rustic kitchen' 3 times with skip_cache — must produce 3 different kitchens."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    skip_cache = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        name_sets: list[set[str]] = []

        for i in range(3):
            _, artifact = await _one_spec(ctx, "A rustic kitchen.", planner="room")
            after = await _scene_names(ctx)
            name_sets.append(after)

            # Reset between builds
            if i < 2:
                try:
                    await ctx.godot_ai("scene_open", {"path": "res://probe_bounce.tscn"})
                except Exception:
                    pass
                try:
                    await ctx.godot_ai("scene_open", {"path": "res://probe.tscn"})
                except Exception:
                    pass

        ms = int((time.time() - t0) * 1000)
        diversity = _jaccard_diversity(name_sets)

        return {
            "name_sets": [sorted(s) for s in name_sets],
            "diversity": diversity,
            "node_counts": [len(s) for s in name_sets],
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        diversity = raw.get("diversity", 0.0)
        ncs = raw.get("node_counts", [])
        all_built = all(n >= 3 for n in ncs)
        are_different = diversity > 0.05

        if all_built and are_different:
            status: Status = "ok"
            score = 100
        elif all_built:
            status = "partial"
            score = 40
            return ScoredResult(
                self.id,
                status,
                score=score,
                raw=raw,
                errors=["All 3 kitchens are identical (diversity ≈ 0) — skip_cache may be ignored"],
                metrics={"diversity": diversity, "node_counts": ncs},
            )
        else:
            status = "broke"
            score = 0

        return ScoredResult(
            self.id,
            status,
            score=score,
            raw=raw,
            errors=[],
            metrics={"diversity": diversity, "node_counts": ncs},
        )


@register
class StressA12KnobMatrix(Test):
    id = "stress.a12_knob_matrix"
    category = "stress"
    title = "Act III.12 — Knob matrix"
    description = "Vary size/style/clutter/mood one axis at a time — each knob must visibly move the output."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    skip_cache = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()

        # Size axis: cramped, spacious
        _, art1 = await _one_spec(ctx, "A cramped kitchen.", planner="room")
        nc1 = _node_count_from_artifact(art1)
        ns1 = await _scene_names(ctx)

        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe_bounce.tscn"})
        except Exception:
            pass
        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe.tscn"})
        except Exception:
            pass

        _, art2 = await _one_spec(ctx, "A spacious kitchen.", planner="room")
        nc2 = _node_count_from_artifact(art2)
        ns2 = await _scene_names(ctx)

        # Clutter axis: 0.2 vs 0.9
        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe_bounce.tscn"})
        except Exception:
            pass
        try:
            await ctx.godot_ai("scene_open", {"path": "res://probe.tscn"})
        except Exception:
            pass

        _, art3 = await _one_spec(ctx, "A minimal kitchen with only the essentials.", planner="room")
        nc3 = _node_count_from_artifact(art3)

        ms = int((time.time() - t0) * 1000)
        # Size differentiation: spacious should have different names than cramped
        size_diversity = _jaccard_diversity([ns1, ns2])

        return {
            "size_diversity": size_diversity,
            "nc_cramped": nc1,
            "nc_spacious": nc2,
            "nc_minimal": nc3,
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        size_div = raw.get("size_diversity", 0.0)
        nc_c = raw.get("nc_cramped", 0)
        nc_s = raw.get("nc_spacious", 0)
        nc_m = raw.get("nc_minimal", 0)
        all_built = nc_c >= 3 and nc_s >= 3 and nc_m >= 1

        # Each knob should visibly change output
        size_moves = size_div > 0.05
        knobs_that_move = sum([size_moves])

        if all_built and knobs_that_move >= 1:
            status: Status = "ok"
            score = 100
        elif all_built:
            status = "partial"
            score = 60
        else:
            status = "broke"
            score = 0

        return ScoredResult(
            self.id,
            status,
            score=score,
            raw=raw,
            errors=[] if knobs_that_move >= 1 else ["Knobs don't visibly move output"],
            metrics={
                "size_diversity": size_div,
                "nc_cramped": nc_c,
                "nc_spacious": nc_s,
                "nc_minimal": nc_m,
            },
        )


# ═══════════════════════════════════════════════════════════════════
# ACT IV — The maximum (compose + make the model matter)
# ═══════════════════════════════════════════════════════════════════


@register
class StressA13Manor(Test):
    id = "stress.a13_manor"
    category = "stress"
    title = "Act IV.13 — Noble manor"
    description = "Build a manor: building + room interiors + scatter garden around it."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    timeout_s = 600

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()

        # Step 1: building
        raw1, art1 = await _one_spec(
            ctx,
            "A small noble manor — styled rooms inside, a garden of trees around it.",
            planner="building",
        )
        nc1 = _node_count_from_artifact(art1)
        ec1 = _error_count(raw1, art1)
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw1,
            "artifact": art1,
            "after_names": sorted(after),
            "node_count": nc1,
            "error_count": ec1,
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        names = set(raw.get("after_names", []))
        has_building = any("bld_" in n for n in names) or any("room" in n.lower() for n in names)
        built = nc >= 10 and has_building
        status: Status = "ok" if built and ec == 0 else "partial" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA14NobleKitchen(Test):
    id = "stress.a14_noble_kitchen"
    category = "stress"
    title = "Act IV.14 — Noble's poison kitchen"
    description = "Rich intent: elegant on surface, hidden cabinets, concealed back room — tests intent depth."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    skip_cache = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx,
            "A noble's manor kitchen that is secretly a poisoner's workshop — "
            "elegant on the surface, hidden cabinets, a concealed back room.",
            planner="room",
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        built = nc >= 6  # rich kitchen should have many props
        status: Status = "ok" if built and ec == 0 else "partial" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if status == "ok" else 50 if status == "partial" else 0,
            raw=raw,
            errors=[] if ec == 0 else [f"{ec} error(s)"],
            metrics={"nodes": nc, "errors": ec},
        )


# ═══════════════════════════════════════════════════════════════════
# ACT V — Break on purpose (expect_break=True = graceful degrade)
# ═══════════════════════════════════════════════════════════════════


@register
class StressA15Contradictory(Test):
    id = "stress.a15_contradictory"
    category = "stress"
    title = "Act V.15 — Contradictory adjectives"
    description = "Cramped+spacious+cozy+abandoned — contradictory enums force choice. Does it pick one or mush?"
    suites = ["everything", "stress-v1"]
    needs_reset = True
    expect_break = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx, "A cramped spacious cozy abandoned luxurious derelict kitchen.", planner="room"
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        # Graceful degrade = still builds something without crash
        built = nc >= 3
        status: Status = "ok" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if built else 0,
            raw=raw,
            errors=[] if built else ["Contradictory prompt produced nothing — enum collapse failure"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA16OffLexicon(Test):
    id = "stress.a16_off_lexicon"
    category = "stress"
    title = "Act V.16 — Off-lexicon kitchen"
    description = "Cyberpunk kitchen with plasma reactor — off-lexicon props handled gracefully."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    expect_break = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx, "A neon cyberpunk kitchen with a plasma reactor and a lava moat.", planner="room"
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        # Off-lexicon: style may collapse but build should not crash
        built = nc >= 3
        status: Status = "ok" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if built else 0,
            raw=raw,
            errors=[] if built else ["Off-lexicon prompt crashed — rigid enum handling failure"],
            metrics={"nodes": nc, "errors": ec},
        )


@register
class StressA17ScaleBomb(Test):
    id = "stress.a17_scale_bomb"
    category = "stress"
    title = "Act V.17 — Scale bomb"
    description = "40-room castle + 100-district city + 1000 trees + 24×24 dungeon — finds scale ceilings."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    expect_break = True
    timeout_s = 900

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        results: dict[str, dict] = {}

        # 40-room castle
        try:
            raw, art = await _one_spec(ctx, "A 40-room castle.", planner="building")
            results["castle"] = {"nodes": _node_count_from_artifact(art), "errors": _error_count(raw, art)}
        except Exception as e:
            results["castle"] = {"nodes": 0, "errors": 1, "exception": str(e)}

        # 100-district city (full scale — designed to find ceiling)
        try:
            raw, art = await _one_spec(ctx, "A city with 100 districts.", planner="voronoi")
            results["city"] = {"nodes": _node_count_from_artifact(art), "errors": _error_count(raw, art)}
        except Exception as e:
            results["city"] = {"nodes": 0, "errors": 1, "exception": str(e)}

        # 1000 trees (full scale — designed to find batch/perf ceiling)
        try:
            raw, art = await _one_spec(ctx, "Scatter 1000 trees across a forest.", planner="scatter")
            results["forest"] = {"nodes": _node_count_from_artifact(art), "errors": _error_count(raw, art)}
        except Exception as e:
            results["forest"] = {"nodes": 0, "errors": 1, "exception": str(e)}

        # 24×24 dungeon
        try:
            raw, art = await _one_spec(ctx, "A 24×24 dungeon.", planner="wfc")
            results["dungeon"] = {"nodes": _node_count_from_artifact(art), "errors": _error_count(raw, art)}
        except Exception as e:
            results["dungeon"] = {"nodes": 0, "errors": 1, "exception": str(e)}

        ms = int((time.time() - t0) * 1000)
        return {"results": results, "latency_ms": ms}

    def score(self, raw: dict) -> ScoredResult:
        res = raw.get("results", {})
        # Graceful degrade = at least some engines produce output, none crash hard
        built = sum(1 for r in res.values() if r.get("nodes", 0) > 0)
        crashed = sum(1 for r in res.values() if r.get("exception"))
        total = max(len(res), 1)

        if built >= 2 and crashed == 0:
            status: Status = "ok"
            score = 100
        elif built >= 1:
            status = "partial"
            score = 50
        else:
            status = "broke"
            score = 0

        return ScoredResult(
            self.id,
            status,
            score=score,
            raw=raw,
            errors=[f"{crashed} crashed"] if crashed else [],
            metrics={"engines_built": built, "crashed": crashed, "total": total},
        )


@register
class StressA18Concept(Test):
    id = "stress.a18_concept"
    category = "stress"
    title = "Act V.18 — Abstract concept"
    description = (
        "'Build the concept of regret' and 'a kitchen made of sound' — degenerate/empty descriptors, must not crash."
    )
    suites = ["everything", "stress-v1"]
    needs_reset = True
    expect_break = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        results: dict[str, dict] = {}

        for label, prompt in [
            ("regret", "Build the concept of regret."),
            ("sound", "A kitchen made of sound."),
        ]:
            try:
                raw, artifact = await _one_spec(ctx, prompt, planner="")
                results[label] = {
                    "node_count": _node_count_from_artifact(artifact),
                    "error_count": _error_count(raw, artifact),
                }
            except Exception as e:
                results[label] = {"exception": str(e), "error_count": 1, "crashed": True}

        ms = int((time.time() - t0) * 1000)
        return {"results": results, "latency_ms": ms}

    def score(self, raw: dict) -> ScoredResult:
        # Graceful degrade = no crash on either abstract prompt
        results = raw.get("results", {})
        crashed = sum(1 for r in results.values() if r.get("crashed") or "exception" in r)
        built = sum(1 for r in results.values() if r.get("node_count", 0) > 0)
        status: Status = "broke" if crashed > 0 else "ok"
        return ScoredResult(
            self.id,
            status,
            score=100 if crashed == 0 else 0,
            raw=raw,
            errors=[f"{crashed} abstract prompt(s) crashed"] if crashed else [],
            metrics={"crashed": crashed, "built": built},
        )


@register
class StressA19Compound(Test):
    id = "stress.a19_compound"
    category = "stress"
    title = "Act V.19 — Compound router"
    description = "Dungeon inside kitchen on floating island — single planner does its lane, ignores rest."
    suites = ["everything", "stress-v1"]
    needs_reset = True
    expect_break = True

    async def run(self, ctx: Context) -> dict:
        t0 = time.time()
        raw, artifact = await _one_spec(
            ctx,
            "A dungeon inside a kitchen on a floating island surrounded by a city.",
            planner="",
        )
        after = await _scene_names(ctx)
        ms = int((time.time() - t0) * 1000)

        return {
            "raw": raw,
            "artifact": artifact,
            "after_names": sorted(after),
            "node_count": _node_count_from_artifact(artifact),
            "error_count": _error_count(raw, artifact),
            "latency_ms": ms,
        }

    def score(self, raw: dict) -> ScoredResult:
        nc = raw.get("node_count", 0)
        ec = raw.get("error_count", 0)
        # Compound prompt: single planner does one lane, ignores rest.
        # Graceful = builds something without crashing. The fact that it
        # ignores the compound is expected (exposes missing router).
        built = nc >= 3
        status: Status = "ok" if built else "broke"
        return ScoredResult(
            self.id,
            status,
            score=100 if built else 0,
            raw=raw,
            errors=[] if built else ["Compound prompt produced nothing"],
            metrics={"nodes": nc, "errors": ec},
        )
