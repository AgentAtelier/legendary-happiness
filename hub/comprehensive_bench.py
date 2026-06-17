#!/usr/bin/env python3
"""
Comprehensive Forge Ecosystem Benchmark — runs EVERY test, gathers EVERY result.

Unit tests (once):
  • DevForge Core       — 689 pytest tests
  • Forge Hub           — 10 pytest test files
  • Odysseus            — 504 pytest test files

Model-dependent tests (3× each on the CURRENT model):
  • diagnostics repeat  — "build a kitchen" ×10 per run
  • diagnostics intent  — 4 adjective variants per run
  • diagnostics ceiling — 1 hard relational prompt per run
  • probes (all)        — 16 chain probes (llama, devforge, godot-ai, runtime, odysseus)
  • gauntlet (key)      — 5 discriminating tests: G7, G5, G8, B1, S4

All output lands in hub/data/comprehensive-bench/<ts>/

Usage:
  cd /home/mrg/dev/games/Forge/hub
  python comprehensive_bench.py                  # Run on current model
  python comprehensive_bench.py --model qwen3-5-4b  # Swap model first, then run
  python comprehensive_bench.py --skip-unit      # Skip unit tests
  python comprehensive_bench.py --skip-model      # Skip model-dependent tests
  python comprehensive_bench.py --dry             # Show what would run, don't execute
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

HOME = Path.home()
HUB_DIR = Path(__file__).parent.resolve()
FORGE_DIR = HOME / "dev" / "games" / "Forge"
DEVFORGE_DIR = FORGE_DIR / "engine"
ODYSSEUS_DIR = HOME / "dev" / "ai" / "odysseus"
OUTPUT_BASE = HUB_DIR / "data" / "comprehensive-bench"

# ── Which model-dependent tests to run, and how ──────────────────
MODEL_TESTS = [
    ("diagnostics:repeat",   "diagnostics repeat",    "diagnostics"),
    ("diagnostics:intent",   "diagnostics intent",    "diagnostics"),
    ("diagnostics:ceiling",  "diagnostics ceiling",   "diagnostics"),
    ("probes:all",           "run all probes",        "probes"),
    ("gauntlet:key",         "gauntlet key tests",    "gauntlet"),
]

GAUNTLET_KEY_TESTS = ["G7_integration", "G5_scripts_signals", "G8_adversarial",
                       "B1_small_house", "S4_adjacency"]
GAUNTLET_KEY_SETS = {"G7_integration": "capability-v1", "G5_scripts_signals": "capability-v1",
                     "G8_adversarial": "capability-v1", "B1_small_house": "building-v1",
                     "S4_adjacency": "spatial-v1"}

RUNS = 3  # Number of times to repeat each model-dependent test


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def log(msg: str = "", **kwargs) -> None:
    print(msg, flush=True, **kwargs)


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


async def run_cmd(cmd: str, cwd: str | None = None,
                  timeout: int = 600) -> tuple[int, str]:
    """Run a shell command, return (exit_code, combined_output)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd) if cwd else None,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"TIMEOUT after {timeout}s"
    return proc.returncode or 0, raw.decode(errors="replace")


def parse_pytest_summary(output: str) -> dict:
    """Extract pass/fail/skip counts from pytest output."""
    m = re.search(r"(\d+) passed", output)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", output)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) skipped", output)
    skipped = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) warnings?", output)
    warnings = int(m.group(1)) if m else 0
    errors = len(re.findall(r"^(ERROR|FAIL)", output, re.M))
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "warnings": warnings, "errors": errors}


# ═══════════════════════════════════════════════════════════════════
#  Section runners
# ═══════════════════════════════════════════════════════════════════

async def run_unit_tests(outdir: Path) -> dict:
    """Run all 3 pytest suites, save logs, return summary."""
    log("\n── Unit Tests ──")
    results: dict[str, Any] = {}

    suites = [
        ("DevForge Core",  str(DEVFORGE_DIR / "devforge" / "tests"),
         f"cd {DEVFORGE_DIR} && .venv/bin/python -m pytest devforge/tests/ -v"),
        ("Forge Hub",      str(HUB_DIR / "tests"),
         f"cd {HUB_DIR} && .venv/bin/python -m pytest tests/ -v"),
        ("Odysseus",       str(ODYSSEUS_DIR / "tests"),
         f"cd {ODYSSEUS_DIR} && .venv/bin/python -m pytest tests/ -v"),
    ]

    for name, _, cmd in suites:
        log(f"  ▶ {name}...", end=" ")
        t0 = time.time()
        code, output = await run_cmd(cmd, timeout=600)
        elapsed = int((time.time() - t0) * 1000)

        summary = parse_pytest_summary(output)
        summary["exit_code"] = code
        summary["elapsed_ms"] = elapsed
        summary["cmd"] = cmd
        results[name] = summary

        # Save full log
        safe = name.lower().replace(" ", "-")
        logfile = outdir / f"unit-{safe}.log"
        logfile.write_text(output)

        status = "OK" if code == 0 else f"FAIL (code={code})"
        log(f"{status}  {elapsed//1000}s  "
            f"({summary['passed']}p/{summary['failed']}f/{summary['skipped']}s)")

    return results


async def run_diagnostics_test(test_name: str, run_label: str,
                               outdir: Path) -> dict:
    """Run a single diagnostics test (repeat/intent/ceiling)."""
    # The test function captures its data to the standard diagnostics dir.
    # After it finishes, we copy the output file into our unified output dir.
    diag_dir = HUB_DIR / "data" / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    code, output = await run_cmd(
        f"cd {HUB_DIR} && .venv/bin/python diagnostics.py {test_name}",
        timeout=600,
    )
    elapsed = int(time.time() * 1000)  # rough

    # Find the most recent diagnostic file
    latest = None
    if diag_dir.exists():
        files = sorted(diag_dir.glob(f"diag-{test_name}-*.json"), reverse=True)
        if files:
            latest = files[0]
            dest = outdir / latest.name
            shutil.copy2(latest, dest)

    # Also save the raw console output
    logfile = outdir / f"diagnostics-{test_name}-{run_label}.log"
    logfile.write_text(output)

    # Parse result
    data = {}
    if latest:
        try:
            data = json.loads(latest.read_text())
        except Exception:
            data = {"parse_error": str(latest)}

    return {
        "test": f"diagnostics:{test_name}",
        "run": run_label,
        "exit_code": code,
        "data_file": str(latest) if latest else None,
        "result": data,
        "raw_log": str(logfile),
    }


async def run_probes_test(run_label: str, outdir: Path) -> dict:
    """Run the full probe suite."""
    bench_dir = HUB_DIR / "data" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)

    code, output = await run_cmd(
        f"cd {HUB_DIR} && .venv/bin/python bench.py",
        timeout=600,
    )

    # Find the most recent probe file
    latest = None
    if bench_dir.exists():
        files = sorted(bench_dir.glob("probe-*.json"), reverse=True)
        if files:
            latest = files[0]
            dest = outdir / latest.name
            shutil.copy2(latest, dest)

    logfile = outdir / f"probes-all-{run_label}.log"
    logfile.write_text(output)

    data = {}
    if latest:
        try:
            data = json.loads(latest.read_text())
        except Exception:
            data = {"parse_error": str(latest)}

    return {
        "test": "probes:all",
        "run": run_label,
        "exit_code": code,
        "data_file": str(latest) if latest else None,
        "result": data,
        "raw_log": str(logfile),
    }


async def run_gauntlet_key_tests(run_label: str, outdir: Path) -> dict:
    """Run the 5 key gauntlet tests one at a time via the gauntlet module."""
    gauntlet_dir = HUB_DIR / "data" / "gauntlet"
    gauntlet_dir.mkdir(parents=True, exist_ok=True)

    # We import and call the module directly to avoid subprocess overhead for 5 tests
    # But for reliability and isolation, we'll run each as a subprocess
    from gauntlet import run_gauntlet

    results: dict[str, Any] = {}
    all_output = ""

    for tid in GAUNTLET_KEY_TESTS:
        set_id = GAUNTLET_KEY_SETS[tid]
        # Collect output by redirecting the emit to our log
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

    logfile = outdir / f"gauntlet-key-{run_label}.log"
    logfile.write_text(all_output)

    # Find the most recent gauntlet file
    latest = None
    if gauntlet_dir.exists():
        files = sorted(gauntlet_dir.glob("gauntlet-*.json"), reverse=True)
        if files:
            latest = files[0]
            dest = outdir / latest.name
            shutil.copy2(latest, dest)

    return {
        "test": "gauntlet:key",
        "run": run_label,
        "results": results,
        "data_file": str(latest) if latest else None,
        "raw_log": str(logfile),
    }


async def run_model_tests(outdir: Path) -> dict:
    """Run all model-dependent tests 3 times each."""
    log("\n── Model-Dependent Tests (3× each) ──")

    all_results: dict[str, Any] = {}
    run_count = 0
    total = RUNS * len(MODEL_TESTS)

    for run_num in range(1, RUNS + 1):
        run_label = f"run-{run_num}"
        log(f"\n  === Model test round {run_num}/{RUNS} ===")

        for name, _, kind in MODEL_TESTS:
            run_count += 1
            log(f"  ▶ ({run_count}/{total}) {name} [{run_label}]...", end=" ")
            t0 = time.time()

            if kind == "diagnostics":
                test_cli = name.split(":")[1]
                result = await run_diagnostics_test(test_cli, run_label, outdir)
            elif kind == "probes":
                result = await run_probes_test(run_label, outdir)
            elif kind == "gauntlet":
                result = await run_gauntlet_key_tests(run_label, outdir)
            else:
                result = {"error": f"unknown kind: {kind}"}

            elapsed = int((time.time() - t0) * 1000)
            result["elapsed_ms"] = elapsed
            all_results.setdefault(run_label, {})[name] = result
            log(f"{elapsed//1000}s")

    return all_results


def build_cross_run_comparison(all_model_results: dict) -> dict:
    """Build a comparison table across the 3 runs for each model test."""
    comparison: dict[str, Any] = {}

    for test_name, _, _ in MODEL_TESTS:
        entries = []
        for run_label in sorted(all_model_results.keys()):
            run_data = all_model_results.get(run_label, {})
            entry = run_data.get(test_name, {})
            entries.append(entry)

        if not entries:
            continue

        # Compute consistency across runs
        node_counts = []
        coverages = []
        verdicts = []

        for e in entries:
            result = e.get("result", {}) if isinstance(e, dict) else {}
            if isinstance(result, dict):
                nc = result.get("node_count") or result.get("coverage")
                if nc is not None:
                    node_counts.append(nc)
                if "coverage" in result:
                    coverages.append(result["coverage"])
                if "counts" in result:
                    verdicts.append(result["counts"])

        comparison[test_name] = {
            "runs_completed": len([e for e in entries if e.get("exit_code", -1) == 0]),
            "runs_total": len(entries),
            "node_counts": node_counts,
            "coverages": coverages,
            "stable": len(set(str(n) for n in node_counts)) <= 1 if node_counts else None,
        }

    return comparison


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

async def main() -> None:
    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    dry_run = "--dry" in args
    skip_unit = "--skip-unit" in args
    skip_model = "--skip-model" in args

    # Model swap (optional)
    model_alias = None
    for a in list(args):
        if a.startswith("--model="):
            model_alias = a.split("=", 1)[1]
        elif a.startswith("--model"):
            idx = args.index(a)
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
                model_alias = sys.argv[idx + 1]

    env = read_env()
    current_model = env.get("MODEL_ALIAS", "?")

    ts = stamp()
    outdir = OUTPUT_BASE / ts
    if not dry_run:
        outdir.mkdir(parents=True, exist_ok=True)

    log("╔══════════════════════════════════════════════════════════╗")
    log("║     Comprehensive Forge Ecosystem Benchmark             ║")
    log("╚══════════════════════════════════════════════════════════╝")
    log(f"  Timestamp:    {ts}")
    log(f"  Output dir:   {outdir}")
    log(f"  Current model:{current_model}")
    log(f"  Model swap:   {model_alias or '(none)'}")
    log(f"  Dry run:      {'yes' if dry_run else 'no'}")
    log(f"  Skip unit:    {'yes' if skip_unit else 'no'}")
    log(f"  Skip model:   {'yes' if skip_model else 'no'}")
    log(f"  Runs per test:{RUNS}")
    log()

    if dry_run:
        if not skip_unit:
            log("  [DRY] Would run unit tests:")
            log("    • DevForge Core   — 689 tests")
            log("    • Forge Hub       — 10 test files")
            log("    • Odysseus        — 504 test files")
        if not skip_model:
            log(f"\n  [DRY] Would run model-dependent tests ({RUNS}× each):")
            for name, _, kind in MODEL_TESTS:
                log(f"    • {name}")
        log(f"\n  [DRY] All output → {outdir}/")
        return

    # Model swap (if requested)
    if model_alias:
        log(f"  Swapping to model: {model_alias}...")
        try:
            sys.path.insert(0, str(HUB_DIR))
            from forge_ops import swap_model
            code = await swap_model(model_alias, lambda m: log(f"    {m}"))
        except Exception as e:
            log(f"  ✗ Model swap failed: {e}")
            log("  Continuing with current model.")
            code = 1
        if code == 0:
            log(f"  ✓ Swapped to {model_alias}")
            env = read_env()
            current_model = env.get("MODEL_ALIAS", "?")
            log(f"  Confirmed model: {current_model}")

    # ── Run everything ──
    manifest: dict[str, Any] = {
        "kind": "comprehensive-bench",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": current_model,
        "model_swapped": model_alias,
        "output_dir": str(outdir),
        "runs_per_model_test": RUNS,
    }

    total_start = time.time()

    # ── Pre-flight health check for model-dependent tests ──
    stack_healthy = False
    if not skip_model:
        log("\n── Pre-flight: Live Stack Health ──")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as c:
                llm = await c.get(f"http://127.0.0.1:{env.get('LLAMA_PORT', '8002')}/health")
                df = await c.get("http://127.0.0.1:8001/sse")
            stack_healthy = llm.status_code == 200
            log(f"  ✓ llama.cpp :{env.get('LLAMA_PORT', '8002')} — {'OK' if stack_healthy else 'FAIL'}")
        except Exception as e:
            log(f"  ✗ Live stack NOT reachable: {e}")
            log(f"  ⚠  Model-dependent tests will likely fail. Use --skip-model or start the stack first.")
        manifest["stack_healthy"] = stack_healthy

    # Unit tests
    if not skip_unit:
        try:
            unit_results = await run_unit_tests(outdir)
            manifest["unit_tests"] = unit_results
            (outdir / "unit-tests.json").write_text(json.dumps(unit_results, indent=2))
        except Exception as e:
            log(f"  ✗ Unit tests failed: {e}")
            manifest["unit_tests"] = {"error": str(e)}

    # Model-dependent tests
    model_results = {}
    if not skip_model:
        try:
            model_results = await run_model_tests(outdir)
            manifest["model_tests"] = model_results
            (outdir / "model-tests.json").write_text(json.dumps(model_results, indent=2))
        except Exception as e:
            log(f"  ✗ Model tests failed: {e}")
            manifest["model_tests"] = {"error": str(e)}

    # Cross-run comparison
    if model_results:
        try:
            comparison = build_cross_run_comparison(model_results)
            manifest["cross_run_comparison"] = comparison
            (outdir / "cross-run-comparison.json").write_text(
                json.dumps(comparison, indent=2))
        except Exception as e:
            log(f"  ✗ Cross-run comparison failed: {e}")

    total_elapsed = int((time.time() - total_start))
    manifest["total_elapsed_s"] = total_elapsed

    # Write the manifest
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Also write a human-readable summary
    summary_lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║     Comprehensive Forge Ecosystem Benchmark — Results   ║",
        "╚══════════════════════════════════════════════════════════╝",
        f"  Timestamp:    {ts}",
        f"  Model:        {current_model}",
        f"  Total time:   {total_elapsed // 60}m {total_elapsed % 60}s",
        f"  Output dir:   {outdir}",
        "",
    ]

    if not skip_unit and "unit_tests" in manifest:
        unit = manifest["unit_tests"]
        summary_lines.append("── Unit Tests ──")
        for suite_name, suite_result in unit.items():
            if isinstance(suite_result, dict) and "error" not in suite_result:
                summary_lines.append(
                    f"  {suite_name:20s}  "
                    f"{suite_result.get('passed', 0):>3d} passed  "
                    f"{suite_result.get('failed', 0):>3d} failed  "
                    f"{suite_result.get('skipped', 0):>3d} skipped  "
                    f"({suite_result.get('elapsed_ms', 0) // 1000}s)")
            elif "error" in suite_result if isinstance(suite_result, dict) else False:
                summary_lines.append(f"  {suite_name:20s}  ERROR: {suite_result['error']}")
        summary_lines.append("")

    if not skip_model and "model_tests" in manifest:
        mt = manifest["model_tests"]
        summary_lines.append(f"── Model-Dependent Tests ({RUNS}× each) ──")
        for run_label in sorted(mt.keys() if isinstance(mt, dict) else []):
            run_data = mt[run_label]
            summary_lines.append(f"  {run_label}:")
            for test_name, result in run_data.items():
                ec = result.get("exit_code", -1)
                status = "✓" if ec == 0 else "✗"
                summary_lines.append(
                    f"    {status} {test_name:25s}  "
                    f"({result.get('elapsed_ms', 0) // 1000}s, "
                    f"exit={ec})")

        if "cross_run_comparison" in manifest:
            summary_lines.append("")
            summary_lines.append("── Cross-Run Consistency ──")
            for test_name, comp in manifest["cross_run_comparison"].items():
                stable = comp.get("stable")
                stable_str = {True: "STABLE", False: "VARIES", None: "N/A"}.get(stable, "?")
                summary_lines.append(
                    f"  {test_name:25s}  {stable_str}  "
                    f"({comp.get('runs_completed', 0)}/{comp.get('runs_total', 0)} runs)")

    summary_lines.append("")
    summary_lines.append(f"  Full data: {outdir}/")
    summary_lines.append(f"  Manifest:  {outdir}/manifest.json")

    summary = "\n".join(summary_lines)
    (outdir / "SUMMARY.txt").write_text(summary)
    log(f"\n{summary}")
    log(f"\n✓ Done — all results in {outdir}")


if __name__ == "__main__":
    asyncio.run(main())
