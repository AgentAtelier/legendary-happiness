# Findings & Approach — Reliability & Diagnostics (June 14, 2026)

**This is an outside-perspective writeup.** Per the roadmap's request: what I found,
where I agree/disagree, what I'd do, and the call on Thread C timing.

---

## What I surveyed

I read the full harness surface: `bench.py` (~1000 lines), `scenarios.py` (~800 lines),
`gauntlet.py` (~400 lines), `hub.py` (~700 lines), `forge_ops.py` (~300 lines), plus
`architecture_compiler.py`, `completeness.py`, `artifact_store.py`, `mcp_server.py`
(relevant sections), `tool_catalog.gd` (the godot-ai tool registry), and the historical
data on disk (`hub/data/` — 39 bench runs, 11 gauntlet runs, 2 scorecards, 2 action
logs). I also traced the Main2 root-cause chain through all affected files.

---

## Thread A — Harness trustworthiness

### Agreement with the roadmap

The roadmap's concern about the Main2-cache fragility is correct, but **not for the reason
stated**. The roadmap says the harness is fragile because "one corrupted editor tab silently
poisons every run." I find the situation is actually better than that, with caveats.

### What I found

**The safety guard works.** `bench._probe_scene_reset()` (line 700-715) does an explicit
`editor_state` check: if `current_scene != PROBE_SCENE`, it raises `RuntimeError` and
refuses to touch any nodes. This is the correct defense — it won't silently nuke main.tscn.
The gauntlet and scenarios both call this guard before any write. The shootout has its own
bounce-scene trick (open a different scene first to force scene_open to actually reload).

**The Main2 root-cause story checks out.** Hardcoding `/root/Main` in two places
(`completeness.py:_find_root` and `architecture_compiler.py:_resolve_parent`) meant that if
the live scene root was ever "Main2" (from a prior Godot auto-suffix), auto-injected
camera/light nodes targeted a non-existent path. Godot materialized a fresh "Main" to
satisfy the reference, which conflicted with the existing "Main2" — hence the corruption.
Both places now resolve the root dynamically from the live scene (`scene.root.path` /
`_collect_nodes` depth-2 `/root/<RootName>` scan). The fix is sound.

**But there's an unfixed fragility.** The probe scene root is assumed to be "Main" — that
name is hardcoded in:
- `PROBE_SCENE_TSCN` (bench.py line 633): `[node name="Main" type="Node3D"]`
- `PROBE_EXPECTED` (bench.py line 645): `{"Hero", "Eye", "Body"}` — but these are name checks,
  not path checks, so they're root-agnostic
- Scenario assertions (scenarios.py): `{"path": "/Main/TestCube"}` etc. — these ARE
  root-specific. If the disposable scene ever ends up with a non-"Main" root (Godot
  auto-suffixes root nodes too), ALL 12 scenarios will fail with "NOT found in scene."

Also: the probe reset clears non-baseline children by name match against `_PROBE_BASELINE_NODES`
(`{"Camera3D", "Ground"}`), but those only exist in the *real* main.tscn, not the disposable
probe. The disposable probe is a bare `Node3D` root — if completeness injects a camera/light
(correct behavior for a bare scene), those get deleted on the next reset. This is fine for
scenarios (each scenario runs in a freshly-reset scene) but means the probe state after a
scenario suite run is NOT the same as after a gauntlet run (gauntlet resets between each
prompt and restores at end; scenarios reset ONCE at suite start and rely on per-scenario
cleanup deletes).

### My call

The harness is **trustworthy enough to use, but not trustworthy enough to automate without
human oversight.** The safety guard prevents catastrophic mistakes. The dynamic root
resolution prevents the Main2 class of bugs. But the `/Main`-specific assertions in scenarios
mean a single Godot auto-suffix event on the probe root poisons the entire scenario suite
with misleading failures, and there's no automated detection of this condition.

**Specific hardening I'd do (in order):**

1. **Make scenario assertions root-agnostic.** Instead of `"path": "/Main/TestCube"`, use a
   root resolver that queries `scene_get_hierarchy` first, finds the actual root path, and
   constructs assertion paths dynamically. This is ~30 lines of code, zero risk, and elimates
   the entire class of "Godot renamed my root" failures.

2. **Add a probe-root health check at suite/gauntlet start.** Before running anything, call
   `scene_get_hierarchy` depth=1, confirm exactly one root node exists and it's a `Node3D`
   (not a stale Main2 remnant). If it's wrong, emit a clear diagnostic ("Probe root is
   'Main2', not 'Main'. Close the probe tab in Godot and re-open it.") and refuse to run.

3. **Use the bounce-scene trick in `_probe_scene_reset()`.** The shootout already does this:
   open a *different* scene first, THEN open the probe scene. This forces Godot to actually
   reload from disk. Currently the probe reset writes the .tscn file THEN calls scene_open,
   but if the probe is already active, scene_open is a no-op and the in-memory state (which
   may have stale nodes) persists. Add a bounce via a second disposable scene
   (res://probe_bounce.tscn) before each reset.

4. **Question: is "% score" even the right metric?** The roadmap asks this in "Things to
   actively challenge." I find the scenario pass/fail is useful for regression detection
   ("did this code change break light_create?") but the percentage is misleading. A 58% score
   where all failures are the same root cause (e.g. stale Main2 cache) is very different from
   58% with 5 distinct failures. I'd replace the single percentage with a **failure signature**
   — a hash of which specific assertions failed — so repeated runs can be compared for
   *stability* rather than *score*. A stable 58% is actually better than an unstable 92%.

---

## Thread B — Data the project emits that we are NOT using

### Agreement with the roadmap

The roadmap's candidate list is accurate but misses the most actionable insight: **the data
we're not using is primarily in the artifact, not in separate tools.** The highest-value
unused diagnostic isn't `editor_screenshot` or `triage_errors` — it's the per-operation
execution results already inside every `read_artifact` response.

### What I found

**The artifact's `execution` block is treasure.** Every `apply_spec` stores a full
`ExecutionResult` in the artifact store. The `build_summary()` in artifact_store.py extracts
only a tiny fraction: `applied`, `operations_total`, `error_count`, and file paths. The
artifact's `execution` dict contains:

```
execution:
  success_count: int        # ops that actually executed
  error_count: int          # ops that failed
  errors: [{op, message}]   # per-op error details with the EXACT op that failed
  results: [{op, status}]   # per-op status (success/fail/skip)
  duration_ms: int          # bridge round-trip time
  scene_before: dict        # full scene tree BEFORE the build
  scene_after: dict         # full scene tree AFTER the build
```

This is what turns "the cube scenario failed" into "the cube scenario failed because
set_property material_override on a DirectionalLight3D caused an atomic rollback, and
here are the 3 ops that were in the batch." We already use this in the devforge.execute
probe, but only for the fixed "Hero/Eye/Body" prompt.

**The artifact also has stage-level timing:**

```
stage_latencies:
  architecture_planning: int   # ms for the LLM to produce a delta
  compilation: int             # ms for compiler + validator
  execution: int               # ms for the bridge round-trip
plan_retries: int              # how many times the planner retried
repair_count: int              # how many repair passes ran
```

This is the performance dashboard waiting to happen. We currently only use a single
`apply_ms` metric. Splitting it into planning/compilation/execution buckets would
immediately show whether slowness is "the model is slow" (planning) vs "the bridge
is slow" (execution) vs "the validator is rejecting things and triggering retries"
(high plan_retries).

**The DevForge journal exists but is completely unused.** `devforge/journal/journal.py`
tracks every tool call with timing and outcome. It reports `by_tool` and `recent_tools`
but nothing reads this data. It's a perfect fit for the "what commands did the model
actually issue?" question — which is currently answered only by reading the artifact.

**The historical data on disk is rich but inert.** 39 bench runs, 11 gauntlet runs.
Each is a self-contained JSON file. There's no aggregation, no trend view, no way to
answer "did the June 14 engine changes improve gauntlet coverage?" without manually
diffing two JSON files. The scorecards have a comparison endpoint (`/api/scorecards/compare`)
but only for two models — no time-series comparison for the same model across config changes.

**godot-ai tools we've never wired:**

| Tool | What it gives us | Diagnostic value |
|------|-----------------|------------------|
| `editor_screenshot` | Pixel-level ground truth of what's on screen | Very high for visual verification, low for automation (needs vision model) |
| `logs_read` | godot-ai's own error log | High — catches bridge-level failures that DevForge never sees |
| `test_run` | GUT unit test execution in-editor | Medium — would catch Godot-side regressions, but our current unit suites run outside Godot |
| `signal_map` | Every signal connection in the scene | Low — useful for debugging signal wiring but rare |
| `triage_errors` | Structured error diagnosis | Medium — exists but not integrated into the hub workflow |

### My call on what's signal vs. noise

**Signal (wire these first):**
1. **Artifact `execution.errors`** — the per-op failure details. Currently the scenarios
   only check `artifact.error_count > 0`. They could check *which specific ops failed*
   and provide a more precise diagnostic. This is a ~20-line change.
2. **Artifact `stage_latencies`** — expose planning/compilation/execution breakdowns in
   the hub UI, so performance regressions are visible immediately.
3. **Bench/probe/gauntlet time-series view** — a simple `/api/trends?dataset=gauntlet&metric=avg_coverage`
   that returns the last N runs with timestamps, so the hub UI can draw a mini sparkline.

**Noise (skip for now):**
- `editor_screenshot` — requires a vision model to interpret, adds latency, and the
  scene hierarchy already tells us what was built.
- `test_run` — our Python unit suites cover the same ground.
- `signal_map` — too niche; only valuable when debugging a specific signal wiring bug.

**Maybe later:**
- `logs_read` — one `fetch → display` endpoint on the hub would be useful for
  post-mortems when something breaks, but wire it reactively (add it when you need it).
- The DevForge journal — if the artifact already has per-op results, the journal is
  redundant. If the artifact gets evicted (LRU cap of 50), the journal is the durable
  fallback. Decide after a week of use.

---

## Thread C — Is it time to instrument for the future?

### My call: **Yes, but only the lightweight parts.**

The system is stable enough that adding instrumentation won't be wasted on a moving
target. The 371 DevForge tests + 151 hub tests pass. The scenario suite has a known
state (some failures, but understood failures). The gauntlet produces consistent
coverage numbers.

But "lightweight" means: **add a single unified results schema, not a new subsystem.**
Right now bench runs, probe runs, gauntlet runs, scenario scorecards, and action logs
all write different JSON schemas to different directories. The simplest instrumentation
is to unify them under one schema with a shared `kind` field, so any query
("show me the last 3 runs of each kind") is a single file glob + filter, not five
different endpoints with five different parsers.

### Concrete instrumentation plan (3 changes, ~100 lines total):

1. **Standardize the results envelope.** Every run (bench, probe, gauntlet, scenario,
   shootout) gets a common header:
   ```json
   {
     "kind": "gauntlet",
     "ts": "2026-06-14 19:01:15",
     "model": "qwen3-14b-q6-k",
     "template": "instruct",
     "config_hash": "d5b393a2",
     "counts": {"pass": 5, "fail": 2, "skip": 0, "error": 0},
     "...kind-specific fields..."
   }
   ```
   This is backward-compatible (add fields, don't remove). The existing endpoints
   continue to work.

2. **Add a `/api/runs` aggregation endpoint.** One route that returns the last N runs
   across all kinds, with the common fields, sorted by time. The frontend gets a
   mini-dashboard: "Last gauntlet: 67% coverage (qwen3-14b). Last scenario suite:
   8/12 pass (qwen3-14b). Last probe: 12 works / 3 degraded / 1 broken."

3. **Add a `/api/runs/compare` endpoint.** Given two config_hashes (or two timestamps),
   return a side-by-side diff. This replaces the manual "diff two JSON files" workflow.
   The scorecards already have a compare endpoint — generalize it.

### What I would NOT do (yet):

- **No time-series database.** JSON files on disk are fine for the volume we have
  (~50 runs total). Postgres/Prometheus/InfluxDB is premature for a single-user tool.
- **No automated alerts.** The user is watching the hub UI. A red "broken" probe is
  more actionable than an email.
- **No permanent AI/daemon.** The hub is already a FastAPI server running on systemd.
  It can serve trends without any new processes.

---

## Where I disagree with the roadmap

1. **"The Main2-cache incident suggests the harness is fragile."** I disagree with the
   framing. The safety guard (`editor_state` check before any node deletion) means the
   harness is *safe* — it will loudly refuse to run rather than silently corrupt. The
   fragility is in the *setup step* (the editor tab must be on the probe scene), not
   in the *harness logic*. This is a UX problem (the hub should check this and tell the
   user what to do), not a design problem.

2. **"Scenario-assertions: maybe they should converge with the gauntlet coverage model."**
   I think these serve different purposes and should stay separate. Scenarios test
   specific known failure modes (did light_create work this time?). The gauntlet tests
   capability breadth (can it build nested entities? signal connections?). Converging
   them would lose the precision of the scenario assertions without gaining the breadth
   of the gauntlet.

3. **"Whether '% score' is the metric that matters."** Strong agree. Variance is more
   important than absolute score for this system. A scenario that passes 4/5 times is
   a different problem than one that never passes. The roadmap frames this as an open
   question; I'd answer it: **replace pass_rate with a stability score** (passes ÷
   attempts across the last N runs) and surface variance explicitly.

---

## What I'd do next (implementation order)

### Immediate (today — high leverage, low risk)

1. **Make scenario assertions root-agnostic** — resolve `/Main` dynamically from the
   live scene. Eliminates the "Godot renamed my root" failure class in 30 lines.

2. **Add probe-root health check** — at suite/gauntlet start, verify the probe root
   is a single `Node3D` and warn if not.

3. **Expose artifact execution errors in scenario results** — when a scenario fails,
   include *which ops failed* from `artifact.execution.errors`, not just the error count.

### Short-term (this week — starts the data-driven transition)

4. **Standardize the results envelope** — add `kind`/`model`/`config_hash` common
   fields to all run outputs. Backward-compatible.

5. **Add `/api/runs` aggregation endpoint** — one route to see the last N runs
   across all kinds.

6. **Expose artifact `stage_latencies` in the hub UI** — a timing breakdown row
   in the probe detail view (planning: Xs, compilation: Yms, execution: Zms).

### Medium-term (next week — if the above proves useful)

7. **Bounce-scene trick in probe reset** — make `_probe_scene_reset()` force a
   real disk reload every time.

8. **Time-series comparison** — `/api/runs/compare` with sparkline data for the
   frontend.

9. **Failure signature instead of pass_rate** — hash the specific failing
   assertions to detect "same failure" vs "new failure."

### Deferred

10. **`editor_screenshot` integration** — needs a vision model; revisit when
    there's a concrete debugging need it would solve.
11. **Automated regression alerts** — only after we have enough historical data
    to know what "normal" looks like.

---

## Summary

The system is in better shape than the roadmap suggests. The safety guard works. The
Main2 fix is correct. The probe chain is already producing rich data (14 probes across
5 layers, 3-tier verdicts, artifact detail). The two highest-value unused data sources
are already collected and just need to be surfaced: (1) per-op execution errors in the
artifact, and (2) stage-level timing. The instrumentation I'm recommending is
unification of what already exists, not a new collection system.

**My Thread C call: Yes, instrument — but instrument by surfacing what's already
collected, not by adding new collection.**
