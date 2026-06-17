# Forge Hub — Exhaustive Audit Brief & Dead-Code Inventory (2026-06-14)

**Purpose.** Hand a fresh AI everything needed to run an exhaustive, thorough audit of the
Forge hub after the "testing/look rework," AND to recover the functionality that the rework
left orphaned. Written to be self-contained: paths, line numbers, endpoints, data shapes,
evidence, constraints, and a recommended investigation order are all inline.

> Read this top to bottom once before touching anything. Several problems are entangled
> (the Main→Main2 corruption, scenario writes not landing, and the missing kitchen are likely
> the same root cause). Do not "fix" one in isolation without checking the others.

---

## 0. Orientation — repo, how to run, hard constraints

**Tree:** `/home/mrg/dev/games/Forge/`
- `hub/` — the ops panel (this audit's subject). FastAPI `hub.py` (~1380 lines) + a single
  hand-written `static/index.html` (~1850 lines, vanilla JS, **no build step**). Own venv at
  `hub/.venv`. Runs as `systemctl --user` service **`forge-hub`** on `127.0.0.1:8003`
  (loopback only; Host-header allowlist; `X-Forge-Hub` header required on POST).
- `hub/forge_score.py` — NEW. Pure, unit-tested scoring (`score_to_verdict`,
  `normalize_result`, `eta_from_durations`).
- `hub/bench.py`, `hub/scenarios.py`, `hub/gauntlet.py`, `hub/shootout.py` — the four test
  engines. `hub/forge_env.py`, `hub/forge_models.py`, `hub/forge_ops.py` — shared stack libs.
- `devforge_review_package/devforge/` — DevForge (the LLM→ops compiler). `spatial/` holds the
  kitchen/layout engine (`compiler.py`, `layout_planner.py`, `lexicon.py`, `anchors.py`).
- Godot project: `/home/mrg/dev/games/rpg/` — scenes in `scenes/`, the real one is
  `scenes/main.tscn` (uid `uid://dh38xgvfrfn7k`, root node **"Main"**).

**Run things:**
- Tests: `cd /home/mrg/dev/games/Forge/hub && .venv/bin/python -m pytest tests/ -q`
  (152 passed / 11 skipped as of this writing). `@live` tests are skipped by default; add
  `-m live` to include (they mutate the running system).
- Restart hub after editing `hub.py`: `systemctl --user restart forge-hub`
  (the frontend `index.html` is served from disk per request — no restart needed for JS/CSS).
- Hub serves the page at `GET /` (see `hub.py:172`, `FileResponse` no-cache).
- Stack health snapshot: `curl -s -H "Host:127.0.0.1:8003" http://127.0.0.1:8003/api/chain-health`

**HARD CONSTRAINTS (do not violate):**
1. **Odysseus (`~/dev/ai/odysseus`) and godot-ai (`~/dev/games/rpg/addons/godot_ai`) stay
   VANILLA.** Never patch their source. Adapt only DevForge, the hub, `stack.env`/`forge-model`,
   or Odysseus *config* (presets.json, app.db).
2. `stack.env` + `forge-model` are the single source of truth; the hub shells out to the
   `stack` CLI and must never reimplement stack logic.
3. Hub binds 127.0.0.1 only. Work email `d.ottavi@wbe.lu` must NOT appear in git history
   (this tree is currently NOT a git repo).
4. Restart `forge-devforge` after any prompt/template/grammar/context change.
5. Use qwen3 for build/agent work. Verify with evidence (run it), never claim done without
   running.

---

## 1. PROBLEM INVENTORY (ranked by severity)

### P1 — CRITICAL: builds leave the scene root renamed "Main" → "Main2" (recurring corruption)
**Symptom (user-reported, corroborated):** running a gauntlet (and likely scenario) build
renames the open scene's root node from `Main` to `Main2`. This has corrupted `main.tscn`
across multiple past sessions and is the root cause of "parent /root/Main not found" failures.

**Evidence on disk:**
- `hub/data/gauntlet/gauntlet-20260614-084446.json` — the persisted run's node paths are all
  under `/Main2/...` (`/Main2/LvlA/LvlB/...`, `/Main2/DirectionalLight`). A gauntlet run built
  into a Main2-rooted scene.
- The spatial compiler **hardcodes the root**: `devforge_review_package/devforge/spatial/compiler.py:75`
  → `root_path = "/root/Main"` (also `:393` default `"/root/Main"`). Any Main2 state ⇒ the
  kitchen build targets a non-existent path ⇒ silent failure. **This links P1 and P4 (kitchen).**

**Mechanism — UNCONFIRMED, trace it:** No `Main2` literal exists in the hub `.py` (confirmed by
grep). The rename is almost certainly a **Godot side effect**: when a build creates a *second*
node named `Main` (e.g. the planner emits a root/parent named "Main" while a "Main" already
exists), Godot auto-suffixes the new sibling to `Main2`; subsequent ops then nest under it.
Alternative: probe/main scene confusion (`bench.py` opens `probe.tscn` whose root is also named
`Main` — see `PROBE_SCENE_TSCN` at `bench.py:633`, root `[node name="Main" type="Node3D"]`).
**Investigate:** capture the exact `batch_execute` op list of a gauntlet run and find the op
that creates/renames a `Main`/`Main2` node; check whether `_probe_scene_reset` (`bench.py:678`)
and its safety guard (`bench.py:711`, refuses if active scene ≠ `res://probe.tscn`) actually
prevent builds from hitting `main.tscn`.

**Fixes to consider (all in adaptable code):** (a) make the spatial compiler + probe logic
**root-agnostic** — resolve the actual scene root name at runtime instead of hardcoding "Main";
(b) ensure every test engine builds into a disposable scene, never `main.tscn`; (c) detect and
refuse to operate when root ≠ expected.

### P2 — CRITICAL: scenario writes don't land in the open scene (scenarios stuck ~58%)
**Symptom:** latest scenario scorecard (`hub/data/scorecards/qwen3-14b-q6-k-d5b393a2.json`,
ts 2026-06-14 18:54:25) = **7 pass / 5 fail / 0 error = 58.3%**. In ALL five failures the scene
is frozen at the SAME six nodes: `['/Main', '/Main/Camera3D', '/Main/DirectionalLight',
'/Main/Ground', '/Main/OldName', '/Main/ToDelete']`. Nothing the scenarios build appears:
- `light_create` → `/Main/TestSun` NOT found
- `script_attach` → `/Main/ScriptedCube` NOT found
- `node_rename` → `/Main/NewName` NOT found
- `small_room` → `/Main/WallFront` (and all walls) NOT found
- `node_delete` → `/Main/ToDelete` STILL exists (delete had no effect)

**Reading:** this is not a *scoring* weakness — it's that apply_spec/godot-ai mutations are
**not reaching the scene the assertions read** (or failing silently). Note the run is
**non-deterministic vs the prior 66.7% run** (earlier `node_rename` DID create `NewName`), which
points at scene-targeting/root state (P1) rather than a stable logic bug. **Likely same root as
P1.** Investigate: does `scenarios.run_suite` build into `main.tscn` or a disposable scene? Where
do its ops land vs where assertions read? (`hub/scenarios.py`; assertion engine reads via
godot-ai `scene_get_hierarchy`.)

### P3 — scenarios run against the REAL main.tscn and pollute it
`/Main/OldName` and `/Main/ToDelete` are **live right now** in `main.tscn` (verified via
godot-ai `scene_get_hierarchy`) — leftovers from failed `node_rename`/`node_delete` scenarios
whose cleanup didn't remove them. Test engines must use a disposable scene (the gauntlet/probe
have `probe.tscn`; scenarios apparently don't). Clean baseline should be:
`Main / Camera3D / Ground / DirectionalLight`.

### P4 — the kitchen was never built (NOT a spatial-system failure)
Live `main.tscn` has no kitchen. The only live attempt failed on the Main2 corruption
("parent /root/Main not found" — see P1's hardcoded root). After the corruption was fixed it
was never re-run. The spatial pipeline (`devforge/spatial/`) is unit-tested and compiles a valid
kitchen deterministically; it just never executed against a clean editor. To build it live: set
`DEVFORGE_PLANNER=layout`, restart `forge-devforge`, run a "build me a kitchen" apply_spec, and
verify nodes land — but **fix P1's hardcoded `/root/Main` first** or it will fail again.

### P5 — health bar: false-down FIXED; some states still look off
**FIXED this session** (`hub.py` chain_health): DevForge + godot-ai are MCP servers that answer
**404 on `/` while healthy**; the check treated non-200 as "down." Now liveness uses an `alive`
flag (got any HTTP response). Verified live: devforge `healthy template=chatml`, godot-ai
`healthy connected`.
**Still potentially "off" (user says checks still seem off) — enumerate for the audit:**
- `ody-llama`, `ody-devforge`, `mcp-keyword` → `unknown` ("Odysseus not running"). Correct
  while Odysseus docker is down, but may *look* broken. Consider rendering "unknown/paused"
  distinctly from "down."
- `config-doc` → `stale`: real drift — "reasoning-budget still in LLAMA_BASE_ARGS (doc says
  removed)" + "LLAMA_ARG_CHAT_TEMPLATE_KWARGS missing (doc says needed for thinking)". Ties to
  memory notes on llama sampling/thinking. Reconcile `stack.env` vs `forge-stack-chain.md`.
- Get the user to point at the *specific* element that "seems off" — could be the collapsed
  mini-chain rendering, a dot color, or the warnings list styling under the new theme.
- chain_health source: `hub.py:521`+. Per-link render JS + CSS: `static/index.html` health
  sidebar (`#health-sidebar` CSS ~line 114; render in the health JS).

### P6 — hub tests mutate LIVE state (swap to "test-model")
`tests/test_hub_api.py::TestSwapEndpoint::test_valid_fragment_returns_job_id` POSTs
`/api/swap {"fragment":"test-model"}` against `TestClient(app)`, which shares the real
filesystem/stack — it triggered a real swap attempt logged in chain-health
(`Last swap to test-model at 2026-06-14 18:44`). Same for `/api/run` doctor etc. **Tests should
not perturb the running stack.** Mock the swap path or assert on validation without dispatching.

---

## 2. REGRESSIONS introduced by the rework (functionality the user misses)

The rework unified four testing tabs into one "Testing" tab (faceted runner). It **kept the four
old tab bodies + their JS in `index.html` but removed them from the nav** (hidden/unreachable —
~600 lines of dead code). In doing so it dropped real capabilities:

| Lost capability | Old home | Detail / endpoint | User words |
|---|---|---|---|
| **Persistent history** | all 4 tabs | new Testing tab only keeps in-session `_thist` (resets on reload); old tabs loaded from `/api/bench/history`, `/api/scorecards`, `/api/gauntlet/history`, `/api/shootout/history` | "only able to see the last test result, no history" |
| **At-a-glance scoreboard / model compare** | Score tab | `cmpA`+`cmpB` inputs + `cmpBtn` → `GET /api/scorecards/compare?model_a=&model_b=` (`index.html:1134`) | "the score board that let me see at a glance… is gone" |
| Full scrolling log output | bench/score/shootout/gauntlet `term*` panes | new status strip shows only the **last** line | — |
| Probe rollup + Quick Health (<10s, no LLM) | Test Bench probes | `/api/bench/probe`, `probeQuick`/`probeFast`/`probeLlama`/`probeDevforge` | — |
| Tool-call-probes-only run | Score tab | `scoreTool` (`runScore(ids, runTools)`) | — |
| Shootout pre-flight check | Shootout tab | `shootoutCheck` → `/api/shootout/preflight` | — |
| Test bundles | Test Bench | `bundleSelect` + `/api/bench/bundle` | — |
| Dedicated shootout progress bar/phase | Shootout | `shootoutBar`/`shootoutPhase` + `handleShootoutMarker` stream markers | — |

**Recommendation:** the new Testing tab should (1) load persistent history per suite on tab open
(call the existing `/api/*/history` endpoints, normalize into the unified scorecard chip row),
and (2) restore the compare scoreboard (a faceted "Compare two models" view over
`/api/scorecards/compare`). These are additive to the existing `runTesting` flow in the
"Unified Testing tab" `<script>` block at the bottom of `index.html`.

---

## 3. DEAD-CODE INVENTORY — exact functionality still in index.html (hidden, removed from nav)

These four `<div id="tab-…">` bodies + their JS remain in `static/index.html` but are unreachable
(no nav button). Listed so nothing is lost when they are removed or features are migrated. The
nav→branch wiring for them was deleted (`index.html` nav click handler), and `setBusy()`
(`index.html:531`) still lists their button ids in its disable selector (harmless but stale).

### `#tab-bench` — "Test Bench"
- **Buttons/els:** `benchAll` (Run all), `benchFast` (Run fast), `bundleSelect`+`benchBundle`
  (Run bundle), `benchShootoutRun` (⚔ Shootout: all), `benchShootoutRunOne` (⚔ Shootout:
  current), `benchHist`, `benchTable`, `termBench`. Probe sub-panel: `probeAll`, `probeLlama`,
  `probeDevforge`, `probeFast` (no-LLM), `probeQuick` (⚡ Quick Health <10s), `probeRollup`,
  `termProbe`, `probeResults`, `benchShootout`/`benchShootoutSummary`.
- **JS:** `loadBenchTests()` (887), `runBench(ids)` (903), `loadProbes()` (932),
  `runProbe(ids)` (939), `renderProbes(run)` (960), `loadBenchShootout()` (1002).
- **Endpoints:** `/api/bench/tests`, `/api/bench/run`, `/api/bench/bundle`, `/api/bench/history`,
  `/api/bench/probes`, `/api/bench/probe`, `/api/bench/probe/history`, `/api/bench/probe/{ts}`.

### `#tab-score` — "Score"
- **Buttons/els:** `scoreAll` (all scenarios), `scoreFast` (geometry only), `scoreTool`
  (tool-call probes only), `scoreBoth` (scenarios+tools), `cmpA`/`cmpB`/`cmpBtn` (compare),
  `scoreSummary`, `termScore`, `scoreTable`, `scoreHistory`.
- **JS:** `loadScoreHistory()` (1066), `runScore(ids, runTools, title)` (1093),
  `cmpBtn` handler (1134).
- **Endpoints:** `/api/scenarios`, `/api/scenarios/run`, `/api/scorecards`,
  `/api/scorecards/compare`.

### `#tab-shootout` — "Shootout"
- **Buttons/els:** `shootoutRun` (all models), `shootoutRunOne` (current only), `shootoutCheck`
  (pre-flight), `shootoutProgress`/`shootoutBar`/`shootoutPhase`, `shootoutResults`,
  `shootoutHistoryTable`/`Body`.
- **JS:** `renderShootoutPhase()` (491), `loadShootoutHistory()` (1281),
  `renderShootoutHistory()` (1296), `loadShootoutDetail(ts)` (1332),
  `renderShootoutCompact(d,mode)` (1344), `renderShootoutResults(d)` (1424),
  `runShootout(modelFilter)` (1512), plus `handleShootoutMarker` stream hook.
- **Endpoints:** `/api/shootout`, `/api/shootout/preflight`, `/api/shootout/history`,
  `/api/shootout/{ts}`, `/api/shootout/{ts}/log`.

### `#tab-gauntlet` — "Gauntlet"
- **Buttons/els:** `gauntletSet` (set selector), `gauntletRun` (Run set), `gauntletSummary`,
  `termGauntlet`, `gauntletResults`, `gauntletHistory`.
- **JS:** `loadGauntletSets()` (735), `runGauntlet()` (743), `renderGauntlet(run)` (765),
  `loadGauntletHistory()` (789).
- **Endpoints:** `/api/gauntlet/sets`, `/api/gauntlet/run`, `/api/gauntlet/history`,
  `/api/gauntlet/{ts}`.

**Note — name collision risk:** the new module defines `renderScorecard` (`index.html:1771`).
Verify no old function shares a name (grep showed only one `renderScorecard`, but audit for any
duplicate `function` declarations when removing dead code; last-declared wins silently).

**How the new faceted runner maps the old tabs** (for migration): Test Bench → Suite **Health**;
Score → Suite **Scenarios** (+ the lost compare/tool-probe features); Gauntlet → Suite
**Gauntlet**; Shootout → Target **Compare**. New routing/adapters live in the
"Unified Testing tab" `<script>` block (`SUITES{}`, `runTesting`, `streamTesting`,
`renderScorecard`, `pushHistory`, ETA via localStorage).

---

## 4. Unified data shapes (so the audit can reason about results)

- **Unified scorecard** (frontend `renderScorecard` + Python `normalize_result`):
  `{suite, target, label, score:0-100, verdict:"pass"|"partial"|"fail",
    metrics:[{label,value,good:bool}]}`. Verdict bands: ≥90 pass, ≥60 partial, else fail
  (`forge_score.score_to_verdict`).
- **Scenario scorecard file** (`data/scorecards/*.json`):
  `{ts, model, template, config_hash, scenarios:[{scenario_id, category, status, ms,
    assertions:[{status, assertion, message}], errors, cleanup_errors}],
    summary:{pass,fail,error,total,pass_rate,total_ms,avg_ms}}`.
- **Gauntlet run file** (`data/gauntlet/gauntlet-*.json`): per-prompt `results[]` each with
  `coverage` + `verdict` ∈ {full,partial,broke}; `summary:{full,partial,broke,avg_coverage}`.
- **Bench history** (`/api/bench/history` → `runs[]`): `{file, ts, model, counts:{pass,fail,
  error,…}, failed:[ids]}`.
- **chain-health** (`/api/chain-health`): `{ts, links:[{id,label,port,status,detail,fix}],
  warnings:[…], last_swap, ms}`. `status` ∈ healthy|degraded|stale|down|unknown.

---

## 5. Recommended investigation order

1. **P1+P2 together** (same likely root). Run ONE gauntlet prompt and ONE scenario with full
   `batch_execute` op-logging; capture (a) the active scene + root name before/after, (b) every
   op's target path, (c) where the "Main2" or missing-node divergence appears. Confirm whether
   engines build into `main.tscn` or a disposable scene.
2. **Make root handling robust** — de-hardcode `/root/Main` (`spatial/compiler.py:75,393`);
   ensure all engines use a disposable scene; add a guard that refuses to mutate `main.tscn`.
3. **Clean P3 pollution** — delete `/Main/OldName`, `/Main/ToDelete` from `main.tscn`; restore
   clean baseline; back it up.
4. **P4 kitchen** — only after 1–2: set `DEVFORGE_PLANNER=layout`, restart forge-devforge,
   build a kitchen, verify nodes land; this is the acceptance demo.
5. **P6** — neutralize live-mutating tests.
6. **Regressions (§2)** — restore persistent history + compare scoreboard in the Testing tab.
7. **P5 remainder** — get the user to point at the exact "off" element; reconcile config-doc drift.

## 5b. VERIFICATION of the first fix round (2026-06-14, live re-run)

A fix round landed (5 files; compiler root_path param, engine root resolution, scenarios→probe
scene, swap test skipped, frontend history/compare). Live re-verification of the actual behavior:

- **P3 — CONFIRMED FIXED.** Ran 3 scenarios live; editor restored to `main.tscn`, root stayed
  "Main", **no new pollution**. Scenarios now build in the disposable probe scene. The
  Main2-corruption-via-scenarios vector is closed. (Gauntlet already used probe → also isolated.)
- **P2 — NOT FIXED (still the core problem).** Re-ran `light_create`, `node_delete`, `small_room`
  live → **0/3 pass** (`data/scorecards/qwen3-14b-q6-k-d5b393a2.json`, ts 19:29:59). Evidence:
  every scenario reports **"Zero pipeline errors" but the requested nodes are absent**
  (`light_create` after-scene = `['/Main']`, no `TestSun`). Two distinct sub-bugs:
  1. **apply_spec succeeds-but-builds-nothing/wrong-names:** zero errors, yet requested nodes
     (`TestSun`, walls, etc.) never appear; the nodes that DO appear are generic
     (`DirectionalLight`, `MainCamera`) — DevForge isn't honoring the prompt's node names, OR
     the build isn't landing and the snapshot is mistimed. **Trace apply_spec's emitted
     batch_execute ops vs the scenario's expected names; this is upstream in DevForge, not the hub.**
  2. **No per-scenario reset:** nodes accumulate across scenarios within one suite run (probe is
     reset ONCE at suite start, not between scenarios). `scenarios.run_suite` should reset the
     probe scene (or delete created nodes) **between** scenarios, like the gauntlet does per-prompt.
- **P1 — code correct, NOT live-verified.** compiler/engine now resolve the root dynamically
  (good, kitchen will target the real root), but the Main→Main2 *creation* mechanism (Godot
  auto-suffix when a build emits a 2nd "Main") is not prevented — only isolated to probe now.
  The kitchen was NOT built this round; building it is still the acceptance demo (do it after
  confirming P2, or it'll greybox into an empty/odd scene).
- **Residual:** `main.tscn` still contains pre-fix pollution `/Main/ToDelete`, `/Main/OldName`
  (cosmetic; delete them for a clean baseline).
- **§2 frontend** reviewed as code (history load + compare wired); the compare reuses the
  hidden old-score-tab `#cmpA`/`#cmpB` inputs — functional but worth tidying. Not live-verified.

**Net:** the round fixed scene *discipline* (P3, real) but the headline scenario failures (P2)
remain and are the priority. P2 is a DevForge apply_spec / snapshot-timing investigation.

## 5c. ROUND 2 VERIFICATION — REGRESSION + TRUE ROOT CAUSE FOUND (2026-06-14, live)

Round 2 changed 2 files (scenarios.py per-scenario `_probe_scene_reset`; engine.py dedup vs
live scene). **Live full-suite re-run = 8% (1/12)** — a SEVERE REGRESSION from the 58% baseline
(`data/scorecards/qwen3-14b-q6-k-d5b393a2.json`, ts 19:54:27). Even `cube_create` now fails.

**THE TRUE ROOT CAUSE (P1 == P2, finally pinned):** the build lands every node under a
**newly-created `/Main2` root**, not the existing `/Main`. Direct evidence — `cube_create`:
`/Main/TestCube NOT found. Present: ['/Main2', '/Main2/DirectionalLight', '/Main2/MainCamera',
'/Main2/TestCube']`. The nodes ARE built; they're under `Main2`. Assertions (and the user) look
at `/Main` ⇒ "fail". So:
- **P2 ("scenarios don't build") was always P1 ("Main→Main2").** The two are ONE bug. Every
  prior "writes don't land / zero errors but nothing built" symptom = nodes built under Main2.
- **Mechanism:** `architecture_compiler.py:112` → `if scene.has_path("/root/Main"): return
  "/root/Main"`, and `_resolve_parent` falls back to `/root/Main` / `root_path`. In the EDITOR
  the scene root is addressed as `/Main`, not the runtime `/root/Main`; the arch path targets a
  `/root/Main` that the bridge then materializes as a fresh top-level `Main` node → Godot
  auto-suffixes to **`Main2`**, and the whole build nests under it. The Round-1 spatial fix gave
  the LAYOUT path dynamic root resolution; **the ARCH path (used by scenarios) never got it.**
- **Why Round 2 regressed 58→8:** per-scenario `_probe_scene_reset()` recreates a clean `Main`
  root before EVERY scenario, so the `Main`+`Main2` collision now fires on every scenario instead
  of occasionally. The "stale system_graph dedup" theory was WRONG — entities weren't being
  deduped away, they were under Main2 the whole time.
- **P3 STILL HOLDS:** `main.tscn` verified intact after the run (root "Main", no new pollution).
  The Main2 corruption is contained to the disposable probe scene. Good.

**REQUIRED FIX (DevForge arch path — adaptable, not vanilla):**
1. **Revert Round 2's per-scenario reset** (it regressed the score and fixed nothing). Keep the
   suite-start reset only, or keep per-scenario reset ONLY after the root bug is fixed.
2. **Fix arch-path root targeting** so entities parent to the LIVE editor scene root, never a
   hardcoded `/root/Main`. Mirror the layout fix: resolve the actual root from the scene
   (`scene["name"]`) and target it the way the godot-ai bridge addresses it (verify whether the
   bridge wants `/Main` or `/root/Main` — the empirical test is: does a node land under the
   EXISTING root or a new Main2?). `architecture_compiler.py:_resolve_parent` (~line 81-114) and
   wherever `root_path` is built in `engine._run_arch_path` are the edit sites.
3. **Acceptance:** after the fix, a single `cube_create` must put `TestCube` under the existing
   root (assert `node_exists(/Main/TestCube)` passes), and a full-suite re-run must recover to
   ≥ the old 58% (ideally higher). Until then scenarios CANNOT pass — they build into Main2.

> Lesson: every prior "P2" symptom should have been read as "where did the nodes actually go?"
> not "did they get built?". They were built — under Main2.

## 5d. ROUND 3 — DE-HARDCODE FIX LANDED + VALIDATED (Main2 cascade FIXED)

**Fix (2 DevForge files, root-agnostic — the arch path now mirrors the Round-1 layout fix):**
- `compilation/pipeline/architecture_compiler.py` `_resolve_parent`: top-level entities now
  return the live `root_path` (= `scene.root.path` = `/root/<RootName>`) instead of a hardcoded
  `/root/Main`.
- `compilation/pipeline/completeness.py` `_find_root`: resolves the actual scene root (the
  unique `/root/<RootName>` depth-2 entry) instead of hardcoding `/root/Main`; the camera/light
  scaffold now injects under the live root.
- Tests: `devforge/tests/test_completeness.py` +2 regression tests (a "Main2"-rooted scene must
  resolve to `/root/Main2`). Suites green: **DevForge 350, hub 151, spatial 30**.
- Requires `systemctl --user restart forge-devforge` to load (done).

**LIVE VALIDATION (model-independent path check):**
- `cube_create` → `/Main/TestCube` (PASS).
- `batch_three` → `/Main/BlockA`, `/Main/BlockB`, `/Main/BlockC` — **all under `/Main`, not
  `/Main2`.** The multi-node cascade is gone.
- `small_room` → scene root `/Main` (no Main2).
- **Conclusion: the Main→Main2 corruption is FIXED.** Nodes land under the real root.

**ROOT CAUSE recap (now fully understood):** a clean scene always built fine (cube_create
passes). The corruption was a CASCADE: once any build left the root as "Main2", the hardcoded
`/root/Main` in the arch compiler + completeness checker targeted a non-existent path; the bridge
materialized a fresh "Main" → Godot auto-suffixed it → everything nested under the rogue root and
it never self-healed. De-hardcoding both sites breaks the cascade.

**STILL OPEN (separate, lower severity — for the next session):**
1. **Wrong model loaded:** the stack is on `Cydonia-Redux-22B-v1e-Q4_K_M` (the *write* model),
   not qwen3-14b (the build model). Scenario scores on it are NOT comparable to the 58%
   qwen3 baseline; the 22B is poor at structured multi-node builds (small_room built nothing).
   **For a real score, swap to ⚒Build (qwen3-14b) and re-run.** (Not done here — model swaps are
   excluded from unsupervised work per the OOM/hang history.)
2. **Per-scenario reset over-cleans / aborts:** `scenarios.run_suite`'s per-scenario
   `bench._probe_scene_reset()` (Round 2) leaves a bare `/Main` (small_room saw no baseline) and
   aborts when the godot-ai MCP session drops (`active scene '?'`). Decide whether to revert it
   or fix it — needs a live A/B on a healthy session + qwen3. (NOT reverted blind this round:
   the last full-suite collapse was a *session death*, not the reset, so attribution is
   uncertain.)
3. **godot-ai MCP session dropped mid-suite** (recovered after). HTTP port stays healthy
   (chain-health green) but the editor session can vanish; `editor_state` re-syncs it. Possibly
   VRAM pressure from the 22B. Watch for it during long live runs.
4. **Hub test suite perturbs live state:** `pytest hub/tests/` writes `swap`/`test`/`reconcile`
   entries to the action log (P6 is broader than the one skipped swap test). Harden so the suite
   never dispatches against the live stack.

## 5e. ROUND 3 FINAL — qwen3 A/B, per-scenario reset reverted, stable 58%

Swapped to ⚒Build (qwen3-14b, verified via /props) and ran the full suite both ways:
- **qwen3 + Main2 fix + Round-2 per-scenario reset:** 50% (6/12), 0 errors.
- **qwen3 + Main2 fix, per-scenario reset REVERTED:** **58% (7/12), 0 errors.**

`scenarios.py` `run_suite` per-scenario `_probe_scene_reset()` REVERTED (the Round-2 regression):
on an already-active probe tab `scene_open` is a no-op, so it left bare scenes; without it the
baseline persists, completeness stops injecting an extra camera/light, and `batch_three`
recovered (50→58). Suite-start reset + per-scenario cleanup is the kept discipline. hub 151 green.

**Net of the whole effort:** the **Main2 corruption is eliminated** (0 errors, every node under
`/Main`, `main.tscn` never touched) and the **catastrophic-variance runs (the 8% disasters) are
gone** — the suite is now STABLE at the real 58% qwen3 baseline. The Main2 fix did not raise the
score above baseline because the baseline failures were never Main2-caused.

**The remaining 5 failures are SEPARATE, pre-existing issues (next session's targets):**
- `light_create` / `script_attach` / `small_room`: DevForge builds the generic completeness
  scaffold (`DirectionalLight`, `MainCamera`) but fails to create the specifically-NAMED
  requested nodes (`TestSun`, `ScriptedCube`, walls). Likely the planner skips an entity when a
  same-category node already exists (accumulation across the suite without per-scenario reset)
  OR the planned entities are dropped before execution. Investigate planner output + the
  `_live_scene_names` dedup + cross-scenario accumulation of injected camera/light.
- `node_delete` / `node_rename`: the delete/rename ops don't take effect (`ToDelete` persists;
  rename doesn't produce `NewName`). A real editing-op issue in apply_spec→godot-ai.
- Tradeoff to resolve: per-scenario reset (bare-scene bug) vs no reset (camera/light
  accumulation). The proper fix is a reset that truly reloads the probe baseline between
  scenarios without the no-op-`scene_open` limitation.

## 6. Artifacts produced this session (context)
- Spec: `hub/docs/superpowers/specs/2026-06-14-hub-testing-rework-design.md`
- Plan: `hub/docs/superpowers/plans/2026-06-14-hub-testing-rework.md`
- Rework audit (server-side checks + interactive checklist): `hub/docs/superpowers/AUDIT-2026-06-14.md`
- Memory: `forge-hub` note updated with the rework + open follow-ups.
- Fix landed this session: chain_health 404-liveness (`hub.py` `_check_http` `alive` flag);
  verified live. New `forge_score.py` (+ tests). Testing tab + theme + logo in `index.html`.
