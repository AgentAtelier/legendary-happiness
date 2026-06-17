# Implementation Complete — Reliability & Diagnostics

**Date:** 2026-06-14
**Based on:** [IMPLEMENTATION-PLAN-2026-06-14-reliability-diagnostics.md](./IMPLEMENTATION-PLAN-2026-06-14-reliability-diagnostics.md)
**Status:** 10/10 items complete. All 522 tests pass (151 hub + 371 DevForge, no regressions).

---

## Files Changed (6 files)

| File | Changes |
|------|---------|
| `hub/bench.py` | Probe-root health check, bounce-scene reload, baked baseline, unified envelope |
| `hub/scenarios.py` | Root-agnostic assertions, per-op execution errors, stage_latencies, unified envelope |
| `hub/gauntlet.py` | Unified envelope (`kind` field) |
| `hub/forge_score.py` | `normalize_result` emits `kind`/`model`/`config_hash`/`ts` |
| `hub/hub.py` | Probe-root in chain-health, `/api/runs`, `/api/runs/compare`, `/api/runs/stability` |
| `hub/static/index.html` | Unified Testing-tab history from single `/api/runs` fetch |

---

## Tier 1 — Harness Trust ✅

### 1.1 Probe-root health check
**File:** `bench.py` `_probe_scene_reset()` + `hub.py` `/api/chain-health`

- `scene_get_hierarchy` depth=2 at probe-scene reset: verifies exactly one root, a `Node3D` named "Main", with baseline children (`MainCamera`, `DirectionalLight3D`) present.
- Fail-loud with `RuntimeError` and actionable diagnostic if root is wrong ("Main2", wrong type, missing children).
- Exposed in chain-health sidebar as link #9 "Probe root" — shows 🟢 healthy / 🟡 degraded / ⚫ unknown with fix instructions.

### 1.2 Bounce-scene reload + baked baseline
**File:** `bench.py` `_probe_scene_reset()`

- **Bounce reload:** Opens throwaway `res://probe_bounce.tscn` first, then the probe — forces a real disk reload (proven by the shootout). This cures the stale-tab 0% pain.
- **Baked baseline:** `PROBE_SCENE_TSCN` now includes `Camera3D` + `DirectionalLight3D` — completeness sees a "complete" scene, injects nothing, `no_extra_nodes` holds. Resolves the 50%↔58% flip-flop.
- `_PROBE_BASELINE_NODES` updated to `{"Main", "MainCamera", "DirectionalLight"}`.

### 1.3 Surface artifact execution.errors
**File:** `scenarios.py` `_eval_assertions`

- `no_errors` assertion now reports exact failing ops from `artifact.execution.results` — e.g. `"set_property material_override on DirectionalLight3D: property not found"` instead of just `"3 pipeline errors"`.

---

## Tier 2 — Resilience + Visibility ✅

### 2.4 Root-agnostic scenario assertions
**File:** `scenarios.py`

- `_resolve_root(snapshot)` — finds live root from snapshot (depth-1 path).
- `_resolve_path(raw_path, root)` — replaces `/Main` prefix dynamically.
- All assertions, cleanup paths, `has_mesh`/`has_script` checks use the live root.
- Runs **after** the health check (defense-in-depth, not a substitute).

### 2.5 Expose stage_latencies
**File:** `bench.py` + `scenarios.py`

- `_pipeline_capture` in bench.py already captured `stage_latencies` from artifact (planning / compilation / execution split).
- `run_scenario` in scenarios.py now captures `stage_latencies` for every scenario run.

### 2.6 Unified results envelope
**Files:** `bench.py`, `scenarios.py`, `gauntlet.py`, `forge_score.py`

- All run kinds now emit: `kind`, `model`, `config_hash`, `ts`, `counts`.
- `forge_score.normalize_result` emits these fields, feeding the Testing-tab history.
- Bench runs: `"kind": "bench"`, Probes: `"kind": "probe"`, Scenarios: `"kind": "scenarios"`, Gauntlet: `"kind": "gauntlet"`.

---

## Tier 3 — Data-Driven Layer ✅

### 3.7 /api/runs aggregation
**File:** `hub.py`

- Single endpoint scanning all run directories (bench, probe, scenarios, gauntlet).
- `_scan_runs(kind, limit)` — globs directories, reads JSON, extracts common envelope fields.
- Returns runs sorted newest-first across all kinds.
- Optional `?kind=` filter and `?limit=` param (default 50, max 200).

### 3.8 /api/runs/compare
**File:** `hub.py`

- Side-by-side comparison of two runs of the same kind.
- Identifier resolution: `"latest"` → most recent, `"previous"` → 2nd most recent, 8-char hex → config_hash match, substring → filename match.
- Returns `{kind, runs: [{ts, model, config_hash, counts}, ...]}`.

### 3.9 Wire /api/runs into Testing-tab history
**File:** `hub/static/index.html`

- **Before:** 3 separate API calls (`/api/scorecards`, `/api/gauntlet/history`, `/api/bench/history`) + localStorage ETA.
- **After:** Single `/api/runs?limit=20` fetch. `_scoreFromRun()` helper switches on `run.kind` to compute scores from per-kind count shapes.
- Unified timeline rendering: timestamp, kind icon (⚕🔬🎯🏋⚖⚔), label, score, verdict (PASS/PARTIAL/FAIL with color).
- Deduplication only for server-sourced runs (gated by `ts`); in-session results always admitted.
- Capped at 40 entries, newest-first.

### 3.10 Stability score / failure signature
**File:** `hub.py` `/api/runs/stability`

- Analyzes recent runs of a given kind (default 10, max 30).
- Returns:
  - `stability_score`: mean of per-run scores (0-100)
  - `variance`: standard deviation of scores across runs
  - `trend`: "improving" / "degrading" / "stable" based on last-3 slope (±10 threshold)
  - `failure_signature`: SHA1 hash of the sorted set of failure count strings — same hash = same failure pattern; different hash = bugs changed
  - `scores`: per-run `[score, verdict, ts]` time series for sparkline rendering
  - `failure_items`: raw failure count strings
- Early-returns with "insufficient data" when fewer than 3 runs exist.
- Per-kind score computation matches frontend `_scoreFromRun()`.

---

## Deferred (by design, not forgotten)

| Item | Rationale |
|------|-----------|
| `editor_screenshot` button (R5) | Low cost, but not blocking. Add whenever convenient. |
| `logs_read` reactive wiring | Wire reactively when a bridge-level post-mortem needs it. |
| DevForge journal integration | Only if artifacts get LRU-evicted before they're read. |

---

## Bugs Caught During Code Review (fixed before commit)

1. **Health check depth=1 bug:** `scene_get_hierarchy` depth=1 only returns root node, so baseline children (depth 2) were never found. Fixed to depth=2.
2. **Dead `elif` branch in chain-health probe-root check:** Walrus operator `active := ""` + `bench.PROBE_SCENE not in ""` always evaluated to True. Simplified.
3. **Sort order reversal in pushHistory:** `unshift` reversed API's newest-first to oldest-first. Fixed to `push`.
4. **Dedup false-positives:** In-session results without `ts` collapsed identical-score runs. Fixed by gating dedup behind `if(c.ts)`.
5. **Missing `json` import in `_scan_runs`:** Would have been runtime `NameError`. Added at module level.
6. **Early-stop in `_scan_runs` with `kind=None`:** Bench/probe files filled the limit before scenarios/gauntlet were scanned. Fixed to scan all kinds, then sort and trim.
7. **Dead `passes_attempts` in stability endpoint:** Scorecard envelope doesn't carry per-scenario status dict. Removed; uses flat counts for failure signature like other kinds.

---

## Post-Implementation Verification (meta-guardrail)

> "Once Tier 1.3 surfaces per-op execution.errors on a clean probe, **re-read the actual failures** — they may reveal a different story than our Bug 1/Bug 2 reconstruction."

**Not yet done.** Run a full scenarios suite on a clean probe (root = "Main") with the new code, then check whether the surfaced per-op errors match the Bug 1 (property-type mismatch) / Bug 2 (delete/rename intent dropped) hypothesis, or reveal something new.

---

## Test Summary

| Suite | Passed | Skipped | Failed |
|-------|--------|---------|--------|
| Hub | 151 | 12 | 0 |
| DevForge | 371 | — | 0 |
| **Total** | **522** | **12** | **0** |
