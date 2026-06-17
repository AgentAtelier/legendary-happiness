#!/usr/bin/env python3
"""Move 1 Diagnostics Runner — measure the bottleneck, get the baseline.

USAGE (run from hub/ directory):
  # Test 1: Repeat-diversity — "build a kitchen" ×10 on current model
  python diagnostics.py repeat

  # Test 2: Intent-sensitivity — 4 adjective variants, pairwise comparison
  python diagnostics.py intent

  # Test 3: Model ceiling — hard relational prompt on 4B vs 27B
  python diagnostics.py ceiling

  # All three tests (requires model swaps)
  python diagnostics.py all

WHAT EACH TEST MEASURES:
  Test 1 (repeat):  Jaccard distance + distinct-output ratio across 10 runs.
    Hypothesis: ~0.0 (all identical — the cache/engine bottleneck).
  Test 2 (intent):  Pairwise node-set differences across 4 adjective variants.
    Hypothesis: ~0% (adjective ignored — "cramped" = "spacious" = "abandoned").
  Test 3 (ceiling): Coverage score on the hard "wizard's tower" prompt.
    Hypothesis: near-identical on 4B and 27B — the interface is the ceiling.

The runner uses skip_cache=True (cache fix from Move 1) so no plan replay.
Each test persists its result to data/gauntlet/gauntlet-<ts>.json.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from bench import read_env, _devforge_call, _probe_scene_reset, _scene_paths
from gauntlet import _compute_diversity

DATA_DIR = Path(__file__).parent / "data" / "diagnostics"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _summarize_nodes(ops: list) -> str:
    """One-line summary of what was built."""
    names = sorted(set(
        o.get("name", "") for o in ops
        if isinstance(o, dict) and o.get("type") == "add_node"
    ))
    return f"{len(names)} nodes: {', '.join(names[:8])}" + (
        f" (+{len(names)-8})" if len(names) > 8 else ""
    )


async def _apply_with_full_ops(prompt: str, planner: str = "room",
                              temperature: float = 0.2,
                              timeout_s: int = 300) -> dict:
    """Call apply_spec and read the full artifact to get operations.

    apply_spec returns a compact summary. The full operations list,
    arch_delta, and stage_latencies are in the artifact fetched via
    read_artifact.
    """
    summary = await _devforge_call("apply_spec", {
        "prompt": prompt,
        "temperature": temperature,
        "planner": planner,
        "skip_cache": True,
    }, timeout_s=timeout_s)
    aid = summary.get("artifact_id")
    if aid:
        try:
            artifact = await _devforge_call(
                "read_artifact", {"artifact_id": aid}, timeout_s=30,
            )
        except Exception:
            artifact = summary
    else:
        artifact = summary
    # Merge: summary has applied/operations_total; artifact has operations/arch_delta
    if isinstance(artifact, dict):
        artifact["applied"] = summary.get("applied")
        artifact["operations_total"] = summary.get("operations_total")
        artifact["errors"] = summary.get("errors", []) + artifact.get("errors", [])
    return artifact


# ═══════════════════════════════════════════════════════════════════
# Test 1: Repeat-diversity
# ═══════════════════════════════════════════════════════════════════

async def test_repeat_diversity(emit=print, runs: int = 10) -> dict:
    """Run 'build a kitchen' ×N times with skip_cache=True.

    Measures: Jaccard distance, asset similarity, distinct-output ratio.
    """
    emit("═══ Test 1: Repeat-Diversity ═══")
    emit(f"Prompt: 'build a kitchen' ×{runs} (skip_cache=True, planner=room)")
    emit("")

    run_data: list[dict] = []
    for rn in range(1, runs + 1):
        emit(f"  run {rn}/{runs}...", end=" ")
        await _probe_scene_reset()
        before = await _scene_paths()
        t0 = time.time()

        try:
            result = await _apply_with_full_ops(
                "build a kitchen", planner="room",
            )
            crashed = False
        except Exception as e:
            result = {"errors": [f"crashed: {e}"]}
            crashed = True

        ms = int((time.time() - t0) * 1000)
        after = await _scene_paths()
        ops = result.get("operations", [])
        node_count = sum(
            1 for o in ops if isinstance(o, dict) and o.get("type") == "add_node"
        )

        emit(f"{node_count} nodes, {ms//1000}s"
             + (" CRASHED" if crashed else ""))

        run_data.append({
            "run": rn,
            "node_count": node_count,
            "node_names": sorted(set(
                o.get("name", "") for o in ops
                if isinstance(o, dict) and o.get("type") == "add_node"
            )),
            "_ops": [o for o in ops if isinstance(o, dict)],
            "_arch_delta": result.get("arch_delta", {}),
            "nodes_sample": sorted(set(
                o.get("name", "") for o in ops
                if isinstance(o, dict) and o.get("type") == "add_node"
            )),
            "latency_ms": ms,
            "coverage": 100 if not crashed and node_count > 0 else 0,
        })

    emit("")
    diversity = _compute_diversity(run_data)
    emit("─── Results ───")
    emit(f"  Jaccard distance:     {diversity['jaccard_distance']:.3f}  (0=identical, 1=all different)")
    emit(f"  Asset similarity:     {diversity['asset_similarity']:.3f}  (1=identical, 0=all different)")
    emit(f"  Distinct outputs:     {diversity['distinct_outputs']}/{diversity['total_runs']}")
    emit(f"  Hypothesis:           ~0.0 jaccard, ~1 distinct (engine bottleneck)")

    # Persist
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = DATA_DIR / f"diag-repeat-{ts}.json"
    card = {
        "kind": "move1-diagnostics",
        "test": "repeat_diversity",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": read_env().get("MODEL_ALIAS", "?"),
        "prompt": "build a kitchen",
        "planner": "room",
        "skip_cache": True,
        "runs": runs,
        "diversity": diversity,
        "run_data": run_data,
        "hypothesis": "~0.0 jaccard, ~1 distinct (engine bottleneck)",
    }
    out.write_text(json.dumps(card, indent=2))
    emit(f"\n→ saved {out}")
    return card


# ═══════════════════════════════════════════════════════════════════
# Test 2: Intent-sensitivity
# ═══════════════════════════════════════════════════════════════════

INTENT_PROMPTS = [
    ("cramped",   "build a cramped kitchen"),
    ("spacious",  "build a spacious kitchen"),
    ("abandoned", "build an abandoned kitchen"),
    ("luxurious", "build a luxurious kitchen"),
]

async def test_intent_sensitivity(emit=print) -> dict:
    """Run 4 adjective variants, measure pairwise output differences.

    Measures: how many pairs produce different node sets.
    Hypothesis: 0/6 — adjective is completely ignored.
    """
    emit("═══ Test 2: Intent-Sensitivity ═══")
    emit("4 adjective variants, pairwise comparison (skip_cache=True, planner=room)")
    emit("")

    results: list[dict] = []
    for label, prompt in INTENT_PROMPTS:
        emit(f"  [{label}] '{prompt}'...", end=" ")
        await _probe_scene_reset()
        t0 = time.time()

        try:
            result = await _apply_with_full_ops(
                prompt, planner="room",
            )
            crashed = False
        except Exception as e:
            result = {"errors": [f"crashed: {e}"]}
            crashed = True

        ms = int((time.time() - t0) * 1000)
        ops = result.get("operations", [])
        node_names = sorted(set(
            o.get("name", "") for o in ops
            if isinstance(o, dict) and o.get("type") == "add_node"
        ))
        node_count = len(node_names)

        emit(f"{node_count} nodes in {ms//1000}s"
             + (" CRASHED" if crashed else ""))

        results.append({
            "label": label,
            "prompt": prompt,
            "node_count": node_count,
            "node_names": node_names,
            "latency_ms": ms,
            "crashed": crashed,
        })

    emit("")
    emit("─── Pairwise Comparison ───")
    pairs_checked = 0
    pairs_different = 0
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            ni = set(results[i]["node_names"])
            nj = set(results[j]["node_names"])
            same = ni == nj
            pairs_checked += 1
            icon = "=" if same else "≠"
            emit(f"  {results[i]['label']:>9} vs {results[j]['label']:<9}  {icon}  "
                 f"({'IDENTICAL' if same else 'DIFFERENT'})")
            if not same:
                pairs_different += 1

    emit("")
    intent_coverage = pairs_different / max(pairs_checked, 1)
    emit(f"  Intent coverage: {pairs_different}/{pairs_checked} pairs differ ({intent_coverage:.0%})")
    emit(f"  Hypothesis: 0/{pairs_checked} (adjective completely ignored)")

    # Persist
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = DATA_DIR / f"diag-intent-{ts}.json"
    card = {
        "kind": "move1-diagnostics",
        "test": "intent_sensitivity",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": read_env().get("MODEL_ALIAS", "?"),
        "planner": "room",
        "skip_cache": True,
        "pairs_checked": pairs_checked,
        "pairs_different": pairs_different,
        "intent_coverage": round(intent_coverage, 3),
        "results": results,
        "hypothesis": "0/6 pairs differ (adjective ignored)",
    }
    out.write_text(json.dumps(card, indent=2))
    emit(f"\n→ saved {out}")
    return card


# ═══════════════════════════════════════════════════════════════════
# Test 3: Model ceiling
# ═══════════════════════════════════════════════════════════════════

CEILING_PROMPT = (
    "a wizard's tower where the wizard grew afraid of heights — "
    "upper floors sealed and dusty, living area migrated down to the ground floor"
)

async def test_model_ceiling(emit=print) -> dict:
    """Run the hard relational prompt on the current model.

    Measures: coverage, node count, error count.
    The user runs this TWICE — once on 4B, once on 27B — and compares.
    Hypothesis: near-identical results — the interface, not the model, is the ceiling.
    """
    emit("═══ Test 3: Model Ceiling ═══")
    emit(f"Prompt: '{CEILING_PROMPT}'")
    emit(f"Planner: room (skip_cache=True)")
    emit("")
    emit("  RUN THIS TWICE: once on 4B, once on 27B, then compare.")
    emit("")

    await _probe_scene_reset()
    t0 = time.time()

    try:
        result = await _apply_with_full_ops(
            CEILING_PROMPT, planner="room", timeout_s=300,
        )
        crashed = False
    except Exception as e:
        result = {"errors": [f"crashed: {e}"]}
        crashed = True

    ms = int((time.time() - t0) * 1000)
    ops = result.get("operations", [])
    node_names = sorted(set(
        o.get("name", "") for o in ops
        if isinstance(o, dict) and o.get("type") == "add_node"
    ))
    errors = result.get("errors", [])
    node_count = len(node_names)
    error_count = len(errors)

    emit("─── Result ───")
    emit(f"  Model:        {read_env().get('MODEL_ALIAS', '?')}")
    emit(f"  Nodes built:  {node_count}")
    emit(f"  Errors:       {error_count}")
    emit(f"  Latency:      {ms//1000}s")
    if node_names:
        emit(f"  Node names:   {', '.join(node_names[:10])}"
             + (f" (+{len(node_names)-10})" if len(node_names) > 10 else ""))
    if errors:
        emit(f"  Error detail: {errors[:3]}")

    emit("")
    emit("  Hypothesis: near-identical on 4B and 27B (interface is the ceiling).")
    emit("  Compare the node_count and error_count across runs.")

    # Persist
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = DATA_DIR / f"diag-ceiling-{ts}.json"
    card = {
        "kind": "move1-diagnostics",
        "test": "model_ceiling",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": read_env().get("MODEL_ALIAS", "?"),
        "prompt": CEILING_PROMPT,
        "planner": "room",
        "skip_cache": True,
        "node_count": node_count,
        "error_count": error_count,
        "node_names": node_names,
        "errors": errors,
        "latency_ms": ms,
        "crashed": crashed,
        "hypothesis": "near-identical on 4B vs 27B (interface is the ceiling)",
    }
    out.write_text(json.dumps(card, indent=2))
    emit(f"\n→ saved {out}")
    return card


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def _cli() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "repeat":
        asyncio.run(test_repeat_diversity())
    elif cmd == "intent":
        asyncio.run(test_intent_sensitivity())
    elif cmd == "ceiling":
        asyncio.run(test_model_ceiling())
    elif cmd == "all":
        async def _all():
            await test_repeat_diversity()
            print("\n" + "=" * 60 + "\n")
            await test_intent_sensitivity()
            print("\n" + "=" * 60 + "\n")
            await test_model_ceiling()
        asyncio.run(_all())
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
