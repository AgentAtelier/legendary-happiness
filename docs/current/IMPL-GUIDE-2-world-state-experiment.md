# Implementation Guide 2 (CORRECTED) — The 4B-vs-27B Richness Verdict

Paste the block below into a code-writing CLI AI. This is a **rewrite** of the
first attempt, which drifted off the actual goal. Read the failure analysis below
before you start — it is the most important part.

## Why this guide was rewritten (the last CLI AI failed these — do NOT repeat)
The previous attempt:
1. **Self-approved its own design** and barreled from "design" into "build"
   without owner review. → This guide removes the design step: the design is
   already reviewed and specified below. You build to THIS spec. You do not
   invent your own.
2. **Measured the wrong thing.** It built the world-state machinery and measured
   *coordination* (clipping %, engine diversity) — and never ran the
   **4B-vs-27B richness comparison**, which is the entire point of the experiment.
   → The ONLY deliverable that matters here is that comparison and its verdict.
3. **Never ran its own code.** It shipped a Python syntax error and an
   import-path bug that crashed the whole testbench, because it only did
   import/parse checks. → Static checks are NOT acceptance here. You must RUN it
   against the live stack and paste real output.
4. **Invented scope and tangled branches**, left the gate red with broken
   imports. → Strict containment rules below.

---

```
============================ COPY FROM HERE ============================
TASK — settle ONE question with evidence: does a bigger local model (qwen 27B)
produce a VISIBLY and MEASURABLY richer game scene than a small one (qwen 4B),
or do they collapse to the same output? Per ADR-003 this is the project's
make-or-break bet. Your deliverable is a VERDICT backed by screenshots + numbers.

READ FIRST: docs/decisions/003-approach-survey-and-world-state-gap.md (the bet),
docs/current/CONVENTIONS.md (rules). The world-state machinery from a prior
attempt lives on branches exp/world-state and exp/world-state-richness
(world_state.py, scatter/voronoi occupancy params, world_planner.py + .gbnf, a
_run_world_path). Its DESIGN is sound and APPROVED — reuse it. Its MEASUREMENT was
wrong — you replace it per STEP 2 below.

THE GOAL IS NOT "make the world-state layer coordinate without clipping." That is
plumbing. The goal is the richness verdict. Do not drift.

=== HARD RULES (the last AI broke these; you will not) ===
1. BRANCH off main: `git checkout main && git checkout -b exp/richness-verdict`.
   NEVER commit to main. NEVER merge. This is an EXPERIMENT that may be thrown
   away — it does not go to production no matter how well it works.
2. RUN IT, DON'T CLAIM IT. Before you say any step "works," paste the actual
   command output into your report. "Imports OK" / "should work" / "parses" are
   NOT acceptance — the last AI shipped two crash bugs that way. Acceptance = you
   swapped a model, ran apply_spec with a real prompt against the live stack, read
   the scene back, and saved a screenshot. If you cannot drive the live stack
   (forge-llama/forge-devforge/forge-godot-ai must be up; a godot-ai editor
   session is needed for screenshots), STOP and say so — do not fake it.
3. Keep `scripts/check.sh` GREEN after every change. New files ≤500 lines.
4. ADDITIVE only. You may create new files and add a "world" planner route. The
   ONLY existing engines you may touch are scatter.py and voronoi.py, and ONLY by
   adding an optional `world_state=None` param whose absence leaves old behaviour
   byte-identical. PROVE that: run one garden + one town with world_state=None and
   confirm output is unchanged. Touch nothing else.
5. DO NOT self-approve past a STOP. If you hit a decision the spec doesn't cover,
   HALT and write the question in your report. Do not guess and proceed.
6. Report failures honestly. A "the bet FAILS" result is a SUCCESS for this
   experiment — it saves months. Do NOT tune, cherry-pick, or massage anything to
   make the 27B look better. If they look the same, say so loudly.

=== STEP 0 — Assemble + PROVE the machinery runs (this is where the last AI failed) ===
On exp/richness-verdict (off current main, which has the full testbench):
- Bring the world-state machinery from the exp branches: world_state.py, the
  scatter/voronoi world_state params, world_planner.py, world_planner.gbnf, and
  the _run_world_path method (port it into engine.py — do not blind-overwrite the
  file). Wire "world" as a per-request planner route like the other spatial ones.
- ACCEPTANCE (paste output for each):
  (a) `bash scripts/check.sh` → green.
  (b) The engine imports under the runtime path (hub runs python from hub/, repo
      root is NOT on sys.path — use BARE imports, e.g. `from forge_env import`,
      never `from hub.forge_env import`; that exact bug crashed the testbench).
  (c) Behaviour-preserving proof: run a scatter garden and a voronoi town with
      world_state=None; confirm node output identical to before your changes.
  (d) ONE real world build end-to-end against the live stack: apply_spec a
      multi-engine "world" prompt, read the scene back, SAVE a screenshot. Paste
      the node summary + screenshot path.
If (d) does not actually produce a scene in Godot, STOP — the machinery isn't
working and the richness test is meaningless until it does.

=== STEP 1 — Pick the richness prompt (one, wide, with room to be rich) ===
Choose ONE deliberately rich, open-ended world prompt that exercises the slice and
leaves the model room to add character — e.g. "A village in a forest clearing with
a road leading to it; the forest grows denser away from the road; a small market
square at the village center." Write it down in the report verbatim. Same prompt
for both models — no per-model prompt tweaks.

=== STEP 2 — The corrected MEASUREMENT (this is the fix) ===
Run the SAME prompt on BOTH models, N≥5 times each, skip_cache=True, via the
proven transactional swap (forge_ops.swap_model):
  - qwen 4b (the small one)
  - qwen 27b (the big one)
For each run capture: a Godot editor SCREENSHOT, and richness numbers — reuse the
testbench where you can (the just-migrated variety.* diversity metric), plus
simple counts: total placed nodes, distinct asset/prop types, props-per-area
(density), and count of distinct "features" (e.g. market, road, clearings).
Aggregate per model: mean ± spread.

Define the verdict thresholds BEFORE looking at results, and write them down:
  - BET HOLDS if the 27B is BOTH (i) visibly richer in the screenshots (a person
    can tell them apart) AND (ii) measurably higher on the richness numbers by a
    clear margin you state up front.
  - BET FAILS if 4B and 27B are visually indistinguishable AND the richness
    numbers overlap. In that case the recommendation is the ADR-003 pivot: move
    the LLM to the narrative layer, keep structure deterministic/human-driven.

=== STEP 3 — Write the VERDICT ===
Write docs/reviews/world-state-richness/RESULT.md with: the exact prompt, the
per-model screenshots side by side (paths), the richness numbers per model
(mean ± spread), the thresholds you set in STEP 2, and a one-line plain verdict:
"BET HOLDS — richness scales" or "BET FAILS — indistinguishable, pivot". Be honest
even if it kills the approach.

=== REPORT + STOP ===
Push the branch (never merge). Reply in chat with: the branch name, whether STEP
0(d) actually produced a scene, and the one-line verdict (or "STOPPED at STEP X:
<reason>"). Do not declare success without the pasted run output behind it.
============================= TO HERE ==================================
```

---

## After this runs
The owner + Claude review `RESULT.md` and the screenshots. This is the **decision
point for the project's central bet**: a "bet holds" greenlights building the
macro frontier on the world-state pattern; a "bet fails" triggers the ADR-003
pivot. Either outcome is a real result — the experiment exists to be *allowed to
fail*, and the branch never touches `main` until that verdict is reviewed.
