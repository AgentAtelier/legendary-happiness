# Implementation Guide 2 — World-State Slice + the Richness Test (for a CLI AI)

Paste the block below into a code-writing CLI AI. This builds the **decisive
experiment** from ADR-003: does scene richness actually scale with model size, or
is the brief a lossy bottleneck that makes a 4B and a 27B produce the same scene?

**This is design-then-build.** The experiment's design IS the make-or-break — so
the guide makes the AI produce a design proposal and STOP for owner approval
before building any engine. It must be built to be able to FAIL.

**Depends on Guide 1:** the richness metric uses the migrated diagnostics
(`variety.*`) from the testbench. Prefer to run this after Guide 1 category D
lands; if not yet available, the design must still specify the measurement.

---

```
============================ COPY FROM HERE ============================
TASK — build the minimal falsifiable "world-state richness" experiment. This is
DESIGN-FIRST: you stop for owner approval before building engines.

AUTHORITATIVE DOCS (read first):
- docs/decisions/003-approach-survey-and-world-state-gap.md  (the bet + the test)
- docs/current/SPATIAL-GENERATION-ARCHITECTURE.md            (existing engines)
- docs/current/CONVENTIONS.md                                (coding rules)

THE QUESTION TO SETTLE (do not lose sight of it): with our architecture
(deterministic engine + LLM "brief"), does a bigger local model (27B) produce a
VISIBLY and MEASURABLY richer scene than a small one (4B) for large-scale
environments — or do they collapse to the same output because the brief/engine is
a lossy bottleneck? ADR-003 commits to settling this EMPIRICALLY before scaling
the macro frontier. The experiment must be able to return "no difference" — if it
can't fail, it's worthless. Do NOT tune anything to flatter the 27B.

THE SHAPE (from ADR-003): a persistent SHARED SPATIAL WORLD-STATE (a heightfield +
masks/zones: water, slope, buildable, proximity-to-road) that deterministic
engines READ and WRITE so they coordinate, and a brief that can address SPACE
("denser near the river"), not just flat globals. The minimal slice: terrain +
ONE forest engine that reads slope/moisture + a road that carves terrain and
updates the masks.

GROUND RULES:
1. BRANCH: `git checkout -b exp/world-state-richness`. Never commit to main,
   never merge. Push + report; owner reviews.
2. Keep `scripts/check.sh` GREEN after every change (ruff + format + length gate);
   new files ≤500 lines, match the spatial engines' style. Behavior-preserving
   for existing engines — this is ADDITIVE (a new slice), not a rewrite of
   room/building/scatter/wfc/voronoi.
3. The stack runs as systemd services; screenshots need a live godot-ai session.

=== PHASE A — DESIGN PROPOSAL (build NOTHING yet; stop at the end) ===
Read the existing spatial engines (engine/devforge/spatial/) and the pipeline,
then write a concrete design proposal to
docs/reviews/world-state/DESIGN-PROPOSAL.md covering:
  1. WORLD-STATE representation — concrete data structure for the heightfield +
     masks (water/slope/buildable/near-road). How it is stored, passed between
     engines, and serialized.
  2. ENGINE COORDINATION — the read/write contract: terrain writes the
     heightfield; the forest engine reads slope+moisture to place/thin trees; the
     road engine carves the heightfield and writes a near-road mask. Show the
     interfaces, no implementation.
  3. BRIEF SCHEMA EXTENSION — how the LLM brief addresses space ("denser near the
     river", "thin the forest by the road") within the existing GBNF/brief
     approach. Keep it grammar-constrained.
  4. THE MINIMAL SLICE — the exact smallest build that tests the bet: terrain +
     one slope/water-aware forest + a carving road. Nothing more.
  5. MEASUREMENT PROTOCOL — the falsifiable test: the SAME deliberately-WIDE
     prompt run on qwen 4b and 27b, repeated N times (skip_cache=True), producing
     (a) Godot editor screenshots for the eyeball A/B and (b) a typed richness/
     diversity metric via the testbench (variety.*). State the explicit KILL
     CRITERION up front: if the 4B and 27B outputs are visually indistinguishable
     AND the metric shows no separation, the bet FAILS and the recommendation is
     to pivot the LLM to the narrative layer (per ADR-003). Define "visibly
     different" and the metric threshold BEFORE running.
Then STOP. Reply with the proposal path. Do not write engine code until the owner
approves the design.

=== PHASE B — BUILD + RUN (only after the owner approves Phase A) ===
Implement exactly the approved minimal slice + the measurement harness. Wire the
new engine(s) behind a per-request planner route like the existing spatial
engines. Run the A/B (4B vs 27B, N repeats), save screenshots + the artifact, and
write docs/reviews/world-state/RESULT.md with: the two screenshot sets side by
side, the richness metric per model, and a plain verdict — "richness scales
(bet holds)" or "indistinguishable (bet fails, pivot)". Report honestly even if
the answer kills the approach.

REPORT: push the branch; reply with the branch name + one-line status (e.g.
"design proposal written, awaiting approval").
============================= TO HERE ==================================
```

---

## After this
The owner + Claude review the Phase-A design before any build. The Phase-B result
is the **decision point for the whole project's central bet** — if richness is
invisible, ADR-003's pivot triggers; if it scales, the macro frontier
(mountains/forests/cities/weather) gets built on the world-state pattern with
evidence behind it.
