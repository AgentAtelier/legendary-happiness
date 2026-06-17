# Testbench Migration — Open Work Handoff (for the other AI)

**Date:** 2026-06-16
**Reads with:** `TESTING-SYSTEM-DESIGN.md` (the architecture). This doc is
*what's left* and *how to do each piece*, in order.

---

## Status
- **Chassis: ✅ built + signed off** (Claude verified: self-describing metrics
  format ratio≠percent correctly; reporting is a pure function of the artifact;
  the runner's single-model path takes no swap).
- **Probes: ⚠ migrated (16), parity = 13/16 — 1 open item.** Parity caught **three
  migration bugs.** Claude fixed two; the third is localized and handed to you below.
  Two fixed (do **not** reintroduce):
  1. **bool metrics** used `Metric(v, "bool", "label")` (3 positional args → the
     label landed in `higher_is_better`, label missing → `TypeError`). Now
     `Metric.boolean(v, "label")` at all 10 sites in `tests/probes.py`.
  2. the runner **Context defaulted `planner="room"`**, so the DevForge probes
     (general-scene prompts) were routed through the *room* engine → empty deltas.
     Now the default is **arch** (`planner=""` → omitted → DevForge's arch
     default) in `runner.py` `_devforge_call` (l.74) and the context lambda
     (l.380). **Tests that want room/scatter/wfc/etc. pass `planner=` explicitly.**

**OPEN PROBE BUG (yours to fix) — the 3 DevForge probes (plan/compile/execute).**
On *both* the 27B and the reliable 9b, the new DevForge probes degrade vs old
(plan→broke "empty delta", compile/execute→partial) where `bench.py` PASSes. Same
prompt. Claude **ruled out**: planner (fixed), temperature (the old probe sends
*only* `{"prompt": …}`; forcing `temperature=0.2` is *not* the cause — a controlled
4-call test had both ways at 0 entities on a dirty scene), `Metric` (fixed), and
model flakiness (the 9b is reliable yet still diverges). **What's left: the new
`_capture_pipeline` / the runner's `_scene_reset` do not reproduce the old
`bench._pipeline_capture` + `run_probes` scene-reset/orchestration**, so apply_spec
runs against a scene state that yields an empty delta. **Fix:** align the new
DevForge-probe scene setup to the proven `bench.py` reset (the old probes reset to a
clean root *between* probes; replicate that). Claude re-verifies parity after.

## THE RULE (non-negotiable): parity before delete
For every category: **migrate → run old-vs-new on the same model → Claude confirms
the verdicts match → only then delete the old runner.** Never delete an old runner
before its replacement has parity-checked. (This rule just caught the two probe
bugs above before `bench.py` was retired — it works.)

---

## Open work, in order

### 1. Probe polish (small)
Only `everything` holds the 16 probes; `chain-health`, `llama-layer`,
`devforge-layer`, `godotai-layer`, `runtime-layer`, `odysseus-layer` are **empty**.
Assign each probe to its layer suite (the test's `suites` field, or catalog suite
population). **Acceptance:** `get_suites()` shows correct per-layer counts.

### 2. Migrate scenarios (`scenarios.py` → `scenario.*` plug-ins)
- Each scenario (cube/light/batch/script_attach/property_edit/the `*_existing`
  edit-ops/small_room/player_movement/no_dup_camera) + the 5 tool-call probes → a
  Test. `run(ctx)` applies ops / drives godot-ai; `score(raw)` = assertion
  pass-rate → status + score(0–100) + typed metrics (`pass` as `count`, `pass_rate`
  as `percent`). Category `scenario`; suite `scenarios-v1`.
- **Parity-gate** vs the old scenario runner → then delete it.

### 3. Migrate gauntlet (`gauntlet.py` sets → `cap.*` / `spatial.*` / …)
- Each gauntlet **prompt** → a Test (category by axis). `run` = `apply_spec` +
  measure; `score` = coverage → 0–100 + metrics (`coverage` as `percent`, `nodes`
  as `count`, full/partial/broke as `count`). Set `repeatable=True` (for ×N
  variance), and `skip_cache`/`needs_reset`/`screenshot` per prompt.
- The 7 sets → suites: `capability-v1`, `spatial-v1`, `building-v1`, `garden-v1`,
  `ssp-v1`, `wfc-v1`, `voronoi-v1`.
- **Parity-gate** vs old gauntlet (≥2 sets) → then delete the gauntlet runner.

### 4. Migrate diagnostics (Move-1 / multi-model-bench → `variety.*`/`intent.*`/`ceiling.*`)
- repeat_diversity, intent_sensitivity, ceiling → Tests. **This is where the Stage-4
  benchmark's reporting bugs die by construction:**
  - diversity → a **typed** metric — pick `percent` (shows `71%`) *or* `ratio`
    (shows `0.71`) and be consistent. **No more ×100.**
  - intent_coverage → a typed metric the reporting reads directly. **No more null.**
  - the runner **owns completion**, so the gauntlet can't be read mid-run.
- `skip_cache=True` on these (variety needs uncached runs). Suite `diagnostics-v1`.
- **Parity here = match the *raw* artifacts** (9b ≈0.71 diversity, 27b 0.00, intent
  ≈0.83), **not** the old broken summary.

### 5. Migrate the stress test (`STRESS-TEST-SCENARIO.md` → a `stress-v1` suite)
The Act I–V steps → Test plug-ins (`expect_break` where designed to fail,
`screenshot=True`, `skip_cache` on variety steps — the runner already supports all
three). This **replaces** the bespoke hub stress-runner from that doc; it's just a
suite now.

### 6. Repoint the Testing tab (UI → catalog + Artifact)
- Test list + **descriptions come from the catalog** (`test.description` — the
  friendly explainers become a property of each test, not hard-coded HTML).
- Suites / models(≤5) / repeat-N map onto the runner's `(test_ids, models[],
  repeat)` — already supported.
- Add one hub endpoint `POST /api/testbench/run` (SSE progress, reuse `_job_lock`)
  + artifact reads; render via `reporting.matrix/scorecards/summary`. The
  model×score matrix + scorecards I built render from the Artifact.
- **Then delete** the old `SUITES` adapters + scattered score-extraction in the hub.

### 7. Final teardown (ONLY after every parity gate passes)
Delete `harness.py`, the `multi-model-bench` runner, `bench.py`'s runner, the
bespoke result shapes in `gauntlet.py`/`scenarios.py`, and the per-suite hub
adapters. One Artifact format remains.

---

## Auto-resolved by this migration (no separate work)
The Stage-4 benchmark reporting bugs (×100 diversity, dropped intent-coverage,
gauntlet read mid-run) are **fixed by construction** once §4 lands with typed
metrics + the completion-owning runner. Don't patch the old runner — let §7 delete it.

## Claude's lane (not the other AI's)
- **Parity-check + sign off each category** as it lands (the gate above).
- The data-driven **suite curation / noise-pruning** once everything is on the
  chassis and trustworthy (Phase 2.5).

## Pending — a separate discussion
The user has a **"simplifying"** direction to explore that may re-scope parts of
this. Treat this as the current open work; revisit after that conversation.
