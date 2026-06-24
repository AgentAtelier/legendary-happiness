# Forge Roadmap → Milestone M1

_2026-06-24. Synthesizes the 5-round audit (`AUDIT-00-SYNTHESIS.md`) + `BACKLOG.md` into a
prioritized plan toward a milestone from which we choose direction. Delegation is assigned per
item. (The prior capability roadmap is archived at `ROADMAP-2026-06-14-capability-archive.md`.)_

## Delegation model (three tiers)

| Tier | Agent | Budget | Owns |
|---|---|---|---|
| **O** | **Opus (orchestrator)** | tokens (scarcest) | **writes the specs/prompts**, decisions, design forks, module boundaries, final review of risky/architectural/visual, Blender bakes + heavy/long test runs + Godot visual verification, triage |
| **D** | **DeepSeek V4 Pro** | 5 h/day (default implementer) | TDD implementation, mechanical/structural refactors, broad investigation |
| **M** | **MiniMax M3** | time (overflow implementer) | same as D; used when O tags a task as a good fit to take pressure off D's clock |

**Constraint:** only ONE CLI agent runs at a time (serialized by the user) — so D/M are best-fit
alternatives, not parallel. **Pipeline:** O writes the prompt → D (or M) implements TDD → O reviews
+ verifies (Blender/visual/heavy tests are always O). O tags a prompt "good for MiniMax" when it fits.

---

## Phase 0 — Correctness & Honesty (fast, highly parallel)

Make the system correct and *loud*. Mostly independent → run M and D in parallel.

| # | Item | Source | Owner |
|---|---|---|---|
| 0.1 | **C4 dialogue validator** — require the target's category word in `ask`+`thank`; demote the verb-only fallback to a soft heuristic + Decision Point | C4/T9 | M |
| 0.2 | **C2 bake Y→Z coord** — remap interior-light `pos` at the Blender boundary `(x,z,y)` | C2/T7 | M writes · **O verifies bake** |
| 0.3 | **Loud failures** — Decision Point (severity=error) at every silent fallback (bake→tier0, shell→box, plan→canned) | R1 | M |
| 0.4 | **Guard tests** — palette-recolor, coord-roundtrip, dialogue-category, bake-cache-palette, + a cross-process/PYTHONHASHSEED determinism test | T5–T9/T19 | M writes · **O runs Blender/Godot parts** |
| 0.5 | **Probe honesty** — rewrite `probe_*.gd` to drive `interaction.gd.on_interact()` with real input; delete the reimplemented raycast + forced state mutations | T1/T2 | **O designs** · M implements · **O verifies headless** |
| 0.6 | **Palette harmony + wiring** — grey anchors stay grey (don't override anchor saturation); pass `palette=` through the build path | prompts A/B | M |
| 0.7 | **Flaky test + explicit Blender markers** — DI instead of `importlib.reload`; mark the real Blender tests explicitly (retire the source-sniff heuristic) | T10/T11 | M |
| 0.8 | **Determinism constants + complete cache keys** — `_constants.py` (seed 42, sun bases); add palette + GLB-content hash to `bake_key` / room_shell key | D4/D5/C1/D1/P2 | M |
| 0.9 | **Hygiene** — `TAG-LEGEND.md`; add `ruff`/`pyflakes` lint (auto-fixes dead imports + hint style); standardize `logging` | Q5/Q6/Q19/Q10/Q12 | M |
| 0.10 | **Brief+seed+plan persistence** — write the Brief/seed/plan as a re-loadable artifact per build (insurance for iterative editing) | BACKLOG §A | D drafts · M implements |

## Phase 1 — Decompose the realization layer (KEYSTONE)

Do **after** Phase 0's guard tests (0.4) + probe honesty (0.5) — they are the safety net for this refactor.

| # | Item | Source | Owner |
|---|---|---|---|
| 1.1 | **`tscn_writer.py`** — shared `.tscn` emission primitives (ext_resource/sub_resource/node/transform/light/wall) | A2/D5/A20 | **O specs boundaries** · M implements |
| 1.2 | **Unified bake contract** — one `build_scene_desc()` + `bake_and_apply()` in `lighting_bake.py`; both compilers + scaffold call it | A4 | D drafts · O approves · M implements |
| 1.3 | **Collapse outdoor paths** — one canonical `compile_exterior`; delete `scene_compiler`'s outdoor branch + duplicate scatter | A5/C3/L2 | **O decides canonical** · M implements |
| 1.4 | **Split `scene_compiler.py`** → ~6 focused modules; `compile_scene` becomes a <300 LOC orchestrator | A1/Q1/Q3/Q4 | **O designs module boundaries** · D drafts migration plan · M implements |
| 1.5 | **`_resolve_lighting()`** — collapse the 6× lighting cascade into one flat context dict | Q4/P11 | M (rides 1.4) |

## Phase 2 — Build-time speed (the iteration UX)

| # | Item | Source | Owner |
|---|---|---|---|
| 2.1 | **Single Godot import** — copy all assets (incl. shell.glb + class textures) before one `_pre_import`; drop the second pass | P1/A7 | M · **O verifies** |
| 2.2 | **Batch Blender spawns** — one Blender invocation per build batch instead of ~31 | P13 | **O designs** · M implements · **O verifies** |
| 2.3 | **Bake caching** — persist UV2 per asset; key bakes on manifest hash; `FORGE_BAKE_TIER` dev override | P3/P14/P16 | M · **O verifies bakes** |
| 2.4 | **Resource caps** — Blender pool ≤2 + RSS guard; navmesh/scatter footprint caps | P7/R2/R5/P17 | M |

## Phase 3 — Showcase correctness (Milestone gate)

| # | Item | Source | Owner |
|---|---|---|---|
| 3.1 | **Triplanar gating** — only stone/wood/rock/soil; UV-map metal/fabric/foliage | P4 | M |
| 3.2 | **Drop dead NPC rig nodes** (verify `npc.gd` doesn't drive them first) | A12/P9 | **O verifies npc.gd** · M implements |
| 3.3 | **Shadow budget** — shadows only on planned lights, not the grid | P5 | M |
| 3.4 | **Lighting re-tune** (after 0.2 C2 + 3.3 + 0.6 harmony) | BACKLOG §C | **O (visual) + user** |
| 3.5 | **Two-palette recolor + lit render** — the demonstrable-correctness artifact | T6 | **O renders · user judges** |

---

## ▶ MILESTONE M1 — "Honest, clean, fast realization + a correct showcase scene"

At M1: the realization layer is decomposed and shared, failures are loud, determinism is tested,
builds are ~2× faster, and the study scene is demonstrably correct (lit right, playable, recolorable
under two palettes). **Step back here and choose direction.**

## Post-M1 — Direction choices (each its own O-brainstorm → D-spec → M-build)

| Thread | Note | Source |
|---|---|---|
| **Iterative editing** | The strategic north star; Brief-persistence (0.10) is its prerequisite. Brainstorm first. | BACKLOG §A |
| **UI definition** | Brainstorm to decide WHICH UI (engine-driver for prompt→iterate, vs in-game HUD, vs hub), then build. Ties to iterative editing. | BACKLOG §D |
| **Exterior (#3)** | Now lands cleanly on the decomposed realization layer + collapsed outdoor path. | BACKLOG §C |
| **CP-3 + CP-4** | Geometry/neural normalization, then the NPR stylized roof + post. | BACKLOG §B |
| **Capability layer** | The hardest dead-end: a general game-logic generator beyond fetch-quest. | Q1 / BACKLOG §A |

---

**Sequencing:** Phase 0 is parallel and unblocks judgment; Phase 1 is the keystone, gated on
0.4+0.5; Phase 2 overlaps Phase 1; Phase 3 gates M1. Fix-first within Phase 0: **0.1 (C4)** and
**0.2 (C2)** ship correct gameplay/lighting immediately.
