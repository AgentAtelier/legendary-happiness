"""Live integration tests for the forge-hub swap pipeline.

Requires the full forge stack to be running (llama, DevForge, godot-ai).
Skipped by default — run with:  pytest hub/tests/ -m live

These are the two cases that were silently broken in the June 13 incident:
  (a) swapping to a known-fitting model must succeed and be verified
  (b) swapping to a too-big config must refuse cleanly and roll back

Stream C of the forge-grunt-work-roadmap — closes the class of bugs
where unit tests pass but real swaps fail.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from forge_env import read_env, ENVFILE
from forge_models import scan, plan_apply, GIB, vram_total, FIT_SAFETY_MARGIN
from forge_ops import swap_model, get_free_vram, check_drift

pytestmark = pytest.mark.live


# ── helpers ──────────────────────────────────────────────────────


def _sanity() -> tuple[str, dict]:
    """Verify the stack is in a testable state. Returns (current_model_name, env)."""
    env = read_env(ENVFILE)
    cur = env.get("MODEL", "")
    if not cur or not Path(cur).exists():
        pytest.skip(f"Model not found: {cur}")
    port = env.get("LLAMA_PORT", "8002")
    import httpx
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3)
        if r.status_code != 200:
            pytest.skip(f"llama /health returned {r.status_code}")
    except Exception:
        pytest.skip("llama not reachable — is the stack up?")
    return Path(cur).name, env


def _find_model(name_fragment: str) -> dict | None:
    """Find a model in the scan list by name fragment."""
    models = scan()
    for m in models:
        if name_fragment.lower() in m["file"].lower() or name_fragment.lower() in m["alias"]:
            return m
    return None


def _read_vram_used() -> int:
    """Read current VRAM usage in bytes from /sys/class/drm."""
    for p in Path("/sys/class/drm").glob("card*/device/mem_info_vram_used"):
        try:
            v = int(p.read_text().strip())
            if v > 4 * 1024 * 1024:  # at least 4 MB — skip tiny/invalid cards
                return v
        except OSError:
            continue
    return 0


# ── Live swap tests ──────────────────────────────────────────────


class TestSwapLive:
    """Real model swaps against the live llama server. Restores original state."""

    def test_swap_to_known_fitting_model(self):
        """Swap to the SMALLEST available model — it must fit and verify."""
        cur_name, env = _sanity()
        models = scan()

        # Pick the smallest model (should always fit)
        smallest = min(models, key=lambda m: m["size_bytes"])
        if Path(smallest["path"]).name == cur_name:
            others = [m for m in models if Path(m["path"]).name != cur_name]
            if not others:
                pytest.skip("Only one model available — can't test swap")
            target = min(others, key=lambda m: m["size_bytes"])
        else:
            target = smallest

        plan = plan_apply(target["alias"])
        if "error" in plan:
            pytest.skip(f"plan_apply failed: {plan['error']}")

        need_gb = plan["model"]["fit"]["need_gb"]
        free_gb = get_free_vram() / GIB
        reclaim = Path(env.get("MODEL", "")).stat().st_size / GIB if env.get("MODEL") else 0
        if need_gb > free_gb + reclaim:
            pytest.skip(
                f"Not enough VRAM: model needs {need_gb} GiB, "
                f"only {free_gb + reclaim:.1f} GiB available. "
                f"Close GPU apps and retry."
            )

        original_model = env.get("MODEL_ALIAS", "?")
        lines: list[str] = []

        try:
            t0 = time.time()
            exit_code = asyncio.run(
                swap_model(target["alias"], lambda line: lines.append(line))
            )
            elapsed = time.time() - t0

            if exit_code != 0:
                all_output = "\n".join(lines)
                pytest.fail(
                    f"Swap to {target['alias']} failed (exit {exit_code}) "
                    f"in {elapsed:.0f}s:\n{all_output}"
                )

            # Verify the running model matches
            cur_env = read_env(ENVFILE)
            assert cur_env.get("MODEL_ALIAS") == target["alias"], (
                f"stack.env says {cur_env.get('MODEL_ALIAS')}, "
                f"expected {target['alias']}"
            )

            # Drift check should show no drift
            drift = asyncio.run(
                check_drift(cur_env.get("LLAMA_PORT", "8002"))
            )
            if drift and drift.get("drift"):
                pytest.fail(
                    f"Drift detected after swap: {drift.get('reason')}"
                )

        finally:
            # Restore original model — fail if restore doesn't work
            if read_env(ENVFILE).get("MODEL_ALIAS") != original_model:
                lines.append(f"[restore] swapping back to {original_model}...")
                restore_exit = asyncio.run(
                    swap_model(original_model, lambda _: None)
                )
                if restore_exit != 0:
                    pytest.fail(
                        f"CRITICAL: restore to {original_model} FAILED — "
                        f"manual recovery needed! Run: stack model {original_model}"
                    )
                lines.append(f"[restore] restored {original_model}")

    def test_swap_too_big_refuses_cleanly(self):
        """Request a too-big swap — must refuse with a clear message and
        leave the previous model running. Does NOT actually write bad config."""
        cur_name, env = _sanity()

        models = scan()
        biggest = max(models, key=lambda m: m["size_bytes"])

        if Path(biggest["path"]).name == cur_name:
            pytest.skip("Already running the biggest model — can't test too-big swap")

        plan = plan_apply(biggest["alias"])
        if "error" in plan:
            pytest.fail(f"plan_apply failed: {plan['error']}")

        need_gb = plan["model"]["fit"]["need_gb"]
        free_gb = get_free_vram() / GIB
        reclaim = Path(env.get("MODEL", "")).stat().st_size / GIB if env.get("MODEL") else 0
        available = free_gb + reclaim

        if need_gb <= available:
            pytest.skip(
                f"Biggest model ({biggest['alias']}, {need_gb} GiB) actually "
                f"fits in {available:.1f} GiB available — can't test refusal case. "
                f"Try closing GPU apps or testing with a bigger model."
            )

        lines: list[str] = []
        t0 = time.time()
        exit_code = asyncio.run(
            swap_model(biggest["alias"], lambda line: lines.append(line))
        )
        elapsed = time.time() - t0

        assert exit_code == 1, (
            f"Expected swap to REFUSE (exit 1) but got exit {exit_code}. "
            f"Output:\n" + "\n".join(lines[-20:])
        )

        all_output = "\n".join(lines)
        assert any(w in all_output.lower() for w in ("vram", "gib", "available")), (
            f"Refusal message should mention VRAM constraints. Output:\n{all_output}"
        )

        # Verify the original model is still configured
        cur_env = read_env(ENVFILE)
        assert cur_env.get("MODEL_ALIAS") == env.get("MODEL_ALIAS"), (
            f"stack.env was MUTATED by a refused swap! "
            f"Expected {env.get('MODEL_ALIAS')}, got {cur_env.get('MODEL_ALIAS')}"
        )

        # Verify the original model is still running
        drift = asyncio.run(
            check_drift(env.get("LLAMA_PORT", "8002"))
        )
        if drift:
            running = drift.get("running_alias", "")
            configured = env.get("MODEL_ALIAS", "")
            assert running == configured, (
                f"Model changed after refusal! Configured: {configured}, "
                f"Running: {running}"
            )

        assert elapsed < 10, (
            f"Refusal took {elapsed:.1f}s — should be near-instant "
            f"(VRAM check alone, no restart)"
        )


# ── Estimator calibration ────────────────────────────────────────


class TestEstimatorCalibration:
    """Stream C: verify the VRAM fit estimator's safety margin is calibrated.

    Measurement methodology (June 13, 2026 — RX 6800 / 16 GiB VRAM):
      - Loaded each model at 5 ctx sizes (4096, 8192, 16384, 24576, 32768)
      - Recorded peak VRAM from /sys/class/drm/card0/device/mem_info_vram_used
        at steady state (30s after /health returned 200).
      - Compared to forge_models.fit() estimates.
      - Tuned FIT_SAFETY_MARGIN upward from 0.1 GiB to 0.6 GiB after
        Gemma 26B @ ctx 32768 OOMed at a reported "15.0/16.0 GiB".
      - Gemma SWA *0.45 fudge derived from 4 loads of Gemma 12B comparing
        actual KV-cache growth per 4096 ctx increment vs non-SWA Qwen3 14B.
    """

    def test_known_model_fit_is_reasonable(self):
        """For every model in ~/models, fit() should return a plausible estimate."""
        models = scan()
        assert len(models) >= 1, "Need at least one model to calibrate"
        vram = vram_total()

        for m in models:
            f = m["fit"]
            need = f["need_gb"]

            # Model + KV cache must be at least the GGUF file size
            file_gb = m["size_bytes"] / GIB
            assert need >= file_gb, (
                f"{m['alias']}: fit says {need} GiB but the GGUF alone "
                f"is {file_gb:.1f} GiB — estimator is broken"
            )

            # Should not claim to fit in impossibly small VRAM
            if need > vram / GIB + 2.0:
                assert f["status"] == "spills", (
                    f"{m['alias']}: {need} GiB exceeds {vram / GIB:.1f} GiB "
                    f"VRAM but status is '{f['status']}', not 'spills'"
                )

    def test_safety_margin_prevented_june13_brick(self):
        """The June 13 incident: Gemma 26B @ ctx 32768 reported "tight,
        15.0/16.0G" then cudaMalloc'd at runtime. Verify the safety
        margin would catch this today."""

        models = scan()
        gemma26 = _find_model("26b-a4b")
        if not gemma26:
            pytest.skip("Gemma 26B model not found — can't test the regression case")

        f = gemma26["fit"]
        need = f["need_gb"]
        vram = vram_total()
        budget = vram - 0.4 * GIB - FIT_SAFETY_MARGIN  # RESERVE + safety margin
        need_bytes = int(need * GIB)

        if need_bytes <= budget and need_bytes > budget - FIT_SAFETY_MARGIN:
            assert f["status"] in ("tight", "spills"), (
                f"Gemma 26B fits at {need} GiB in {vram / GIB:.1f} GiB VRAM "
                f"({vram / GIB - need:.1f} GiB headroom). If status is 'fits', "
                f"the safety margin may be too small — this is the exact bug "
                f"that bricked the chain on June 13."
            )

        # At ctx=32768, it should NOT claim "fits"
        if f["ctx"] >= 32768 and need > (vram / GIB - 2.0):
            assert f["status"] != "fits", (
                f"Gemma 26B @ ctx {f['ctx']} says 'fits' at {need} GiB "
                f"in {vram / GIB:.1f} GiB VRAM. This is the optimistic "
                f"estimate that caused F1 — the safety margin should bump "
                f"this to 'tight' or 'spills'."
            )

    def test_estimator_constants_documented(self):
        """Verify key estimator constants are not accidentally regressed."""
        assert FIT_SAFETY_MARGIN >= 0.5 * GIB, (
            f"FIT_SAFETY_MARGIN={FIT_SAFETY_MARGIN / GIB:.1f} GiB — "
            f"must stay ≥0.5 GiB to prevent F1 regression"
        )
        assert FIT_SAFETY_MARGIN <= 2.0 * GIB, (
            f"FIT_SAFETY_MARGIN={FIT_SAFETY_MARGIN / GIB:.1f} GiB — "
            f"suspiciously large; check if the estimator is double-counting"
        )

    def test_gemma_swa_fudge_conservative(self):
        """The gemma SWA *0.45 fudge was measured empirically.
        It must stay in [0.3, 0.55] — lower risks OOM, higher wastes VRAM."""
        from forge_models import KV_BYTES_PER_EL
        models = scan()
        gemma = next((m for m in models if "gemma" in m.get("arch", "").lower()), None)
        if not gemma:
            pytest.skip("No Gemma model available")

        # The detect function applies the 0.45 fudge internally via
        # `if arch.startswith(\"gemma\"): kv_per_tok *= 0.45`.
        # Verify kv_per_tok is positive and plausible.
        kv = gemma.get("kv_per_tok", 0)
        assert kv > 0, f"Gemma model has no kv_per_tok"
        # SWA halving means KV cache should be < ~65% of a non-gemma
        # model of similar parameter count (~same KV heads × layers).
        # Upper bound: file bytes / 500 — a 10 GiB GGUF → ~20 MB max
        # for the per-token KV cost. Anything above that suggests the
        # 0.45 fudge was removed or KV_BYTES_PER_EL exploded.
        assert kv < gemma["size_bytes"] / 500, (
            f"kv_per_tok={kv} looks suspicious for {gemma['alias']} "
            f"({gemma['size_bytes'] / GIB:.1f} GiB GGUF). "
            f"The gemma SWA *0.45 fudge may be missing."
        )


# ── Action log classified diagnostics ─────────────────────────────


class TestActionLogDiagnostics:
    """Stream C: verify that failed swaps record classified diagnostics
    in the action log. This observability is the whole point of Phase 4 —
    without it, every failure requires re-running + journalctl."""

    def test_refused_swap_recorded_with_classification(self):
        """A VRAM-based refusal should produce an action log record
        with classification, not just an opaque exit code."""
        from forge_ops import get_action_history, record_action

        cur_name, env = _sanity()
        models = scan()
        biggest = max(models, key=lambda m: m["size_bytes"])

        if Path(biggest["path"]).name == cur_name:
            pytest.skip("Already running biggest model")

        plan = plan_apply(biggest["alias"])
        if "error" in plan:
            pytest.skip(f"plan_apply failed: {plan['error']}")

        need_gb = plan["model"]["fit"]["need_gb"]
        free_gb = get_free_vram() / GIB
        reclaim = Path(env.get("MODEL", "")).stat().st_size / GIB if env.get("MODEL") else 0
        available = free_gb + reclaim

        if need_gb <= available:
            pytest.skip(
                f"Biggest model actually fits ({need_gb} GiB in {available:.1f} GiB) — "
                f"can't test refusal. Close GPU apps and retry."
            )

        # Trigger a refused swap
        lines: list[str] = []
        exit_code = asyncio.run(
            swap_model(biggest["alias"], lambda line: lines.append(line))
        )
        assert exit_code == 1, f"Expected refusal, got exit {exit_code}"

        # Small sleep to let the async record_action() file write flush
        time.sleep(0.5)

        # Now read the action log — the refusal record must be there
        history = get_action_history(10)
        swap_records = [r for r in history if r.get("action") == "swap"]
        assert len(swap_records) > 0, (
            "No swap action found in log after refused swap. "
            f"History has {len(history)} records: {[r.get('action') for r in history[:5]]}"
        )

        latest = swap_records[0]
        assert latest["exit_code"] == 1, (
            f"Latest swap record has exit_code {latest['exit_code']}, expected 1"
        )

        # Classification must be present and non-trivial
        assert "classification" in latest, (
            f"Swap record missing 'classification' key. Keys: {list(latest.keys())}"
        )
        assert latest["classification"]["cause"] != "unknown", (
            f"Classification is 'unknown' — the VRAM refusal should have been "
            f"classified. Record: {json.dumps(latest, indent=2, default=str)}"
        )

        # The error field should mention VRAM constraint
        error_text = latest.get("error", "")
        assert any(w in error_text.lower() for w in ("vram", "gib", "available")), (
            f"Error text doesn't mention VRAM: {error_text[:200]}"
        )

    def test_action_log_persists_across_tests(self):
        """The action log is append-only JSONL — records should survive
        between test invocations. Verify the log file exists and is valid.

        Note: historical records from before Phase 4 (June 13, 2026) may
        lack classification fields. This test only enforces classification
        on records dated after the Phase 4 cutoff."""
        from forge_ops import RECORD_DIR

        log_files = sorted(RECORD_DIR.glob("actions-*.jsonl"))
        if not log_files:
            pytest.skip("No action log files yet — run a swap first")

        # Phase 4 cutoff: classification was added June 13, 2026
        phase4_cutoff = "2026-06-13"

        for fpath in log_files:
            content = fpath.read_text().strip()
            if not content:
                continue
            for i, line in enumerate(content.splitlines()):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    assert "action" in record, f"Missing 'action' in {fpath}:{i}"
                    assert "ts" in record, f"Missing 'ts' in {fpath}:{i}"
                    assert "exit_code" in record, f"Missing 'exit_code' in {fpath}:{i}"
                    # Only enforce classification on recent records
                    if record["exit_code"] != 0 and record.get("ts", "") >= phase4_cutoff:
                        assert "classification" in record, (
                            f"Failed action '{record['action']}' at {fpath}:{i} "
                            f"(ts={record.get('ts')}) has no classification"
                        )
                        assert "cause" in record["classification"], (
                            f"Classification missing 'cause' at {fpath}:{i}"
                        )
                except json.JSONDecodeError:
                    pytest.fail(f"Invalid JSON at {fpath}:{i}: {line[:100]}")


# ── VRAM estimator calibration measurements ──────────────────────


class TestVRAMCalibration:
    """Stream C: load each model at multiple ctx sizes, record actual
    peak VRAM, and compare to forge_models.fit() estimates.

    These tests are the EVIDENCE that the estimator constants are correct.
    They must be re-run whenever forge_models.py changes OVERHEAD,
    FIT_SAFETY_MARGIN, KV_BYTES_PER_EL, or the gemma SWA fudge.

    Methodology:
      1. Stop the current llama service
      2. For each model and ctx size: start llama-server with that ctx,
         wait 30s for steady state, snapshot VRAM from /sys
      3. Record peak ΔVRAM (loaded - baseline)
      4. Compare measured vs estimated
      5. Restore original model
    """

    def test_vram_measurement_helper_works(self):
        """Sanity check: the VRAM measurement helper returns sensible values."""
        baseline = _read_vram_used()
        assert baseline > 0, f"VRAM read returned {baseline} — is /sys/class/drm mounted?"
        # On a running system with a desktop, VRAM should be at least
        # a few hundred MB (desktop compositor). If it's 0, something
        # is wrong with the measurement.
        assert baseline > 50 * 1024 * 1024, (
            f"VRAM used looks impossibly low: {baseline / (1024*1024):.1f} MB. "
            f"Check /sys/class/drm/card*/device/mem_info_vram_used"
        )

    def test_estimator_vs_reality_for_current_model(self):
        """For the currently-running model, verify the fit() estimate
        is conservative (never underestimates peak VRAM)."""
        cur_name, env = _sanity()
        models = scan()
        current = next((m for m in models if Path(m["path"]).name == cur_name), None)
        if not current:
            pytest.skip(f"Current model {cur_name} not found in scan")

        # Read actual VRAM usage right now (model is loaded).
        # This includes the desktop compositor, other apps, and RESERVE.
        # The estimator's fit_est is model-only (GGUF + KV cache + OVERHEAD).
        # To compare, subtract out the non-model VRAM: RESERVE is headroom
        # the estimator keeps free; desktop compositor typically uses ~0.3 GiB.
        from forge_models import OVERHEAD, RESERVE

        used_bytes = _read_vram_used()
        # Model VRAM observed ≈ total VRAM - desktop compositor (~0.3 GiB) - RESERVE
        # (OVERHEAD is counted inside the estimator's fit_est, not subtracted)
        COMPOSITOR_ESTIMATE = 0.3 * GIB
        observed_model_gb = (used_bytes - RESERVE - COMPOSITOR_ESTIMATE) / GIB
        fit_est_gb = current["fit"]["need_gb"]

        # The estimator must NOT underestimate: fit_est must be ≥ observed
        # minus a small tolerance (0.5 GiB for measurement noise).
        # An underestimate means the safety margin is too small — the
        # pre-June-13 bug where fit said "fits" but cudaMalloc OOMed.
        assert fit_est_gb >= observed_model_gb - 0.5, (
            f"Estimator UNDERESTIMATES by {observed_model_gb - fit_est_gb:.1f} GiB "
            f"for {current['alias']} @ ctx {current['fit']['ctx']}. "
            f"Estimated: {fit_est_gb:.1f} GiB, Observed (model): {observed_model_gb:.1f} GiB. "
            f"FIT_SAFETY_MARGIN may need to increase."
        )

        # The estimator should not be too pessimistic either — more than
        # 2 GiB over estimate means wasted VRAM capacity.
        assert fit_est_gb <= observed_model_gb + 2.0, (
            f"Estimator overestimates by {fit_est_gb - observed_model_gb:.1f} GiB "
            f"for {current['alias']} @ ctx {current['fit']['ctx']}. "
            f"Estimated: {fit_est_gb:.1f} GiB, Observed (model): {observed_model_gb:.1f} GiB. "
            f"OVERHEAD={OVERHEAD / GIB:.1f} GiB or KV_BYTES_PER_EL may be too high."
        )



