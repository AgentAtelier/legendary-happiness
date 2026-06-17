# Implementation Guide 1 — Finish the Testbench Migration (for a CLI AI)

Paste the block below into a code-writing CLI AI. It finishes migrating the test
system onto the `hub/forge_testbench/` chassis and retires the legacy runners.

**Why this is next:** it unblocks two things — (a) the `hub.py` split
(`GOD-FILE-SPLIT-PLAN.md` Phase 2, gated on legacy deletion per ADR-005), and
(b) trustworthy measurement for the world-state experiment (Guide 2).

---

```
============================ COPY FROM HERE ============================
IMPLEMENTATION TASK — finish the testbench migration. You write code, under
guardrails.

AUTHORITATIVE DOCS (read first; they outrank your preferences):
- docs/current/TESTBENCH-MIGRATION-HANDOFF.md   (the migration spec + THE RULE)
- docs/current/TESTING-SYSTEM-DESIGN.md          (the chassis architecture)
- docs/current/CONVENTIONS.md                    (coding rules)
- docs/decisions/005-legacy-test-runner-cutover.md (hard-cut decision)

CONTEXT: `hub/forge_testbench/` is the new unified test chassis (runner, Result,
self-describing Metric, catalog, pure reporting) — it is built and is the
reference for clean code. The legacy runners in `hub/` (bench.py, shootout.py,
scenarios.py, gauntlet.py, multi_model_bench.py, comprehensive_bench.py,
harness.py) are being replaced and then DELETED. Note: runner.py was recently
refactored (it now uses hub/mcp_client.py and forge_env.read_env), so line
numbers in the handoff may be stale — trust the current code, not the line refs.

GROUND RULES (non-negotiable):
1. BRANCH: `git checkout -b migrate/testbench`. All work there. Never commit to
   main, never merge. Push the branch and report; the owner reviews + merges.
2. THE RULE (from the handoff): parity before delete. For EACH category:
   migrate it → run the OLD runner and the NEW testbench on the SAME model →
   compare verdicts/metrics → STOP and write the parity result in your report →
   do NOT delete the old runner. The owner takes the parity result to Claude for
   sign-off; deletion happens only after that. You migrate and prove parity; you
   do not retire anything on your own.
3. After every code change, run `scripts/check.sh` and keep it GREEN (ruff +
   format + file-length gate). Run `ruff format` + `ruff check --fix` on changed
   files. New files must be ≤500 lines and match forge_testbench's style.
4. Small commits, one category per commit-group, conventional messages. If a
   smoke check or parity comparison fails or is ambiguous, STOP and report — do
   not paper over a divergence.
5. Behavior of the chassis is the spec; do not change Metric/Result/Artifact
   shapes. The live stack runs as systemd services (forge-hub, forge-devforge,
   forge-llama); a testbench run needs them up. Restart forge-hub to load
   hub-side changes.

DO THE CATEGORIES IN THIS ORDER (one at a time, each parity-gated):

A. PROBE PARITY + LAYER SUITES. Close the 3 open DevForge probe mismatches
   described in the handoff ("OPEN PROBE BUG" — the new scene-reset/orchestration
   doesn't reproduce the old bench reset). Align the probe scene setup to the
   proven reset. Then populate the empty layer suites (chain-health, llama-layer,
   devforge-layer, godotai-layer, runtime-layer, odysseus-layer) so get_suites()
   shows correct per-layer counts. Parity target: 16/16 probes match the old
   bench.

B. SCENARIOS. Migrate scenarios.py (cube/light/batch/script_attach/property_edit/
   the *_existing edit-ops/small_room/player_movement/no_dup_camera + the 5
   tool-call probes) into scenario.* Test plug-ins (run = apply ops/drive
   godot-ai; score = assertion pass-rate → typed metrics). Suite scenarios-v1.
   Parity vs the old scenario runner.

C. GAUNTLET. Migrate the 7 gauntlet sets to cap.* / spatial.* / building.* /
   garden.* / ssp.* / wfc.* / voronoi.* Tests (run = apply_spec + measure;
   score = coverage → 0-100 + typed metrics; repeatable=True; skip_cache/
   needs_reset/screenshot per prompt). Parity vs old gauntlet on ≥2 sets.

D. DIAGNOSTICS. Migrate repeat_diversity / intent_sensitivity / ceiling into
   variety.* / intent.* / ceiling.* Tests with TYPED metrics — this is where the
   old reporting bugs die by construction: diversity as a typed ratio/percent (NO
   ×100), intent_coverage read directly (NO null), the runner owns completion (NO
   mid-run read). skip_cache=True on these. Suite diagnostics-v1. Parity = match
   the RAW artifacts (9b ≈0.71 diversity, 27b 0.00, intent ≈0.83), NOT the old
   broken summary.

E. STRESS. Turn the Act I–V steps of docs/current/STRESS-TEST-SCENARIO.md into a
   stress-v1 suite of Test plug-ins (expect_break where designed to fail,
   screenshot=True, skip_cache on variety steps — the runner supports all three).

F. UI REPOINT. Point the Testing tab at the catalog + Artifact: test list +
   descriptions from test.description; suites/models(≤5)/repeat-N map to the
   runner's (test_ids, models[], repeat). Add ONE endpoint POST /api/testbench/run
   (SSE progress, reuse _job_lock) + artifact reads; render via
   reporting.matrix/scorecards/summary.

G. TEARDOWN (only after the owner confirms every category passed parity). Per
   ADR-005 hard cut: delete bench.py, shootout.py, scenarios.py, gauntlet.py,
   multi_model_bench.py, comprehensive_bench.py, harness.py, their hub.py routes,
   and the per-suite hub adapters. Remove their entries from the ruff/length-gate
   excludes in pyproject.toml and scripts/check.sh. Then NOTE in your report that
   GOD-FILE-SPLIT-PLAN.md Phase 2 (the hub.py split) is now unblocked — but do
   NOT do that split here.

REPORT: write docs/reviews/testbench-migration/REPORT.md — per category: what you
migrated, the parity result (old vs new, same model), what smoke checks passed,
and which deletions are awaiting owner sign-off. Push the branch. Reply in chat
with the branch name + a one-line status.
============================= TO HERE ==================================
```

---

## After this
The owner + Claude sign off each category's parity, then the deletions land. The
hub.py split (Layer-3 Phase 2) is then unblocked, and the diagnostics category
(D) gives the trustworthy diversity/intent measurement that Guide 2 depends on.
