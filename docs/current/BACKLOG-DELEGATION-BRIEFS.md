# Backlog — Delegation Briefs (prompts for the CLI AI)

**Date:** 2026-06-20 (rev 2 — answers Q1–Q15 folded in)
**How to use:** hand the CLI AI one **package** at a time, in order within a section. READY packages need
no further input. Section C packages are **design-first** (each gets its own brainstorm→spec→plan) and
several wait on the OPEN-QUESTIONS-v2 answers at the bottom.

## Standing rules (paste once at the top of each handoff)

> Read `AGENTS.md` + `docs/current/SLICE1-RPG-FETCH-QUEST.md`. Work on a **dedicated branch/worktree**
> (Q13 — isolate from now on; the in-place runs caused stale-build bugs). TDD red→green. Foundry tests:
> `cd foundry && .venv/bin/python -m pytest tests/ -q`. **Godot-in-the-loop is the gate**: after any
> change under `foundry/godot_template/` or to `scene_compiler.py`, scaffold a build, run
> `godot --headless --path <build> --quit`, grep stderr for `SCRIPT ERROR|Parse Error|Failed to load`
> (must be 0), and **regenerate builds after shell-script changes**. **Eval-first (Q15):** every package
> that changes generation adds/extends an `foundry/eval/` signal so regressions self-surface. Single-line
> GBNF only. Never mutate the real `asset_lexicon.json` in tests (`/tmp` copy). qwen stochastic → live
> claims run twice. Honor the manifest contract (`room_size, yaw, surface, decor`). Never touch
> `addons/godot_ai`. Commit per task with commit-proof.

---

# SECTION A — DONE ✅ (CLI AI, ~180 py + 7 godot tests green)
P-A player scale, P-B HUD/UX, P-C-1 highlight, P-D smoke-probe gap, P-H-1 seed, P-K eval oracle,
P-L-1 parallel builds.

---

# SECTION B — READY NOW (answers folded in)

## P-E · Carryable items + target realism  [gen+shell · M-L] — Q1=C, Q2
> **Goal:** the fetch target becomes a small **carryable item** that the NPC **names precisely** —
> resolving "the trinket is actually a cabinet." Two halves:
>
> **(1) Carryable generators (10 items).** Add small generators built from primitive boxes/cylinders
> (mirror `rug`/`painting` thin-box pattern): **key, book, cup, gem, bottle, scroll, coin-pouch,
> candle, dagger, ring**. Each: `_build_*_geometry` + `_BUILDERS` + `compiler.GENERATORS`/`PARAM_RANGES`
> + grammar branch + lexicon envelope + live gate-passing build test. They are **`decor=false`,
> pickable**, small (≤0.3 m), `category` ∈ the new set. *(Confirm/adjust the 10 via NQ1.)*
>
> **(2) Placement + target.** Extend `room_layout`: carryables get `surface:"on"` placed on a random
> furniture top (furniture y-top + small offset), or on the floor if no furniture — "can be on furniture
> but doesn't have to" (Q2). Extend `RoomPlanner` grammar so it may emit carryables. Change
> `_cmd_quest`/behaviour-gen so the **quest target is a carryable** (not furniture); the NPC dialogue
> names it by category (+material): "find my brass key on the table." Furniture stays pickable scenery.
> **Eval:** add a "target-is-carryable + reachable + named-in-dialogue" signal. **Verify:** headless
> playthrough — pick the wrong carryable → wrong line; right one → thank → win. Commit-proof, run-twice.

## P-F · 20 stress-test prop generators  [gen · M] — Q3, gated on **NQ2** (selection)
> **Goal:** add ~20 new prop generators chosen to **stress-test the generator** across axes
> (size extremes, thin/flat, tall/narrow, many-parts, aspect ratios, hollow/closed). Final list +
> stress strategy = **NQ2**. Per item: builder + `_BUILDERS` + `GENERATORS`/`PARAM_RANGES` + grammar +
> lexicon envelope + **live gate-passing build test**. **Eval:** extend the gate-pass corpus so each new
> generator is covered and a regression in any one self-surfaces. Build in batches of ~5, commit each batch.

## P-G · Material & visual richness  [gen · M] — Q5=all, Q7 (default), gated on **NQ3** (image source)
> 1. **Painting content modes (all, Q5):** `blank | solid | pattern | image`, chosen per-asset.
>    `pattern` = a procedurally generated canvas texture (bake like existing materials). `image` source
>    = **NQ3**. 2. **Per-theme lighting mood (Q7 default = deterministic):** derive light color/energy
>    from theme keywords in the prompt (warm forge vs cool hermit) in `scene_compiler`. 3. **Fabric
>    material family** for rugs (extend `materials.py` + color builder). Each part TDD'd + headless-verified;
>    add an eval signal for "painting mode honored" + "theme→light deterministic."

---

# SECTION C — DESIGN-FIRST SLICES (brainstorm→spec→plan each; sequenced)

> These are too big for a one-shot prompt. Do them **in this order** (Q7-systems / your priority), each
> as its own slice. Several need an OPEN-QUESTIONS-v2 answer before the spec.

**C-0 · General room rules / control layer**  — Q6+Q13, gated on **NQ10**
> "Some variety but more control." A deterministic theme/constraint layer over RoomPlanner (required
> props, palette bands, density min/max, NPC clearance) so output is steerable. Do this EARLY — it
> shapes every later room. (Eval: variety-within-rules metric.)

**C-1 · Audio (synth generator)**  — Q4=C, gated on **NQ4**
> A generation-first SFX generator (footstep/pickup/win/combat). Approach = NQ4.

**C-2 · Inventory**  [systems #1]
> Carry/hold multiple items, simple UI, select-to-deliver. Builds on P-E.

**C-3 · NPC quest-state persistence**  [systems #2] — gated on **NQ9**
> idle→given→done survives; mechanism (world-model vs JSON) = NQ9.

**C-4 · Multiple NPCs / multiple quests**  [systems #3]
> >1 NPC + quest per room; behaviour-gen per NPC; HUD tracks active quest.

**C-5 · Multi-room + leave-to-win**  [systems #4 + Q11/Q14] — gated on **NQ8**
> Generated rooms linked by doors; win by delivering AND/OR leaving via exit. Structure = NQ8.

**C-6 · NPC pathfinding / idle-wander**  [systems #5]
> NavMesh + simple wander/approach.

**C-7 · Camera: first/third-person toggle**  — Q9=both, gated on **NQ5**
> Runtime toggle + a visible body that reads in both. Mechanism = NQ5.

**C-8 · Basic combat**  — Q10=yes, gated on **NQ7**
> Player melee + simple enemy with health. Scope = NQ7. (Eval: "enemy defeatable / win reachable.")

**C-9 · Rigged animated humanoid NPC (basic)**  — Q10=yes, gated on **NQ6**
> The frontier: replace the primitive NPC body with a rigged GLB + a single idle anim, gate-passing and
> animating in Godot headless. Scope = NQ6. Highest risk — its own slice, eval-gated.

---

# OPEN QUESTIONS v2 — see chat for options + pro/con (NQ1–NQ10)
NQ1 carryable list · NQ2 20-prop stress strategy · NQ3 painting image source · NQ4 audio synth approach ·
NQ5 camera toggle mechanism · NQ6 humanoid rig scope · NQ7 combat scope · NQ8 multi-room structure ·
NQ9 persistence mechanism · NQ10 room control-rules shape.
