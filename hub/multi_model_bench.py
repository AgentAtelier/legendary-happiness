#!/usr/bin/env python3
"""
Multi-Model Comprehensive Benchmark — runs ALL tests across ALL 4 Qwen models.

Strategy:
  1. Run unit tests ONCE (shared across all models — they don't depend on which
     model is loaded)
  2. For each model (smallest→largest: 4B → 9B → 14B → 27B):
     a. Transactional model swap (VRAM pre-flight + llama restart + health poll)
     b. Run model-dependent tests 3× each (diagnostics, probes, gauntlet key)
  3. Build a cross-model comparison matrix

Output: hub/data/multi-model-bench/<ts>/

Usage:
  cd /home/mrg/dev/games/Forge/hub
  python multi_model_bench.py                        # Full run (all 4 models)
  python multi_model_bench.py --models qwen3-5-4b,qwen3-6-27b  # Subset
  python multi_model_bench.py --dry                  # Show plan
  python multi_model_bench.py --resume <ts>          # Resume from partial run

Estimated time: ~2-3 hours for all 4 models (30-45 min per model)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HOME = Path.home()
HUB_DIR = Path(__file__).parent.resolve()
OUTPUT_BASE = HUB_DIR / "data" / "multi-model-bench"

# All 4 Qwen models, smallest→largest
QWEN_MODELS = [
    {"alias": "qwen3-5-4b", "label": "qwen3-5-4b"},
    {"alias": "qwen3-5-9b-q8-0", "label": "qwen3-5-9b"},
    {"alias": "qwen3-14b-q6-k", "label": "qwen3-14b"},
    {"alias": "qwen3-6-27b", "label": "qwen3-6-27b"},
]

RUNS = 3  # model-dependent test repetitions

# Which model-dependent tests to run
MODEL_TESTS = [
    "diagnostics:repeat",
    "diagnostics:intent",
    "diagnostics:ceiling",
    "probes:all",
    "gauntlet:key",
]


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def log(msg: str = "", **kwargs) -> None:
    print(msg, flush=True, **kwargs)


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def read_env() -> dict[str, str]:
    envfile = HOME / ".config/forge-stack/stack.env"
    env: dict[str, str] = {}
    try:
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return env


async def run_cmd(cmd: str, timeout: int = 600) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"TIMEOUT after {timeout}s"
    return proc.returncode or 0, raw.decode(errors="replace")


def parse_pytest_summary(output: str) -> dict:
    import re

    m = re.search(r"(\d+) passed", output)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", output)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) skipped", output)
    skipped = int(m.group(1)) if m else 0
    return {"passed": passed, "failed": failed, "skipped": skipped}


# ═══════════════════════════════════════════════════════════════════
#  Phase 1: Unit tests (once)
# ═══════════════════════════════════════════════════════════════════


async def run_unit_tests(outdir: Path) -> dict:
    log("\n═══ Phase 1: Unit Tests (shared across all models) ═══")

    DEVFORGE_DIR = HOME / "dev" / "games" / "Forge" / "engine"
    ODYSSEUS_DIR = HOME / "dev" / "ai" / "odysseus"

    suites = [
        ("DevForge Core", f"cd {DEVFORGE_DIR} && .venv/bin/python -m pytest devforge/tests/ -v -q"),
        ("Forge Hub", f"cd {HUB_DIR} && .venv/bin/python -m pytest tests/ -v -q"),
        ("Odysseus", f"cd {ODYSSEUS_DIR} && .venv/bin/python -m pytest tests/ -q"),
    ]

    results = {}
    for name, cmd in suites:
        log(f"  ▶ {name}...", end=" ")
        t0 = time.time()
        code, output = await run_cmd(cmd, timeout=600)
        elapsed = int((time.time() - t0) * 1000)

        summary = parse_pytest_summary(output)
        summary["exit_code"] = code
        summary["elapsed_ms"] = elapsed
        results[name] = summary

        safe = name.lower().replace(" ", "-")
        (outdir / f"unit-{safe}.log").write_text(output)

        status = "OK" if code == 0 else f"FAIL(code={code})"
        log(f"{status}  {elapsed // 1000}s  ({summary['passed']}p/{summary['failed']}f/{summary['skipped']}s)")

    (outdir / "unit-tests.json").write_text(json.dumps(results, indent=2))
    return results


# ═══════════════════════════════════════════════════════════════════
#  Phase 2: Per-model model-dependent tests
# ═══════════════════════════════════════════════════════════════════


async def run_model_round(model: dict, model_dir: Path) -> dict:
    """Swap to model, run all model-dependent tests 3×, return results."""
    label = model["label"]
    alias = model["alias"]
    log(f"\n═══ Model: {label} ({alias}) ═══")

    # ── Swap ──
    log(f"  Swapping to {alias}...")
    t0 = time.time()
    try:
        sys.path.insert(0, str(HUB_DIR))
        from forge_ops import swap_model

        code = await swap_model(alias, lambda m: log(f"    {m}"))
    except Exception as e:
        log(f"  ✗ Swap failed: {e}")
        return {"model": label, "error": str(e), "tests": {}}
    swap_ms = int((time.time() - t0) * 1000)

    if code != 0:
        log(f"  ✗ Swap refused (exit {code}) — skipping {label}")
        return {"model": label, "error": f"swap refused (exit {code})", "tests": {}}

    env = read_env()
    current = env.get("MODEL_ALIAS", "?")
    log(f"  ✓ Loaded: {current} ({swap_ms // 1000}s)")

    # ── Run tests 3× each ──
    test_results: dict[str, Any] = {}
    total_tests = len(MODEL_TESTS) * RUNS
    run_count = 0

    for run_num in range(1, RUNS + 1):
        run_label = f"run-{run_num}"
        run_dir = model_dir / run_label
        run_dir.mkdir(parents=True, exist_ok=True)

        for test_name in MODEL_TESTS:
            run_count += 1
            log(f"  ▶ ({run_count}/{total_tests}) {test_name} [{run_label}]...", end=" ")
            t0 = time.time()

            if test_name.startswith("diagnostics:"):
                result = await _run_diagnostics(test_name.split(":")[1], run_dir)
            elif test_name == "probes:all":
                result = await _run_probes(run_dir)
            elif test_name == "gauntlet:key":
                result = await _run_gauntlet_key(run_dir)
            else:
                result = {"error": f"unknown test: {test_name}"}

            elapsed = int((time.time() - t0) * 1000)
            result["elapsed_ms"] = elapsed
            test_results.setdefault(test_name, {})[run_label] = result
            log(f"{elapsed // 1000}s")

    return {
        "model": label,
        "alias": alias,
        "swap_ms": swap_ms,
        "tests": test_results,
    }


async def _run_diagnostics(test_cli: str, outdir: Path) -> dict:
    """Run a single diagnostics test."""
    diag_dir = HUB_DIR / "data" / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    code, output = await run_cmd(f"cd {HUB_DIR} && .venv/bin/python diagnostics.py {test_cli}", timeout=600)

    # Copy latest diagnostic file
    latest = None
    if diag_dir.exists():
        files = sorted(diag_dir.glob(f"diag-{test_cli}-*.json"), reverse=True)
        if files:
            latest = files[0]
            shutil.copy2(latest, outdir / latest.name)

    (outdir / f"diagnostics-{test_cli}.log").write_text(output)

    data = {}
    if latest:
        try:
            data = json.loads(latest.read_text())
        except Exception:
            data = {"parse_error": str(latest)}

    return {
        "test": f"diagnostics:{test_cli}",
        "exit_code": code,
        "result": data,
        "log": str(outdir / f"diagnostics-{test_cli}.log"),
    }


async def _run_probes(outdir: Path) -> dict:
    """Run the full probe suite."""
    bench_dir = HUB_DIR / "data" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)

    code, output = await run_cmd(f"cd {HUB_DIR} && .venv/bin/python bench.py", timeout=600)

    latest = None
    if bench_dir.exists():
        files = sorted(bench_dir.glob("probe-*.json"), reverse=True)
        if files:
            latest = files[0]
            shutil.copy2(latest, outdir / latest.name)

    (outdir / "probes-all.log").write_text(output)

    data = {}
    if latest:
        try:
            data = json.loads(latest.read_text())
        except Exception:
            data = {"parse_error": str(latest)}

    return {"test": "probes:all", "exit_code": code, "result": data, "log": str(outdir / "probes-all.log")}


GAUNTLET_KEY_TESTS = ["G7_integration", "G5_scripts_signals", "G8_adversarial", "B1_small_house", "S4_adjacency"]
GAUNTLET_KEY_SETS = {
    "G7_integration": "capability-v1",
    "G5_scripts_signals": "capability-v1",
    "G8_adversarial": "capability-v1",
    "B1_small_house": "building-v1",
    "S4_adjacency": "spatial-v1",
}


async def _run_gauntlet_key(outdir: Path) -> dict:
    """Run the 5 key gauntlet tests."""
    gauntlet_dir = HUB_DIR / "data" / "gauntlet"
    gauntlet_dir.mkdir(parents=True, exist_ok=True)

    from gauntlet import run_gauntlet

    results: dict[str, Any] = {}
    all_output = ""

    for tid in GAUNTLET_KEY_TESTS:
        set_id = GAUNTLET_KEY_SETS[tid]
        lines: list[str] = []

        def emit(m: str) -> None:
            lines.append(m)

        try:
            card = await run_gauntlet(set_id, emit=emit, only=[tid], runs=1)
            results[tid] = card
        except Exception as e:
            results[tid] = {"error": str(e)}
            lines.append(f"ERROR: {e}")

        all_output += f"\n── {tid} ──\n" + "\n".join(lines) + "\n"

    (outdir / "gauntlet-key.log").write_text(all_output)

    latest = None
    if gauntlet_dir.exists():
        files = sorted(gauntlet_dir.glob("gauntlet-*.json"), reverse=True)
        if files:
            latest = files[0]
            shutil.copy2(latest, outdir / latest.name)

    return {"test": "gauntlet:key", "results": results, "log": str(outdir / "gauntlet-key.log")}


# ═══════════════════════════════════════════════════════════════════
#  Phase 3: Cross-model comparison
# ═══════════════════════════════════════════════════════════════════


def build_comparison(all_model_results: dict) -> dict:
    """Build model×test coverage matrix."""
    comparison: dict[str, Any] = {
        "models_tested": [],
        "test_matrix": {},
    }

    for test_name in MODEL_TESTS:
        comparison["test_matrix"][test_name] = {}
        for model_label, mdata in all_model_results.items():
            if "error" in mdata:
                comparison["test_matrix"][test_name][model_label] = {"error": mdata["error"]}
                continue

            # Gather run-level results for this test across all 3 runs
            runs_data = []
            for run_label in [f"run-{r}" for r in range(1, RUNS + 1)]:
                run_entry = mdata.get("tests", {}).get(test_name, {}).get(run_label, {})
                if run_entry:
                    runs_data.append(run_entry)

            if not runs_data:
                comparison["test_matrix"][test_name][model_label] = {"error": "no runs"}
                continue

            # Extract coverage/node count from each run
            coverages = []
            node_counts = []
            errors = []
            for rd in runs_data:
                result = rd.get("result", {}) if isinstance(rd, dict) else {}
                if isinstance(result, dict):
                    # diagnostics
                    if "diversity" in result:
                        coverages.append(result["diversity"].get("jaccard_distance", 0))
                    if "node_count" in result:
                        node_counts.append(result["node_count"])
                    if "coverage" in result:
                        coverages.append(result["coverage"])
                    # probes
                    if "counts" in result:
                        errors.append(result["counts"].get("broken", 0))
                    # gauntlet
                    if isinstance(rd.get("results"), dict):
                        for tid, card in rd["results"].items():
                            if isinstance(card, dict) and "summary" in card:
                                s = card["summary"]
                                coverages.append(s.get("avg_coverage", 0))

            comparison["test_matrix"][test_name][model_label] = {
                "runs": len(runs_data),
                "mean_coverage": round(sum(coverages) / max(len(coverages), 1), 1) if coverages else None,
                "mean_nodes": round(sum(node_counts) / max(len(node_counts), 1), 1) if node_counts else None,
                "latencies_ms": [rd.get("elapsed_ms", 0) for rd in runs_data],
            }

    return comparison


def render_comparison_table(comparison: dict) -> str:
    """Render the model×test matrix as an ASCII table."""
    lines = ["", "═══ Cross-Model Comparison ═══", ""]

    models = comparison.get("models_tested", [])
    tests = list(comparison.get("test_matrix", {}).keys())
    if not models or not tests:
        return "(insufficient data)"

    # Determine best per test
    best_per_test = {}
    for test_name in tests:
        best_val = -1
        for ml in models:
            cell = comparison["test_matrix"].get(test_name, {}).get(ml, {})
            cov = cell.get("mean_coverage")
            if cov is not None and cov > best_val:
                best_val = cov
        best_per_test[test_name] = best_val

    COL_W = 16
    header = f"{'':22s}"
    for m in models:
        header += f"  {m[: COL_W - 2]:>{COL_W}s}"
    lines.append(header)
    lines.append("─" * len(header))

    overall_scores = []
    for test_name in tests:
        row = f"  {test_name[:20]:20s}"
        best = best_per_test.get(test_name)
        for ml in models:
            cell = comparison["test_matrix"].get(test_name, {}).get(ml, {})
            if "error" in cell:
                row += f"  {'ERR':>{COL_W}s}"
                continue
            cov = cell.get("mean_coverage")
            nodes = cell.get("mean_nodes")
            if cov is not None:
                marker = "★" if cov == best and best is not None and cov > 0 else " "
                row += f"  {cov:>5.1f}%{marker:>1s}{'':>{COL_W - 8}s}"
            elif nodes is not None:
                row += f"  {nodes:>4.0f}n{'':>{COL_W - 6}s}"
            else:
                row += f"  {'—':>{COL_W}s}"
        lines.append(row)

    # Overall score
    lines.append("")
    for ml in models:
        vals = []
        for test_name in tests:
            cell = comparison["test_matrix"].get(test_name, {}).get(ml, {})
            cov = cell.get("mean_coverage")
            if cov is not None:
                vals.append(cov)
        if vals:
            avg = sum(vals) / len(vals)
            overall_scores.append((ml, avg))
    if overall_scores:
        overall_scores.sort(key=lambda x: -x[1])
        lines.append("  Rankings:")
        for rank, (ml, avg) in enumerate(overall_scores, 1):
            lines.append(f"    {rank}. {ml:<20s} avg {avg:.1f}%")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════


async def main() -> None:
    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    dry_run = "--dry" in args

    # Parse model filter
    models_to_run = list(QWEN_MODELS)
    for a in list(args):
        if a.startswith("--models="):
            wanted = [x.strip() for x in a.split("=", 1)[1].split(",")]
            models_to_run = [m for m in QWEN_MODELS if m["alias"] in wanted or m["label"] in wanted]

    ts = stamp()
    outdir = OUTPUT_BASE / ts
    if not dry_run:
        outdir.mkdir(parents=True, exist_ok=True)

    log("╔══════════════════════════════════════════════════════════╗")
    log("║     Multi-Model Comprehensive Benchmark                 ║")
    log("╚══════════════════════════════════════════════════════════╝")
    log(f"  Timestamp:    {ts}")
    log(f"  Output dir:   {outdir}")
    log(f"  Models:       {len(models_to_run)} — {', '.join(m['label'] for m in models_to_run)}")
    log(f"  Tests/model:  {len(MODEL_TESTS)} × {RUNS} runs = {len(MODEL_TESTS) * RUNS} per model")
    log(f"  Total runs:   {len(models_to_run) * len(MODEL_TESTS) * RUNS}")
    log(f"  Dry run:      {'yes' if dry_run else 'no'}")
    log()

    if dry_run:
        log("  [DRY] Phase 1: Unit tests (once)")
        log("    • DevForge Core   — ~689 tests")
        log("    • Forge Hub       — 10 test files")
        log("    • Odysseus        — ~504 test files")
        log(f"\n  [DRY] Phase 2: Model-dependent tests ({RUNS}× each):")
        for m in models_to_run:
            log(f"    • {m['label']}: swap → {', '.join(MODEL_TESTS)}")
        log(f"\n  [DRY] → {outdir}/")
        return

    manifest: dict[str, Any] = {
        "kind": "multi-model-bench",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": [m["label"] for m in models_to_run],
        "runs_per_test": RUNS,
        "output_dir": str(outdir),
    }
    total_start = time.time()

    # ── Phase 1: Unit tests ──
    unit_results = await run_unit_tests(outdir)
    manifest["unit_tests"] = unit_results

    # ── Phase 2: Per-model runs ──
    all_model_results: dict[str, Any] = {}

    for mi, model in enumerate(models_to_run):
        label = model["label"]
        model_dir = outdir / "models" / label
        model_dir.mkdir(parents=True, exist_ok=True)

        log(f"\n{'═' * 60}")
        log(f"── Model {mi + 1}/{len(models_to_run)}: {label} ──")
        log(f"{'═' * 60}")

        model_result = await run_model_round(model, model_dir)
        all_model_results[label] = model_result
        manifest["models_tested"] = list(all_model_results.keys())

        # Save per-model result immediately
        (outdir / "models" / label / "result.json").write_text(json.dumps(model_result, indent=2, default=str))

        # Save intermediate manifest
        manifest["models"] = all_model_results
        (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    # ── Phase 3: Cross-model comparison ──
    log("\n═══ Phase 3: Cross-Model Comparison ═══")
    comparison = build_comparison(all_model_results)
    comparison["models_tested"] = list(all_model_results.keys())
    manifest["comparison"] = comparison
    (outdir / "comparison.json").write_text(json.dumps(comparison, indent=2, default=str))

    # Render + save summary
    table = render_comparison_table(comparison)
    log(table)

    total_elapsed = int((time.time() - total_start))
    manifest["total_elapsed_s"] = total_elapsed

    summary = [
        "╔══════════════════════════════════════════════════════════╗",
        "║     Multi-Model Benchmark — Complete                     ║",
        "╚══════════════════════════════════════════════════════════╝",
        f"  Total time:   {total_elapsed // 60}m {total_elapsed % 60}s",
        f"  Models:       {', '.join(manifest.get('models_tested', []))}",
        f"  Output:       {outdir}",
        "",
    ]
    summary.append(table)

    (outdir / "SUMMARY.txt").write_text("\n".join(summary))
    manifest["summary"] = "\n".join(summary)
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    log(f"\n{'=' * 60}")
    log(f"✓ Complete — {total_elapsed // 60}m {total_elapsed % 60}s")
    log(f"  All results: {outdir}/")
    log(f"  Comparison:  {outdir}/comparison.json")


if __name__ == "__main__":
    asyncio.run(main())
