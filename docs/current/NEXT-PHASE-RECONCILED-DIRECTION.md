# Next-Phase Direction — RECONCILED (deterministic evaluation + reliability loop)

**Date:** 2026-06-17
**Supersedes** the "VLM-as-keystone" framing in
`NEXT-PHASE-VISUAL-EVAL-SURVEY.md` (which was the *question*; this is the
*answer* after chat + CLI input).

## The verdict: the survey pivoted the keystone

Three independent sources converged on the **same** conclusion:
- **Chat AIs** (concept, 6 responses): don't put a VLM in the evaluation loop.
- **CLI AIs** (codebase, 3 reports): even when asked *how* to build the VLM, they
  said "deterministic signals first; the VLM is slow, uncalibrated, and must never
  block."
- **xenodot-forge** (an external project): already uses **deterministic
  headless-Godot verification**, not model-judging.

**Pivot: demote the VLM from keystone to an optional, offline, non-gating
descriptive aid. Build deterministic evaluation instead.**

Why VLM-in-the-loop is wrong (convergent): two stochastic things judging each
other; **topology-blind** (one 2D frame can't see physics/wiring/clipping/floating
nodes); **Goodhart/reward-hacking** (the generator learns to spam visual noise to
score high while the scene graph stays broken); **16 GB can't co-run** → a
60–120 s swap per rating kills the loop; it needs a **calibration set you don't
have**; "a gate with a wrong threshold is worse than no gate."

## The reconciled slice (ordered by value ÷ cost — cheap & safe first)

1. **Fix screenshot capture.** The worlds *do* build (1000s of ops); the editor
   camera just isn't framed on them. Frame it (godot-ai `view_target`/`elevation`/
   `azimuth`, or camera framing) → `source=viewport`. Unblocks the *human* eyeball
   (the real judge) and any future VLM. *Caveat: confirm godot-ai's framing op
   exists; we do not patch godot-ai source.*
2. **A — System-owned conditioning.** The CLI reports found the richness framing
   is **completely absent from all 9 planner prompts** today (only RoomIntent has
   any). Add ONE `conditioning.py` module, inject it at the dispatch points
   (`_run_spatial_path` + `_run_arch_path`), with an env toggle for A/B. **Biggest,
   cheapest win** — it makes a plain request always get the rich treatment, which
   *is* the fix for the "magic words" problem.
3. **B (structural) — Deterministic collapse/quality gate.** `PipelineResult`
   already carries `truncated` / `plan_retries` / `completeness_added` / entities;
   add scene-graph checks (variety collapse, op monoculture, thin generation,
   missing systems, bounding-box overlap, floating nodes). **No LLM.** This is
   exactly the "scene-graph linter" the chat survey recommended — and it's the
   honest, loud, deterministic gate (CONVENTIONS rule 8: no silent disabling).
4. **The deepest lever — scale as a parameter + a wider brief schema.** The real
   expressiveness ceiling is the **schema**, not the model: today the planner's
   props are limited to `{mesh, shape, color, position, text}`
   (`architecture_planner.py:281-360`). Two moves: (a) move **scale/richness** to a
   deterministic parameter the engine/UI owns (so the LLM stops being a "stochastic
   counter"), and (b) **widen the schema** (materials, nested props, relationships)
   so a bigger model *can* express more. This is the thing that decides whether
   model size will ever visibly matter — it deserves its own investigation, and it
   resolves the unease about prompt-phrasing controlling output.
5. **VLM — deferred, offline, advisory, calibration-gated, NEVER a blocking gate.**
   Only after a calibration set exists; combined with structural signals (never
   alone); for human-facing description / trend, not to gate the loop. Optionally a
   tiny (~1.5 B) co-resident VLM on a second port to dodge the swap tax. **Last and
   optional.**

## Explicitly NOT doing now
- No VLM inside the `apply_spec` loop or as a gate.
- No model-escalation-on-collapse yet (swap tax + the "thrash death spiral" the
  survey warned of; opt-in / future).

## The through-line
This is your *original* architecture bet applied honestly: **deterministic code
owns single-correct-answer things — including the countable parts of "richness."**
The survey didn't reject the project; it caught us drifting (outsourcing a
quantitative variable — *scale* — to a stochastic model) and pointed us back. The
result is cheaper, more reliable, and more *you* than the VLM keystone would have
been.

## Codebase anchors (from the CLI reports)
- **Screenshot:** `engine/devforge/execution/godot_ai_executor.py:608` (`source=game`,
  `include_image=False` bug) — needs camera framing before `source=viewport`.
- **Conditioning:** 9 `_build_prompt` methods; inject at `engine.py` `_run_spatial_path`
  (~615) + `_run_arch_path`; new `engine/devforge/reasoning/prompts/conditioning.py`;
  env toggle.
- **Gate:** `PipelineResult` fields + a new `_check_generation_quality` over
  `arch_delta`/`operations`; hook after completeness (~engine.py:530).
- **Testbench:** `Result.screenshot` already exists (unused); `Metric` extensible;
  add a `visual` category later (only when/if the VLM lands).
- **Schema ceiling:** `architecture_planner.py:281-360` — props `{mesh,shape,color,
  position,text}`.

## Next step
Turn slices 1–3 (+ the schema/scale investigation of 4) into a design spec. The
VLM (5) waits until the deterministic foundation exists and a calibration set can
be built.
