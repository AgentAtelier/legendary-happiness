# Stage Plan — A–F: Spatial, Capability, Edit-Ops, Robustness, Diagnostics, Hygiene

**For the next AI.** Same method as prior stages: **instrument → measure → isolate → fix →
re-measure**; every stated cause is a **hypothesis to test** (we've revised "root causes" 5+
times); **documentation is a first-class deliverable.** Work in **BIG SLICES** — take a whole
theme, drive it to a *visible result + a re-measurement*, update the docs, then the next slice.
Each slice ends with a number that moved and an honest doc.

---

## ‼️ READ THIS FIRST — THE HUMAN RUNS THE TESTS, NOT YOU
The human's budget with you is **time-based**. A gauntlet run is ~1 min/prompt, a scenario suite
is ~6–8 min, a model swap ~1 min. **Waiting on those while the clock runs is pure waste.**

**The rule:**
- **You do NOT run tests, gauntlets, scenario suites, `apply_spec` probes, or model swaps
  yourself.** Do not start a long command and block the session on it.
- When a run is needed, **stop and hand the human the EXACT command(s)** to run in their own
  terminal (off-clock), with a one-line note of what to look for, then **wait for them to paste
  the results.** Continue from what they paste.
- This includes the unit suites — hand over `pytest …` too; their terminal is free, your clock
  is not.
- **What you MAY do on-clock:** read/grep code, edit code, reason, and *prepare* the commands +
  the expected-output description so the human's manual run is one paste-back. Near-instant
  sanity reads (a `grep`, a file read) are fine; anything that *executes the pipeline or a test*
  is the human's to run.
- Format the handoff so it's trivial to run, e.g.:
  > **Please run and paste the output:**
  > ```bash
  > cd /home/mrg/dev/games/Forge/hub && .venv/bin/python -m pytest tests/ -q
  > ```
  > *(expect: all green; watch for any new failure in `test_*`)*

When a code change needs `forge-devforge`/`forge-hub` restarted to take effect, **tell the human
to restart it** (and to clear `__pycache__` first — see Hygiene) as part of the same handoff.

---

## 0. Ground rules (firm)
- Odysseus + godot-ai stay **VANILLA**. Adapt only DevForge, the hub, `stack.env`/`forge-model`,
  Odysseus config.
- Restart `forge-devforge` after DevForge code changes; `forge-hub` after `hub.py`. (The human
  does the restart + the test run.)
- Verify with evidence — but the *human* produces the evidence by running the command you hand
  them. No "should work."
- Nothing may require an AI/daemon running permanently.

## 1. State of truth (verify via the human; don't re-derive)
Capability-v1 is **model-dependent**: **97%** (7F/1P/0B) on **qwen3-14b** with **G5_scripts_signals**
the last partial (75%), but **100%** (8F/0P/0B) on **qwen3-6-27b** — the larger model resolves G5,
confirming the standing diagnosis that G5 is LLM signal non-determinism, not a code bug. The 27B is
the currently-loaded model. (Live: `gauntlet-20260615-190001.json` = 27B/100%;
`gauntlet-20260615-134440.json` = 14B/97%.) Pipeline reliability is strong:
connection-guard hierarchy (B1 non-3D target / B2 unscripted same-delta / B3 method-fallback),
host-node creation for orphaned systems, dual validation (compiler semantic + validator type),
and "execute whenever there are valid ops" (no more all-or-nothing on one bad op). **The kitchen
is built, proven, AND wired into the normal flow** (`kitchen_demo.tscn`, deterministic
SpatialCompiler; `spatial-v1` routes through `planner: layout` and builds a real greybox kitchen
via `apply_spec`, 30/30 ops, 0 errors — verified 2026-06-16). Hub diagnostics live:
`/api/runs`, `/api/runs/stability`, `/api/runs/compare`, per-op `execution.errors`,
`stage_latencies`, `plugin_logs` on gauntlet failures. Full trail: `hub/docs/` (`SESSION-CHANGES-*`,
`OBSERVATIONS-2026-06-15`, `GRAND-ROADMAP`, `STAGE-NEXT-*`) + the `forge-hub` memory note.

> **Inherited misframing — RESOLVED & INVERTED (2026-06-16, verified from the run artifact):**
> an earlier note claimed spatial-v1 "routes through the arch planner, the compiler is never
> invoked — it's a routing bug, not a check bug." **The opposite is true.** Routing works:
> `spatial-v1.json` declares `planner: layout`, `gauntlet.py:319-324` threads it into `apply_spec`,
> and `engine.py` honours the per-request `planner` ("arch"|"layout"|"ops"). The S1_kitchen run
> (`data/gauntlet/gauntlet-20260615-231900.json`, model qwen3-6-27b) built
> `/Main/Kitchen/{Counter,Fridge,Stove,Table}` — each a positioned container with a MeshInstance3D
> + CollisionShape child — at **30/30 ops, 0 errors**: deterministic SpatialCompiler output, not an
> LLM guess. The 67% was a **pure measurement bug**: `spatial:assets` only counted MeshInstance3Ds
> positioned *directly*, so it scored the layout pattern (mesh parented under a positioned
> container) as 0/3. **Fixed in `gauntlet.py:_add_spatial_checks` on 2026-06-16** (count a
> positioned node that is, or is the parent of, a MeshInstance3D). Slice A is no longer "route
> spatial" — it's "re-measure to confirm ~100%, then make the eval harder."

---

## SLICE A — Make spatial a real, MEASURED capability  ★ next headline
**Routing is DONE and the measurement bug is FIXED (2026-06-16).** What's left is confirmation +
making the eval harder.
- ~~Route `spatial-v1` to the layout planner.~~ **DONE** — `spatial-v1.json` `planner: layout` →
  `gauntlet.py:319-324` → `engine.run_pipeline(planner=...)`. Verified building a real greybox
  kitchen through the normal `apply_spec` flow (30/30 ops, 0 errors).
- ~~Fix the `spatial:assets` check~~ **DONE** — `gauntlet.py:_add_spatial_checks` now counts a
  positioned node that *is, or is the parent of,* a MeshInstance3D (was: only directly-positioned
  meshes → scored layout output 0/3). Pre-fix run was 67% (0F/4P) on a *correctly built* kitchen.
- **Re-measure `spatial-v1`** to confirm the fix lands it near 100% (expect S1–S4 to flip
  partial→full). **This is the open step.** (Human runs it — see the rule above.)
- **Then make the eval more demanding** now the engine + measurement are proven: assert per-asset
  *placement correctness* (north-wall items actually on the north wall, table centered), not just
  count + non-overlap.
- **Test handoff:** hand the human the `spatial-v1` gauntlet command; ask for the per-prompt
  verdicts + a screenshot. Expect ~100% if the check fix is correct.
- **Deliverable:** confirmed real spatial scores (~100%) + a harder placement-correctness eval.

## SLICE B — Close the capability axis + handle non-determinism
- **G5 stability:** auto-create a **stub script for unscripted signal targets** (the *reverse*
  host-node case — entity targeted by a connection but no system). This is the identified fix for
  the last partial.
- **Multi-run measurement:** qwen3 is non-deterministic even at temp 0.2 (G2 flips full↔partial
  with identical nodes; G5 signal count 0↔1). Add a `--runs N` mode to the gauntlet (mean ±
  stddev per prompt) and route it through `/api/runs/stability`. **Single runs are snapshots.**
- **Test handoff:** the human runs `--runs 3` on capability-v1 and pastes the variance.
- **Deliverable:** G5 stable to full, and a variance number that tells truth from noise.

## SLICE C — Edit-op reliability (untouched; the real open capability gap)
- **B1 truncation:** edit prompts ("Delete Gizmo.") truncate the planner intermittently. Leading
  hypothesis: the **unapplied thinking/reasoning config** (`--reasoning-budget 1024`, no
  `enable_thinking:false`; the prior session already built `api_thinking_toggle`). Run the clean
  **A/B** (thinking on/off) — measure truncation rate + edit-op scores + `stage_latencies`. **Do
  not apply the config as a default without the human; present the data.**
- **B2 same-batch create-then-edit:** decide — fix (split batches / recognize net-zero) or declare
  the test degenerate (the realistic case is editing *existing* nodes; the `*_existing` scenarios
  test that).
- **Resolver:** live-validate the `_resolve_node_target` punctuation-strip + token-match fix once
  truncation is unblocked (implemented + unit-tested, never reached live).
- **Test handoff:** the human runs the edit-op scenarios under each thinking setting and pastes
  both.
- **Deliverable:** edit-op scenarios off the floor, with the A/B data behind the decision.

## SLICE D — Validation / robustness consolidation
- **Add `position` to `PROPERTY_ALLOWLIST`** (complement of `_NON_3D_TYPES`; consider a `*3D` +
  `Node3D` wildcard) so the guard lives in one place (the validator), not split with the compiler.
- **Reverse host-node (entity→system stub)** — sibling of Slice B's G5 fix; do them together.
- **Ghost fabricated-parent detection** (G8 hardening) — low priority; G8 already passes.
- **Deliverable:** validation consolidated; no regression (human runs capability-v1).

## SLICE E — Diagnostics surfaced + measurement infra
- **Surface `stage_latencies` (planning/compilation/execution) + per-op `execution.errors` in the
  Testing-tab UI** — the data's collected, barely shown.
- **Extend `plugin_logs`/`logs_read` capture to scenarios** (gauntlet-only today).
- **Coverage-model refinement:** the binary `passed/total` model makes G2 flip full↔partial with
  identical nodes. Consider partial credit / weighting / saturation. Plus a **historical trend
  view** over `data/gauntlet/`.
- **Deliverable:** a slow/failed build is legible at a glance; trends visible.

## SLICE F — Code quality & hygiene
- **Extract `compile()` sub-methods** — it's ~400 lines (entity creation, systems, rename/remove,
  `_compile_connections`, `_validate_semantics`, `_create_host_for_system`).
- **`.pyc` auto-clear on restart** (stale-bytecode bit multiple sessions); **module-level `import
  re`** (the `_re`-in-method-scope NameError class); a **pyflakes/linter** pass (caught the
  unreachable-code-after-`if` bug only at runtime).
- **Grunt backlog:** remove ~600 lines of dead old-tab markup/JS in `index.html`; clean
  `/Main/ToDelete` + `/Main/OldName` from `main.tscn`; stop `pytest hub/tests/` writing
  `swap`/`test`/`reconcile` to the live action log (P6).
- **Deliverable:** smaller files, fewer footguns, less cruft.

---

## Things to challenge (don't inherit our blind spots)
- Per-request `planner` param vs global `DEVFORGE_PLANNER` (Slice A) — pick with reasons.
- Whether `spatial-v1`'s prompts/checks are the right spatial eval now the engine is proven.
- Whether the thinking-config is *really* B1's cause — prove it with the A/B.
- Whether `% coverage` is the metric vs. stability/variance (use `/api/runs/stability`).
- Whether the dual-validation split (compiler semantic vs validator type) is drawn in the right
  place as you add the `position` check (Slice D).

## Suggested sequencing (your call)
**A** (spatial real — the headline) → **B** (close G5 + variance, cheap) → **C** (edit-ops, the
last capability gap). **D–F** are consolidation/hygiene to fold in between the big slices. Big
slices. Momentum. Measured outcomes. **Human runs the tests.** Honest docs.

## Documentation required back
1. A `SESSION-CHANGES-YYYY-MM-DD.md` change log — per change: symptom → root cause → exact change
   → **the command the human ran to verify + the result they pasted**.
2. **Update the state-of-truth** in this doc / the roadmaps when data contradicts a claim. We've
   shipped stale claims ("forces all stages to 0.2", "0% truncation", "spatial:assets is a check
   bug"). When the data says otherwise, fix the doc.
3. Per slice: hypothesis → measurement (the command) → data (the paste-back) → what it showed
   (esp. where it contradicted this plan) → change → re-measurement.
