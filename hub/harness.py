#!/usr/bin/env python3
"""Multi-model harness — sweep the 5 discriminating tests across 4 Qwen models.

Usage:
  python harness.py sweep    # Run the full 200-run sweep (4 models × 5 tests × 10)
  python harness.py matrix <artifact.json>  # Print the readability matrix
  python harness.py dry      # Dry-run: show what WOULD happen without running

The sweep:
  1. Swap to each qwen model (small→big: 4B → 9B → 14B → 27B)
  2. For each model: run the 5 locked gauntlet tests × 10 runs each
  3. Collect per-run coverage + latency
  4. Persist everything to data/harness/harness-<ts>.json
  5. Print the model×test matrix
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

HOME = Path.home()
DATA_DIR = Path(__file__).parent / "data" / "harness"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── The 4 qwen models (small→big swap order) ────────────────────
SWEEP_MODELS = [
    {"alias": "qwen3-5-4b", "label": "qwen3-5-4b"},
    {"alias": "qwen3-5-9b-q8-0", "label": "qwen3-5-9b"},
    {"alias": "qwen3-14b-q6-k", "label": "qwen3-14b"},
    {"alias": "qwen3-6-27b", "label": "qwen3-6-27b"},
]

# ── The 5 locked discriminating tests ────────────────────────────
SWEEP_TESTS = [
    "G7_integration",
    "G5_scripts_signals",
    "G8_adversarial",
    "B1_small_house",
    "S4_adjacency",
]

# Map test IDs to their gauntlet set
TEST_SETS: dict[str, str] = {
    "G7_integration": "capability-v1",
    "G5_scripts_signals": "capability-v1",
    "G8_adversarial": "capability-v1",
    "B1_small_house": "building-v1",
    "S4_adjacency": "spatial-v1",
}


async def _sh(*cmd: str, timeout: float = 30.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s"
    return proc.returncode or 0, raw.decode(errors="replace")


async def swap_model(alias: str, emit) -> bool:
    """Swap to a model via the PROVEN transactional path. Returns True on success.

    CRITICAL FIX (2026-06-16): the previous version ran `forge_models apply`
    (config-only) and restarted forge-DEVFORGE, but NEVER forge-LLAMA — the
    service that actually loads the GGUF. So the running model never changed and
    every sweep column would have measured the *same* model (garbage data). It
    also skipped the VRAM pre-flight, risking an OOM-hang on the tight 27B.

    `forge_ops.swap_model` is the battle-tested swap the hub uses: VRAM
    pre-flight + write_env + restart forge-llama + /health poll + verify the
    loaded model_alias + restart devforge if template/ctx changed + rollback on
    failure. A refused/failed swap returns non-zero, which the caller treats as
    "skip this model" — exactly what we want for the tight 27B.
    """
    from forge_ops import swap_model as _transactional_swap

    emit(f"  swapping to {alias} (transactional: pre-flight + llama restart)...")
    try:
        code = await _transactional_swap(alias, emit)
    except Exception as exc:  # never let one model's failure abort the sweep
        emit(f"  ✗ swap raised: {exc}")
        return False
    if code != 0:
        emit(f"  ✗ swap to {alias} failed/refused (exit {code})")
        return False
    emit(f"  ✓ {alias} loaded and healthy")
    return True


def color_cell(mean: float, best: bool) -> str:
    """Return ANSI-colored cell string: green ≥90, amber 60-89, red <60."""
    if best:
        prefix = "\033[1m"  # bold for best
    else:
        prefix = ""
    if mean >= 90:
        return f"{prefix}\033[32m"  # green
    elif mean >= 60:
        return f"{prefix}\033[33m"  # amber
    else:
        return f"{prefix}\033[31m"  # red


def render_matrix(artifact: dict) -> str:
    """Render a model × test matrix from a harness artifact."""
    models = artifact.get("models", [])
    test_ids = artifact.get("test_ids", [])
    results = artifact.get("results", {})

    if not models or not test_ids:
        return "(no data)"

    COL_W = 17  # fixed column width for alignment

    # Header row
    header = f"{'':20s}"
    for m in models:
        label = m.get("label", m.get("alias", "?"))[:14]
        header += f" {label:>{COL_W}s}"
    lines = [header, "─" * len(header)]

    # Per-test rows
    best_per_row = {}
    for tid in test_ids:
        best_val = -1
        for m in models:
            label = m.get("label", m.get("alias", "?"))
            cell = results.get(label, {}).get(tid, {})
            if "error" in cell:
                continue
            mean = cell.get("mean_coverage", 0)
            if mean > best_val:
                best_val = mean
        best_per_row[tid] = best_val

    for tid in test_ids:
        row = f"  {tid:<18s}"
        for m in models:
            label = m.get("label", m.get("alias", "?"))
            cell = results.get(label, {}).get(tid, {})
            if "error" in cell or not cell:
                row += f" {'SKIP':>{COL_W}s}"
                continue
            mean = cell.get("mean_coverage", 0)
            std = cell.get("stddev_coverage", 0)
            best = mean == best_per_row[tid] and mean > 0
            cc = color_cell(mean, best)
            star = "★" if best else " "
            cell_str = f"{mean:>3d} ±{std:>2d}{star}"
            row += f" {cc}{cell_str:>{COL_W}s}\033[0m"
        lines.append(row)

    # Latency strip
    lines.append("")
    lat_row = f"  {'latency (s)':<18s}"
    for m in models:
        label = m.get("label", m.get("alias", "?"))
        lat_vals = []
        for tid in test_ids:
            cell = results.get(label, {}).get(tid, {})
            if cell.get("mean_latency_ms"):
                lat_vals.append(cell["mean_latency_ms"])
        if lat_vals:
            avg_lat = sum(lat_vals) / len(lat_vals)
            lat_row += f"  {avg_lat / 1000:>4.1f}s{'':>{COL_W - 7}}"
        else:
            lat_row += f" {'—':>{COL_W}s}"
    lines.append(lat_row)

    # Best overall
    lines.append("")
    best_overall = ("", 0)
    for m in models:
        label = m.get("label", m.get("alias", "?"))
        vals = []
        for tid in test_ids:
            cell = results.get(label, {}).get(tid, {})
            if cell.get("mean_coverage"):
                vals.append(cell["mean_coverage"])
        if vals:
            avg = sum(vals) / len(vals)
            if avg > best_overall[1]:
                best_overall = (label, avg)
    if best_overall[0]:
        lines.append(f"  ★ best: {best_overall[0]} (avg {best_overall[1]:.0f}% across {len(test_ids)} tests)")

    return "\n".join(lines)


async def run_sweep(emit=lambda s: print(s), dry: bool = False) -> dict:
    """Run the full sweep: swap models, run gauntlet × 10, collect results.

    Args:
        emit: Callable for progress output.
        dry: If True, print what WOULD happen without running.
    """
    emit("═══ Multi-Model Sweep ═══")
    emit(
        f"Models: {len(SWEEP_MODELS)}  |  Tests: {len(SWEEP_TESTS)}  |  Runs: 10  |  Total: {len(SWEEP_MODELS) * len(SWEEP_TESTS) * 10}"
    )
    emit("")

    if dry:
        for m in SWEEP_MODELS:
            emit(f"[DRY] Would swap to {m['alias']} ({m['label']})")
            for tid in SWEEP_TESTS:
                emit(f"  [DRY]   → {tid} ×10 (set: {TEST_SETS[tid]})")
        return {"dry": True}

    artifact = {
        "kind": "harness",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": SWEEP_MODELS,
        "test_ids": SWEEP_TESTS,
        "results": {},
    }

    # Import gauntlet lazily (requires venv)
    try:
        from gauntlet import run_gauntlet
    except ImportError:
        emit("✗ Cannot import gauntlet — run from the hub directory")
        return {"error": "gauntlet import failed"}

    for mi, m in enumerate(SWEEP_MODELS):
        label = m["label"]
        emit(f"\n── Model {mi + 1}/{len(SWEEP_MODELS)}: {label} ({m['alias']}) ──")

        if not dry:
            ok = await swap_model(m["alias"], emit)
            if not ok:
                emit(f"  ✗ Skipping {label} — model swap failed")
                continue

        model_results = {}
        for tid in SWEEP_TESTS:
            set_id = TEST_SETS[tid]
            emit(f"\n▶ {tid} (set: {set_id}) ×10")

            if dry:
                continue

            try:
                card = await run_gauntlet(
                    set_id,
                    emit=emit,
                    only=[tid],
                    runs=10,
                )
                # Extract per-test stats from the gauntlet result
                if "results" in card:
                    for r in card["results"]:
                        if r.get("id") == tid:
                            model_results[tid] = {
                                "mean_coverage": r.get("mean_coverage", r.get("coverage", 0)),
                                "stddev_coverage": r.get("stddev_coverage", 0),
                                "mean_latency_ms": r.get("mean_latency_ms", r.get("latency_ms", 0)),
                                "n": len(r.get("runs", [r])),
                                "runs": r.get("runs", [r]),
                            }
                            break
            except Exception as e:
                emit(f"  ✗ {tid} failed: {e}")
                model_results[tid] = {"error": str(e)}

        artifact["results"][label] = model_results

    emit("\n━━━ Results ━━━")
    emit(render_matrix(artifact))

    # Persist
    out = DATA_DIR / f"harness-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(artifact, indent=2))
    emit(f"\n→ saved {out}")

    return artifact


def _cli() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "sweep":
        asyncio.run(run_sweep())
    elif cmd == "dry":
        asyncio.run(run_sweep(dry=True))
    elif cmd == "matrix":
        path = sys.argv[2] if len(sys.argv) > 2 else None
        if not path:
            print("usage: python harness.py matrix <harness-ts>.json")
            return
        art = json.loads(Path(path).read_text())
        print(render_matrix(art))
    else:
        print("usage: python harness.py {sweep|dry|matrix <file>}")


if __name__ == "__main__":
    _cli()
