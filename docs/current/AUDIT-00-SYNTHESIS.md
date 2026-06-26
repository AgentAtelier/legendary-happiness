# Audit Synthesis — Orchestrator's Observations

_2026-06-24. After 5 rounds (~124 findings across architecture, correctness/determinism,
quality, tests, performance). This is the cross-cutting read — root patterns, not a re-list._

## Verdict first

**The foundation is sound; the debt is concentrated.** Nothing in 124 findings says "the
architecture is wrong." The Spine (prompt → Interpreter → Brief → deterministic planners →
compiler → scaffold → Godot + build report), the content-addressed caches, and the
deterministic-planner pattern are all validated. The debt lives almost entirely in **one place**
(the realization layer) and in a handful of **repeating patterns**. That's the best possible audit
outcome: addressable, not existential.

## The root patterns (each explains many findings)

1. **The realization layer is the epicenter.** `scene_compiler.py` (2,303 LOC) + its twin
   `exterior_compiler.py` are the source of a plurality of findings in *every* round: god-file (A1),
   duplicated `.tscn`/bake emission (A2/A4), three divergent outdoor paths (A5/C3/L2/P6), the Y→Z
   bake bug (C2), dead NPC rig nodes (A12/P9), triplanar-on-everything (P4), the 18-light shadow
   grid (P5), O(N²) separation (P8), the 6× lighting cascade (Q4/P11), magic-42 seeds (D4).
   **Decomposing it (A1+A2+A5) is the single lever that makes a dozen other findings tractable** —
   and it's a precondition for the iterative-editing future (a clean realization layer is what a
   "re-realize" loop calls repeatedly).

2. **Silent degradation is systemic — the root cause of "green tests / red game."** The system
   prefers to ship a quietly-degraded result over surfacing a failure: probes reimplement game
   logic so the real path is never tested (T1/T2), fallbacks degrade with no Decision Point (R1),
   cache-key gaps serve stale bakes silently (C1/D1/P2), HIP→CPU bake falls back silently (P10), the
   dialogue validator passes unplayable quests silently (C4). **This is the most dangerous pattern**
   — it's *why* "tests pass" hasn't meant "it works." The fix is a principle, not 20 patches: every
   fallback emits a Decision Point (the machinery already exists, it's just unused at failure
   sites), and the Godot test must drive the *real* `interaction.gd` path, not a reimplementation.

3. **The Python-build → Godot-runtime seam is hand-maintained and unguarded.** The JSON sidecar
   contract drifts (A11/R3, already broke twice), runtime ignores the dead skeleton nodes the build
   emits (A12/P9), the coordinate convention splits Y-up/Z-up across the seam (C2). Two engines, no
   enforced contract. Needs a schema + a real headless-load test.

4. **Determinism is asserted but under-protected.** The project's #1 stated value has the *weakest*
   test coverage: cache keys omit inputs (C1/D1/P2), `seed=42` is hardcoded in 3 places, there is no
   cross-process / PYTHONHASHSEED test (T5/T19), float formatting is non-canonical (D3). Small to
   fix (a `_constants.py`, complete cache keys, one cross-process test) but **load-bearing for
   iterative editing**, which depends entirely on deterministic re-realize.

5. **Build-time is death by a thousand Blender spawns.** Double `godot --import` per build (P1),
   6 spawn entry points → ~31 spawns per showcase batch (P13), per-bake re-unwrap (P3/P14), bake
   cost (P3), unbounded pool OOM (P7). For an engine whose value is "prompt → scene fast" and that
   wants *iterative* editing, **build-time wall-clock IS the UX** — and right now it's tens of
   minutes of mostly-redundant startup. This is the bottleneck the iterative-editing vision dies on
   if unaddressed.

## What I'd actually fix first (cutting across the audit's severity labels)

Ranked by my judgment, not the per-round Critical/High counts:

1. **C4 — dialogue validator** (ships winnable-but-unplayable quests). One line. Ships broken
   gameplay *today*. Do immediately.
2. **C2 — bake Y→Z coordinate bug** (mine). One line. Degrades every lit scene; the "lighting
   overshoot" you saw is most likely C2 + P5 (18 shadow lights) + the palette over-saturation, not a
   real lighting-design problem. Fix before we re-judge lighting.
3. **The silent-degradation principle** — wire Decision Points into the ~4 fallback sites (R1) and
   rewrite the Godot probes to drive `interaction.gd` (T1/T2). This is the confidence fix; without
   it we keep flying blind.
4. **Decompose `scene_compiler` (A1+A2+A5)** — the structural keystone; unlocks ~a dozen findings
   and is the precondition for iterative editing.
5. **Determinism hardening** (`_constants.py`, complete cache keys C1/D1/P2, one cross-process test)
   — small, and the substrate the iterative future stands on.
6. **Build-time speed** (P1 single-import, P13 batched Blender, bake caching P3/P16) — the iteration
   UX; the lever that makes everything else feel fast.

## My own observation (beyond the findings)

The audit *empirically confirms the Q1 strategic dead-ends* we'd already reasoned about: the
realization layer, the single-scene model, the Python-Godot seam, the narrow capability layer. It's
independent validation that we know where the architecture must evolve. And it reframes the
showcase: before chasing more visual polish, the highest-value move is to **fix C4+C2, make failures
loud, and decompose the realization layer** — because a clean, honest, fast realization layer is
the thing every future thread (exterior, NPR roof, iterative editing, UI) builds on top of.

→ Next: fold these + the BACKLOG into a prioritized **roadmap with a defined milestone** (UI scoped).
