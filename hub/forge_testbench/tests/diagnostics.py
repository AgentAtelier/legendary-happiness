"""Diagnostics tests — migrated from diagnostics.py into plug-in tests.

Three key measurements that unblock Guide 2 (world-state richness experiment):
  variety.repeat_diversity  — "build a kitchen" ×10, skip_cache, Jaccard diversity
  variety.intent_sensitivity — 4 adjective variants, pairwise differentiation
  variety.ceiling           — hard relational prompt, node count / error metrics

THE RULE: typed metrics fix the old reporting bugs by construction.
  diversity → ratio (0–1), NO ×100
  intent_coverage → ratio (0–1), NO null
  The runner owns completion; no mid-run reads possible.
"""

from __future__ import annotations

import time
from typing import Any

from ..catalog import register
from ..context import Context
from ..metric import Metric
from ..result import ScoredResult, Status
from ..test import Test

# ── Prompts ──────────────────────────────────────────────────────

REPEAT_PROMPT = "build a kitchen"

INTENT_PROMPTS: list[tuple[str, str]] = [
    ("cramped", "build a cramped kitchen"),
    ("spacious", "build a spacious kitchen"),
    ("abandoned", "build an abandoned kitchen"),
    ("luxurious", "build a luxurious kitchen"),
]

CEILING_PROMPT = (
    "a wizard's tower where the wizard grew afraid of heights — "
    "upper floors sealed and dusty, living area migrated down to the ground floor"
)

# ── Diversity computation (pure, copied from gauntlet.py) ────────


def _compute_diversity(run_data: list[dict]) -> dict[str, Any]:
    """Compute Jaccard distance + asset similarity across multiple runs.

    Returns: {jaccard_distance, asset_similarity, distinct_outputs, total_runs}
    """
    if len(run_data) < 2:
        return {"jaccard_distance": 0.0, "asset_similarity": 1.0, "distinct_outputs": 1, "total_runs": len(run_data)}

    node_sets: list[set] = []
    asset_multisets: list[dict] = []

    for run in run_data:
        names = set()
        asset_counts: dict[str, int] = {}
        ops = run.get("_ops", [])
        for o in ops if ops else []:
            if isinstance(o, dict) and o.get("type") == "add_node":
                name = str(o.get("name", ""))
                if name:
                    names.add(name)
                    parts = name.split("_")
                    if parts:
                        asset_counts[parts[0]] = asset_counts.get(parts[0], 0) + 1
        if not names:
            names = set(run.get("node_names", []))
        node_sets.append(names)
        asset_multisets.append(asset_counts)

    # Jaccard distance: 1 − |intersection|/|union|
    all_union = set()
    all_intersection = node_sets[0].copy() if node_sets else set()
    for ns in node_sets:
        all_union |= ns
        all_intersection &= ns
    jaccard = 1.0 - (len(all_intersection) / max(len(all_union), 1))

    # Asset multiset similarity
    asset_sims: list[float] = []
    for i in range(len(asset_multisets)):
        for j in range(i + 1, len(asset_multisets)):
            keys = set(asset_multisets[i].keys()) | set(asset_multisets[j].keys())
            if not keys:
                asset_sims.append(1.0)
                continue
            matches = sum(min(asset_multisets[i].get(k, 0), asset_multisets[j].get(k, 0)) for k in keys)
            totals = sum(max(asset_multisets[i].get(k, 0), asset_multisets[j].get(k, 0)) for k in keys)
            asset_sims.append(matches / max(totals, 1))
    asset_similarity = sum(asset_sims) / max(len(asset_sims), 1) if asset_sims else 1.0

    # Distinct outputs by hashing node sets
    node_hashes = {hash(frozenset(ns)) for ns in node_sets}

    return {
        "jaccard_distance": round(jaccard, 3),
        "asset_similarity": round(asset_similarity, 3),
        "distinct_outputs": len(node_hashes),
        "total_runs": len(run_data),
    }


# ── Shared runner helpers ────────────────────────────────────────


async def _between_run_reset(ctx: Context) -> None:
    """Bounce-trick scene reload between iterations.

    The runner does a full _scene_reset before the test, writing fresh
    probe scene files to disk.  Between iterations inside a test's run(),
    we just need to discard the in-memory dirty scene and reload from
    disk — the bounce trick (open a different scene first, then the probe)
    forces Godot to actually reload from disk instead of reusing the
    stale in-memory tab.
    """
    try:
        await ctx.godot_ai("scene_open", {"path": "res://probe_bounce.tscn"})
    except Exception:
        pass
    try:
        await ctx.godot_ai("scene_open", {"path": "res://probe.tscn"})
    except Exception:
        pass


async def _one_apply(ctx: Context, prompt: str, planner: str = "room") -> dict[str, Any]:
    """Single apply_spec call → {node_names, node_count, _ops, latency_ms}."""
    t0 = time.time()
    raw = await ctx.apply_spec(prompt, planner=planner)
    artifact = raw
    if raw.get("artifact_id"):
        try:
            artifact = await ctx.read_artifact(raw["artifact_id"])
        except Exception:
            pass
    ops = [o for o in artifact.get("operations", []) if isinstance(o, dict)]
    node_names = sorted({o.get("name", "") for o in ops if o.get("type") == "add_node" and o.get("name")})
    return {
        "node_names": node_names,
        "node_count": len(node_names),
        "_ops": ops,
        "latency_ms": int((time.time() - t0) * 1000),
        "raw": raw,
        "_arch_delta": artifact.get("arch_delta", {}),
    }


# ═══════════════════════════════════════════════════════════════════
# Test 1: Repeat Diversity
# ═══════════════════════════════════════════════════════════════════


@register
class VarietyRepeatDiversity(Test):
    id = "variety.repeat_diversity"
    category = "variety"
    title = "Repeat diversity"
    description = "Run 'build a kitchen' ×10 with skip_cache → Jaccard distance across runs."
    suites = ["everything", "diagnostics-v1"]
    needs_reset = True
    skip_cache = True
    timeout_s = 1800  # 10 LLM calls

    async def run(self, ctx: Context) -> dict[str, Any]:
        run_data: list[dict] = []
        for rn in range(1, 11):
            # Per-run scene reset to match original diagnostics.py behavior.
            # The runner resets once before the test; we reset between iterations
            # so each apply_spec sees a pristine scene (matching bench._probe_scene_reset).
            if rn > 1:
                await _between_run_reset(ctx)
            rd = await _one_apply(ctx, REPEAT_PROMPT, planner="room")
            rd["run"] = rn
            run_data.append(rd)
        return {"run_data": run_data}

    def score(self, raw: dict) -> ScoredResult:
        run_data = raw.get("run_data", [])
        diversity = _compute_diversity(run_data)
        jaccard = diversity["jaccard_distance"]
        distinct = diversity["distinct_outputs"]
        total = diversity["total_runs"]

        # Parity target: 9b ≈0.71, 27b ≈0.00
        status: Status = "ok" if jaccard > 0.05 else ("partial" if jaccard > 0.0 else "broke")
        score = round(jaccard * 100)

        node_counts = [rd.get("node_count", 0) for rd in run_data]
        avg_nodes = round(sum(node_counts) / max(len(node_counts), 1))

        return ScoredResult(
            self.id,
            status,
            score=score,
            metrics={
                "diversity": Metric.ratio(jaccard, "Jaccard diversity"),
                "asset_similarity": Metric.ratio(diversity["asset_similarity"], "asset similarity"),
                "distinct": Metric.count(distinct, "distinct outputs"),
                "avg_nodes": Metric.count(avg_nodes, "avg nodes per run"),
            },
            raw=raw,
        )


# ═══════════════════════════════════════════════════════════════════
# Test 2: Intent Sensitivity
# ═══════════════════════════════════════════════════════════════════


@register
class VarietyIntentSensitivity(Test):
    id = "variety.intent_sensitivity"
    category = "variety"
    title = "Intent sensitivity"
    description = "4 adjective variants (cramped/spacious/abandoned/luxurious) → pairwise differentiation."
    suites = ["everything", "diagnostics-v1"]
    needs_reset = True
    skip_cache = True
    timeout_s = 1200  # 4 LLM calls

    async def run(self, ctx: Context) -> dict[str, Any]:
        results: list[dict] = []
        for i, (label, prompt) in enumerate(INTENT_PROMPTS):
            if i > 0:
                await _between_run_reset(ctx)
            rd = await _one_apply(ctx, prompt, planner="room")
            rd["label"] = label
            rd["prompt"] = prompt
            results.append(rd)
        return {"results": results}

    def score(self, raw: dict) -> ScoredResult:
        results = raw.get("results", [])
        pairs_checked = 0
        pairs_different = 0
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                ni = set(results[i].get("node_names", []))
                nj = set(results[j].get("node_names", []))
                pairs_checked += 1
                if ni != nj:
                    pairs_different += 1

        intent_coverage = pairs_different / max(pairs_checked, 1)
        # Parity target: ≈0.83 (5/6 pairs differ)
        status: Status = "ok" if intent_coverage >= 0.5 else ("partial" if intent_coverage > 0 else "broke")
        score = round(intent_coverage * 100)

        return ScoredResult(
            self.id,
            status,
            score=score,
            metrics={
                "intent_coverage": Metric.ratio(intent_coverage, "intent coverage"),
                "pairs_different": Metric.count(pairs_different, "pairs different"),
                "pairs_total": Metric.count(pairs_checked, "pairs total"),
            },
            raw=raw,
        )


# ═══════════════════════════════════════════════════════════════════
# Test 3: Model Ceiling
# ═══════════════════════════════════════════════════════════════════


@register
class VarietyCeiling(Test):
    id = "variety.ceiling"
    category = "variety"
    title = "Model ceiling"
    description = "Hard relational prompt — does a bigger model produce richer output?"
    suites = ["everything", "diagnostics-v1"]
    needs_reset = True
    skip_cache = True
    repeatable = True  # user may want to compare 4B vs 27B

    async def run(self, ctx: Context) -> dict[str, Any]:
        rd = await _one_apply(ctx, CEILING_PROMPT, planner="room")
        errors = rd.get("raw", {}).get("errors", [])
        rd["error_count"] = len(errors)
        rd["errors"] = errors
        return rd

    def score(self, raw: dict) -> ScoredResult:
        node_count = raw.get("node_count", 0)
        error_count = raw.get("error_count", 0)
        node_names = raw.get("node_names", [])

        # Coverage: more nodes + fewer errors is better
        score = min(100, max(0, node_count * 3 - error_count * 20))

        status: Status = "ok" if node_count >= 5 and error_count == 0 else ("partial" if node_count >= 2 else "broke")

        return ScoredResult(
            self.id,
            status,
            score=score,
            metrics={
                "nodes": Metric.count(node_count, "nodes built"),
                "errors": Metric.count(error_count, "errors", higher_is_better=False),
                "latency": Metric(raw.get("latency_ms", 0), "ms", False, "latency"),
            },
            raw=raw,
            errors=raw.get("errors", [])[:3] if error_count else [],
        )
