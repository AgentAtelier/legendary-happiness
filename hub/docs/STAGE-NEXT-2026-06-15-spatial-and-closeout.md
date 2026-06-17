# Next Stage — Spatial as a First-Class Capability + Reliability Close-out

**For the next AI.** Same method as the last stage: **instrument → measure → isolate → fix →
re-measure**, every stated cause is a **hypothesis to test** (we've revised "root causes" 4–5
times now), and **documentation is a first-class deliverable**, not an afterthought.

**One change in how I want you to work this stage: move in BIG SLICES.** Don't nibble
one-bug-at-a-time. Take a whole coherent slice, drive it to a **visible result + a
re-measurement**, update the docs, then take the next slice. We want momentum — each slice should
end with a number that moved and a doc that's honest. You decide the *how*, the *order*, and
whether a slice is even the right shape — push back where you disagree.

---

## 0. Ground rules (firm)
- Odysseus + godot-ai stay **VANILLA**. Adapt only DevForge (`devforge_review_package/...`), the
  hub, `stack.env`/`forge-model`, or Odysseus config.
- Restart `forge-devforge` after DevForge code changes; `forge-hub` after `hub.py`. Frontend is
  served from disk.
- Verify with evidence. A green unit test ≠ a working feature — run it live, read the data.
- Nothing may require an AI/daemon running permanently.

## 1. State of truth (verify it yourself; don't re-derive)
**Done + verified live:** Main→Main2 cascade fix; Bug 1 (invalid-property → atomic rollback);
**G4 fix** — the gauntlet "broke" was a *phantom-connection → atomic rollback* (the LLM wires a
`connect_signal` to a hallucinated `ScoreLabel`; the compiler fabricated the path and one bad op
rolled back the whole build). Fix = drop connections whose endpoints don't resolve
(`architecture_compiler.py` ~line 275; +2 tests). **Verified broke(60%,0 nodes)→full(100%,10
nodes) live.** **The kitchen is built** — the SpatialCompiler was driven directly (deterministic,
no LLM), 38 ops/38 applied/0 errors, 7 greybox assets placed in a 5×5×3 room, saved to
`res://kitchen_demo.tscn` (script: `/tmp/build_kitchen.py`). The spatial slice **works
end-to-end.** Hub diagnostics are live: `/api/runs`, `/api/runs/stability`, `/api/runs/compare`,
per-op `execution.errors`, `stage_latencies`, and `plugin_logs` captured on gauntlet failures.

**Two prior conclusions the data corrected (don't re-inherit them):** the §5 `temperature=0.2`
override is a **no-op for the `arch` stage** (it's already 0.2 in `runtime_config.py`) — wrong
lever, superseded by the G4 fix. §6's "0% truncation, n_predict is sufficient" only tested
**create** prompts (the gauntlet) — the **edit-prompt truncation is still open and unmeasured.**

**Open:** capability-v1 not re-measured since the G4 fix; **spatial-v1 never actually ran the
spatial compiler** (see Slice 1); model left on **merged-22b** (not the qwen3 build model);
edit-prompt truncation; same-batch create-then-edit; resolver fix live-unverified; grunt backlog.
Full trail in `hub/docs/` (`GRAND-ROADMAP-2026-06-15`, `SESSION-CHANGES-2026-06-15`,
`AUDIT-BRIEF-2026-06-14`, `FINDINGS-*`) + the `forge-hub` memory note.

---

## SLICE 0 — Re-measure & restore (close the last stage; do this first)
The G4 fix is verified on **one** prompt. Close the loop:
- **Swap to qwen3 (⚒ Build mode)** — restores the correct build model (currently merged-22b).
- Run **capability-v1** (and the scenario suite). Confirm G4 broke→full holds, and check the
  **aggregate**: the connection-drop fix is signal-class, so it should also help the
  signal-heavy prompts (**G5_scripts_signals / G7_integration / G8_adversarial**). Watch for
  regressions. Use `/api/runs/compare` against the §6 baseline (qwen3 85% / the per-prompt table
  in `SESSION-CHANGES`).
- **Deliverable:** a before/after table (which prompts moved, the new avg coverage, zero
  regressions) + the run on disk. This is "run all the tests," done with data.

## SLICE 1 — Make spatial REAL and measured (the kitchen finding)
> **SUPERSEDED 2026-06-16 — this slice's framing was wrong on both counts. See
> `STAGE-PLAN-2026-06-15-A-to-F.md` Slice A for the corrected, current truth.** Routing is DONE
> (`spatial-v1.json planner: layout` → `gauntlet.py` → `engine.py`), and the spatial compiler *is*
> invoked (verified: a real greybox kitchen, 30/30 ops, 0 errors). The remaining gap was the
> **`spatial:assets` check** (the opposite of what the next sentence claims) — it miscounted
> container-parented meshes; **fixed** in `gauntlet.py:_add_spatial_checks`. The text below is kept
> for history only.

This is the headline of the stage. **The gauntlet's `spatial-v1` set has never invoked the
spatial compiler** — `gauntlet.py` calls `apply_spec` with **no planner param**, so all four
"kitchen/corridor" prompts route through the *default arch planner*. So §6's spatial scores
(58%/33%) and "0 assets counted" measured the LLM guessing at a room, **not** the deterministic
layout engine (which we just proved works). The `spatial:assets` check is fine; the gap is
**routing**.
- **Route spatial prompts to the layout planner.** Mechanism is your call: a **per-request
  `planner` param on `apply_spec`** (the prior session added a `temperature` param the same way —
  exact precedent, `mcp_server.py` + `engine.run_pipeline`), or the global
  `DEVFORGE_PLANNER=layout`. Per-request is cleaner (no global mode flip), but you decide.
- **Re-run `spatial-v1` THROUGH the real layout path** and get **true** spatial scores. Compare to
  the (meaningless) arch-path numbers.
- **Make the kitchen reachable through the normal flow** — `apply_spec "build me a kitchen"` via
  the layout planner should produce a placed greybox kitchen, not just the hand-driven script.
- **Deliverable:** real spatial-v1 scores on qwen3 + a kitchen built through the normal pipeline
  (screenshot it — `editor_screenshot view_target=... elevation/azimuth` works well).

> Slices 0 and 1 together ARE the two things to do first. The rest of the stage is below — take
> them as big slices, not a checklist.

## SLICE 2 — Edit-op reliability (the whole B1/B2 cluster as one slice)
Editing *existing* nodes (delete/rename) is the last broken capability. Treat it as one slice:
- **Truncation (B1):** edit prompts truncate the planner ("hit n_predict") *intermittently* — the
  leading hypothesis is the **unapplied thinking/reasoning config** (`--reasoning-budget 1024`, no
  `enable_thinking:false`; the prior session already built an `api_thinking_toggle`). Run the
  clean **A/B**: thinking on vs off, measure **truncation rate + edit-op scores + stage_latencies**
  both ways. Don't apply the config as a default without the human — present the data.
- **Same-batch create-then-edit (B2):** `node_delete`/`node_rename` fail because the edit op can't
  see a node created earlier in the same atomic batch. Decide: fix (split batches / recognize
  net-zero) or declare the test degenerate (the realistic case is editing existing nodes — the new
  `*_existing` scenarios).
- **Resolver:** live-validate the punctuation-strip + token-match `_resolve_node_target` fix once
  truncation is unblocked (it's implemented, unit-tested, never reached live).
- **Deliverable:** the edit-op scenarios moving off the floor, with the truncation A/B data behind
  the decision.

## SLICE 3 — Diagnostics surfaced + grunt (one slice)
- Surface `stage_latencies` (planning/compilation/execution split) and per-op `execution.errors`
  in the Testing-tab UI — the data's collected, barely shown.
- Extend `plugin_logs`/`logs_read` capture beyond gauntlet failures (scenarios too).
- Grunt that's been waiting: remove the ~600 lines of dead old-tab markup/JS in `index.html`;
  clean `/Main/ToDelete` + `/Main/OldName` pollution from `main.tscn`; stop `pytest hub/tests/`
  from writing `swap`/`test`/`reconcile` to the live action log (P6).

## Things to challenge (don't inherit our blind spots)
- Per-request `planner` param vs global `DEVFORGE_PLANNER` — pick with reasons.
- Whether `spatial-v1`'s prompts + checks are the *right* spatial eval (now that the engine is
  proven, the eval can get more demanding).
- Whether the thinking-config is *really* B1's cause — prove it with the A/B, don't assume.
- Whether "% coverage / pass_rate" is the metric that matters vs. stability/variance (we built
  `/api/runs/stability` — use it).

## Documentation (required back)
**Update the docs as you go** — this is not optional:
1. A `SESSION-CHANGES-YYYY-MM-DD.md` change log (the prior one is a good template): per change,
   symptom → root cause → exact change → verification.
2. **Update the state-of-truth** in this stage doc / the roadmap so the trail stays honest — we've
   shipped stale claims before (e.g. "forces all stages to 0.2", "0% truncation"). When the data
   contradicts a doc, fix the doc.
3. Per slice: the hypothesis, the measurement, the data, what it showed (especially where it
   contradicted this plan), the change, the re-measurement.

## Suggested first moves (your call)
Slice 0 (re-measure + restore qwen3) → Slice 1 (route spatial to layout, real scores, kitchen via
normal flow). Those two close the last stage and open this one. Then Slice 2 or 3 as the data
suggests. **Big slices. Momentum. Measured outcomes. Honest docs.**
