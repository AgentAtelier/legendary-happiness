#!/usr/bin/env python3
"""VRAM estimator calibration — Stream C grunt work.

Loads each model in ~/models at multiple context sizes, records actual
peak VRAM from /sys/class/drm, and compares to forge_models.fit() estimates.

Usage:
    python calibrate_vram.py              # measure all models, all ctx sizes
    python calibrate_vram.py --model gemma  # single model
    python calibrate_vram.py --ctx 16384 32768  # specific ctx sizes only

This script:
  1. Stops the current llama service
  2. Reads baseline VRAM (no model loaded)
  3. For each model × ctx size: starts llama, waits for steady state, records peak
  4. Compares measured vs forge_models.fit() estimates
  5. Suggests constant adjustments if the estimator is off
  6. Restores the original model

Destructive: will stop/start llama multiple times. Takes ~10 min for 2 models.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Add hub/ to sys.path so we can import forge_* modules
HUB_DIR = Path(__file__).parent
sys.path.insert(0, str(HUB_DIR))

from forge_env import ENVFILE, read_env, write_env  # noqa: E402
from forge_models import (  # noqa: E402
    FIT_SAFETY_MARGIN,
    GIB,
    KV_BYTES_PER_EL,
    OVERHEAD,
    RESERVE,
    scan,
    vram_total,
)

LLAMA_SERVICE = "forge-llama.service"
MEASURE_WAIT = 30  # seconds to wait for steady state
CTX_SIZES = [4096, 8192, 16384, 24576, 32768]


def read_vram_used() -> int:
    """Read current VRAM usage in bytes from /sys/class/drm."""
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_vram_used"):
        try:
            v = int(p.read_text().strip())
            if v > 4 * 1024 * 1024:  # at least 4 MB
                return v
        except OSError:
            continue
    return 0


def read_vram_total() -> int:
    """Read total VRAM from /sys/class/drm."""
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            v = int(p.read_text().strip())
            if v > 4 * GIB:
                return v
        except OSError:
            continue
    return 16 * GIB


async def run_cmd(*args: str) -> tuple[int, str]:
    """Run a command, return (exit_code, stdout+stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode(errors="replace")


async def stop_llama() -> None:
    """Stop the llama service and wait for VRAM to be freed."""
    print("  Stopping llama service...")
    await run_cmd("systemctl", "--user", "stop", LLAMA_SERVICE)
    await asyncio.sleep(2)
    # Verify it's stopped
    code, state = await run_cmd("systemctl", "--user", "is-active", LLAMA_SERVICE)
    if state.strip() == "active":
        print("  WARNING: llama still active after stop")
    else:
        print("  Llama stopped.")


async def start_llama(model_path: str, ctx_size: int, base_args: str, extra_args: str = "") -> tuple[bool, str]:
    """Start llama-server with the given model and context size.
    Returns (success, error_message)."""
    # Build args: base + ctx-size
    args_list = base_args.split()
    # Replace --ctx-size if present, or append
    replaced = False
    for i, a in enumerate(args_list):
        if a == "--ctx-size" and i + 1 < len(args_list):
            args_list[i + 1] = str(ctx_size)
            replaced = True
            break
    if not replaced:
        args_list.extend(["--ctx-size", str(ctx_size)])

    if extra_args:
        args_list.extend(extra_args.split())

    # Prepend model path as first positional arg
    cmd_args = ["systemctl", "--user", "start", LLAMA_SERVICE]
    # We write env changes and let systemd use the env file
    # Actually, let's just run llama-server directly for measurement
    # to avoid systemd env file complications

    # Use the env file approach: write MODEL + LLAMA_ARGS, restart
    env = read_env(ENVFILE)
    args_str = " ".join(args_list)
    # Single write_env call — combine all updates to avoid overwrite
    alias = Path(model_path).stem
    write_env(
        ENVFILE,
        {
            "MODEL": model_path,
            "MODEL_ALIAS": alias,
            "LLAMA_ARGS": args_str,
        },
    )

    code, out = await run_cmd("systemctl", "--user", "restart", LLAMA_SERVICE)
    if code != 0:
        return False, f"systemctl restart failed (exit {code}): {out[:200]}"

    # Wait for /health
    env = read_env(ENVFILE)
    port = env.get("LLAMA_PORT", "8002")
    for attempt in range(60):
        # Check if service died
        code_fail, _ = await run_cmd("systemctl", "--user", "is-failed", LLAMA_SERVICE)
        if code_fail == 0:
            logs_code, logs = await run_cmd(
                "journalctl",
                "--user",
                "-u",
                LLAMA_SERVICE,
                "-n",
                "10",
                "--no-pager",
                "-o",
                "cat",
            )
            return False, f"llama crashed during load:\n{logs}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "curl",
                "-sf",
                f"http://127.0.0.1:{port}/health",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return True, ""
        except Exception:
            pass
        await asyncio.sleep(1)

    return False, f"timeout waiting for /health after {60}s"


async def measure_one(model: dict, ctx_size: int, base_args: str, baseline_vram: int) -> Optional[dict]:
    """Load one model at one ctx size and measure peak VRAM.

    Returns None if the model won't load (OOM, crash), or a dict with
    measurement data.
    """
    alias = model["alias"]
    path = model.get("path", "")
    extra = model.get("extra_args", "")

    print(f"\n  [{alias}] ctx={ctx_size} ...", end=" ", flush=True)

    # Start llama with this model + ctx
    ok, err = await start_llama(path, ctx_size, base_args, extra)
    if not ok:
        print(f"FAILED: {err[:120]}")
        return None

    # Wait for steady state
    print(f"waiting {MEASURE_WAIT}s for steady state...", end=" ", flush=True)
    await asyncio.sleep(MEASURE_WAIT)

    # Read peak VRAM
    vram = read_vram_used()
    model_vram = max(0, vram - baseline_vram)
    print(f"{model_vram / GIB:.1f} GiB model VRAM (total: {vram / GIB:.1f})")

    return {
        "model": alias,
        "ctx": ctx_size,
        "vram_total": vram,
        "vram_model": model_vram,
        "vram_model_gb": round(model_vram / GIB, 1),
        "loaded": True,
    }


def estimate_for_model(model: dict, ctx_size: int, vram_total_bytes: int) -> dict:
    """Run the estimator for a specific ctx size.

    NOTE: This duplicates the core logic from forge_models.fit() —
    base = d["size_bytes"] + OVERHEAD, budget = vram - RESERVE - FIT_SAFETY_MARGIN.
    If those constants change, keep this function in sync.
    Prefer refactoring fit() to accept an optional ctx= parameter instead.
    """
    # Compute estimate manually — the fit() function uses CTX_CANDIDATES
    # which is a fixed list. We need to evaluate at a specific ctx size.
    d = {**model}
    d["kv_per_tok"] = model.get("kv_per_tok", 0)
    d["size_bytes"] = model.get("size_bytes", 0)
    d["ctx_train"] = model.get("ctx_train", 32768)

    base = d["size_bytes"] + OVERHEAD
    budget = vram_total_bytes - RESERVE - FIT_SAFETY_MARGIN
    need = base + d["kv_per_tok"] * ctx_size

    if need <= budget:
        status = "tight" if need > budget - 0.7 * GIB else "fits"
    else:
        status = "spills"

    return {
        "ctx": ctx_size,
        "need_bytes": need,
        "need_gb": round(need / GIB, 1),
        "status": status,
        "budget_gb": round(budget / GIB, 1),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="VRAM estimator calibration — measure real model VRAM usage")
    parser.add_argument("--model", help="Only measure models matching this fragment")
    parser.add_argument("--ctx", type=int, nargs="*", help=f"Only measure these ctx sizes (default: {CTX_SIZES})")
    parser.add_argument(
        "--wait", type=int, default=MEASURE_WAIT, help=f"Seconds to wait for steady state (default: {MEASURE_WAIT})"
    )
    args = parser.parse_args()

    ctx_sizes = args.ctx or CTX_SIZES

    # ── Setup ────────────────────────────────────────────────────

    print("=" * 70)
    print("VRAM Estimator Calibration — Stream C")
    print(f"  GPU: {read_vram_total() / GIB:.1f} GiB VRAM")
    print("  Models: ~/models/*.gguf")
    print(f"  Ctx sizes: {ctx_sizes}")
    print(f"  Steady-state wait: {args.wait}s per measurement")
    print("=" * 70)

    env = read_env(ENVFILE)
    original_model = env.get("MODEL", "")
    original_alias = env.get("MODEL_ALIAS", "?")
    original_args = env.get("LLAMA_ARGS", "")
    base_args_raw = env.get("LLAMA_BASE_ARGS", "")
    if not base_args_raw:
        print("ERROR: stack.env missing LLAMA_BASE_ARGS — cannot calibrate")
        sys.exit(1)

    # Strip quotes for arg parsing
    base_args = base_args_raw.strip().strip('"').strip("'")

    models = scan()
    if args.model:
        models = [
            m for m in models if args.model.lower() in m["alias"].lower() or args.model.lower() in m["file"].lower()
        ]
    if not models:
        print("No models found. Check ~/models/ for .gguf files.")
        sys.exit(1)

    print(f"\nModels to measure: {len(models)}")
    for m in models:
        fit_info = m.get("fit", {})
        print(
            f"  {m['alias']}  ({m['size_bytes'] / GIB:.1f} GiB, "
            f"arch={m.get('arch', '?')}, kv_per_tok={m.get('kv_per_tok', '?')}, "
            f"fit: {fit_info.get('need_gb', '?')} GiB @ ctx {fit_info.get('ctx', '?')})"
        )

    # ── Stop llama, measure baseline ─────────────────────────────

    print("\n── Step 1: Baseline VRAM ──")
    await stop_llama()
    await asyncio.sleep(3)  # let VRAM fully settle
    baseline_vram = read_vram_used()
    print(f"  Baseline VRAM: {baseline_vram / GIB:.1f} GiB (desktop compositor + system)")

    results: list[dict] = []

    try:
        results = await _run_measurements(models, ctx_sizes, base_args, baseline_vram)
    finally:
        # ── Restore original model ── (ALWAYS, even on crash)
        print(f"\n── Restoring: {original_alias} ──")
        write_env(
            ENVFILE,
            {
                "MODEL": original_model,
                "MODEL_ALIAS": original_alias,
                "LLAMA_ARGS": original_args,
            },
        )
        await run_cmd("systemctl", "--user", "restart", LLAMA_SERVICE)
        print("  Restart requested — llama will load in background.")

    _print_results(results, baseline_vram)


async def _run_measurements(models: list[dict], ctx_sizes: list[int], base_args: str, baseline_vram: int) -> list[dict]:
    """Run the measurement loop for all models × ctx sizes."""
    results: list[dict] = []
    vram_total_bytes = vram_total()

    for model in models:
        print(f"\n── Model: {model['alias']} ──")

        for ctx in ctx_sizes:
            if ctx > model.get("ctx_train", 32768):
                print(f"  [{model['alias']}] ctx={ctx} SKIP (exceeds ctx_train)")
                continue

            measurement = await measure_one(model, ctx, base_args, baseline_vram)
            estimate = estimate_for_model(model, ctx, vram_total_bytes)

            row = {
                "model": model["alias"],
                "ctx": ctx,
                "arch": model.get("arch", "?"),
            }

            if measurement:
                row["measured_gb"] = measurement["vram_model_gb"]
                row["measured_total_gb"] = round(measurement["vram_total"] / GIB, 1)
                row["loaded"] = True
            else:
                row["measured_gb"] = None
                row["measured_total_gb"] = None
                row["loaded"] = False

            row["estimated_gb"] = estimate["need_gb"]
            row["est_status"] = estimate["status"]
            row["budget_gb"] = estimate["budget_gb"]

            if measurement:
                delta = measurement["vram_model_gb"] - estimate["need_gb"]
                row["delta_gb"] = round(delta, 1)
            else:
                row["delta_gb"] = None

            results.append(row)

            # Stop llama between measurements
            await stop_llama()
            await asyncio.sleep(2)

    return results


def _print_results(results: list[dict], baseline_vram: int) -> None:
    print(f"{'Model':<28} {'Ctx':>6} {'Est':>6} {'Meas':>6} {'Delta':>7} {'Status':>8} {'Budget':>7}")
    print("-" * 70)

    for r in results:
        meas = f"{r['measured_gb']:.1f}" if r["measured_gb"] is not None else "  OOM"
        delta = f"{r['delta_gb']:+.1f}" if r["delta_gb"] is not None else "   —"
        loaded = "✓" if r.get("loaded") else "✗"
        print(
            f"{r['model']:<28} {r['ctx']:>6} {r['estimated_gb']:>5.1f}  "
            f"{meas:>5}  {delta:>6}  {r['est_status']:>8} {r['budget_gb']:>5.1f} GiB  {loaded}"
        )

    print("-" * 70)
    print("Delta = Measured - Estimated. Positive = estimator is conservative (safe).")
    print("Negative = estimator is optimistic (DANGER — risk of OOM).")

    # ── Recommendations ──────────────────────────────────────────

    print("\n── Recommendations ──")
    deltas = [r["delta_gb"] for r in results if r["delta_gb"] is not None]
    if deltas:
        avg_delta = sum(deltas) / len(deltas)
        min_delta = min(deltas)
        max_delta = max(deltas)
        print(f"  Delta range: {min_delta:+.1f} to {max_delta:+.1f} GiB (avg {avg_delta:+.1f})")

        if min_delta < 0:
            print(f"  ⚠  Estimator UNDERESTIMATES by up to {-min_delta:.1f} GiB!")
            print(f"     Increase FIT_SAFETY_MARGIN by at least {-min_delta:.1f} GiB.")
            new_margin = FIT_SAFETY_MARGIN + int(-min_delta * GIB * 1.2)
            print(f"     Suggested: FIT_SAFETY_MARGIN = {new_margin / GIB:.1f} GiB")
        elif avg_delta > 1.5:
            print(f"  Estimator is too conservative (avg +{avg_delta:.1f} GiB)")
            print(f"  Consider reducing OVERHEAD (currently {OVERHEAD / GIB:.1f} GiB)")
        else:
            print(f"  ✓ Estimator is well-calibrated (avg delta +{avg_delta:.1f} GiB)")

    # Check gemma SWA fudge specifically
    gemma_results = [r for r in results if "gemma" in r.get("arch", "").lower()]
    non_gemma = [r for r in results if "gemma" not in r.get("arch", "").lower()]
    if gemma_results and non_gemma:
        gemma_deltas = [r["delta_gb"] for r in gemma_results if r["delta_gb"] is not None]
        other_deltas = [r["delta_gb"] for r in non_gemma if r["delta_gb"] is not None]
        if gemma_deltas and other_deltas:
            avg_g = sum(gemma_deltas) / len(gemma_deltas)
            avg_o = sum(other_deltas) / len(other_deltas)
            print("\n  Gemma SWA fudge check:")
            print(f"    Gemma avg delta:  {avg_g:+.1f} GiB")
            print(f"    Non-Gemma avg delta: {avg_o:+.1f} GiB")
            if avg_g < avg_o - 0.5:
                print("    ⚠  Gemma fudge may be too small — SWA *0.45 under-compensates")
            elif avg_g > avg_o + 0.5:
                print("    Gemma fudge may be too large — wasting VRAM on Gemma models")

    # Save results
    out_path = HUB_DIR / "data" / "scorecards" / "vram_calibration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gpu_total_gb": round(read_vram_total() / GIB, 1),
                "baseline_vram_gb": round(baseline_vram / GIB, 1),
                "constants": {
                    "OVERHEAD_GiB": round(OVERHEAD / GIB, 1),
                    "RESERVE_GiB": round(RESERVE / GIB, 1),
                    "FIT_SAFETY_MARGIN_GiB": round(FIT_SAFETY_MARGIN / GIB, 1),
                    "KV_BYTES_PER_EL": KV_BYTES_PER_EL,
                    "gemma_swa_fudge": 0.45,
                },
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
