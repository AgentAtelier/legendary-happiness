# Futurelog — designed & parked

Threads that are **designed/specced but not yet in active implementation.** Each links its spec. The
discipline: finish the current epoch's work before opening a parked thread, so we stop dragging un-built
work behind every brainstorm.

> **Epoch shift (2026-06-25):** M1 (the "engine" epoch) is essentially complete. The new north star is
> the **World Engine** — see **`WORLD-ENGINE.md`** (canonical). Several previously-parked threads are now
> **sub-projects of the World Engine**, not standalone items.

## Active north star

| Thread | State | Spec / source |
|---|---|---|
| **World Engine** (stateless scene generator → stateful, growing, editable persistent world; consensus architecture + named walls + build order) | Designed; documentation done; implementation not started | **`WORLD-ENGINE.md`** |

## Folds INTO the World Engine

| Thread | Now is… | Source |
|---|---|---|
| **Iterative editing** | World Engine sub-projects (a)+(b): human JSON-patch machinery, then NL→patch. The thing the user wanted "sooner." | `WORLD-ENGINE.md` §6 |
| **Cohesion Contract** | World Engine sub-project (c) / Wall W4: coherence enforced as hard constraints + validators. | `docs/superpowers/specs/2026-06-24-cohesion-contract-design.md` |
| **Exterior (#3)** | "spaces + portals" lands on the World-DAG (not the old disposable outdoor path). Groundwork (terrain/biome/scatter/exterior_planner + Blender generators) already built. | `WORLD-ENGINE.md` §6; BACKLOG §C |
| **CP-3 + CP-4** (geometry normalization, NPR roof) | Later coherence/style facets of the Cohesion Contract. | BACKLOG §B |

## Parked — its own thread (NOT folded in)

| Thread | State | Approach notes |
|---|---|---|
| **UX / Forge Hub redesign** | Parked; its own careful process (NOT the engineering survey) | **See approach below.** |
| **Capture-harness headless-GL fix** | Diagnosed; honesty fixes landed | ROADMAP 0.11 — its main consumer (Cohesion auto-exposure probe) is parked. |

### UX / Forge Hub redesign — approach notes (so a cold session can pick this up)

**Why it matters:** the current `forge-hub` is an *operator's console* (model swapping, VRAM, stack.env)
— a workshop for the person *building* Forge, not a front door for whoever *uses* it. It "reads as typical
AI slop." The risk we're eliminating: building a technically-impressive tool nobody would actually use. A
genuinely usable, non-slop UX is the **proof** the hard problem is solved.

**Who/what (locked in this conversation):**
- **User = a maker/creator** who builds & owns playable 3D output, refining and extending it over time.
- **Unit of creation = a growing persistent sandbox world** (→ this is *why* the World Engine exists).
- **The maker journey (draft, 7 beats):** 1) first spark (seed prompt → first space generates — the reveal
  hook); 2) step inside (first-person presence — the payoff); 3) **refine** (the core loop — "make it
  dusk," "bigger throne"); 4) **extend** (linked new spaces — the world grows); 5) **populate** (NPCs,
  simple quests); 6) **return** (it's all still there — persistence = retention); 7) **show it off**
  (ownership + spectacle). The redesigned hub is the shell: a **world map** (graph of spaces), a **prompt
  bar** (create/refine/extend), **live preview/play**, **library + version history**.

**How we will approach it (explicitly different from the engineering survey):**
- It is a **separate, careful, anti-slop process** — UX is "a very complicated subject to get right."
- **Leverage Claude web's design feature** for the actual mockups/visuals.
- **Research real UX fundamentals** first — color palettes, layout, interaction patterns, reference
  products — so the design has a foundation, not vibes.
- When picked up: the deliverable is a UX brief (journey + anti-slop constraints + what to research),
  feeding the Claude-design work — NOT a fan-out survey of other AIs.
- Iterative editing (World Engine a+b) can be **prototyped on human-authored patches** before NL is solid,
  so the UX can be exercised early.

## Open dead-end (further out)

| Thread | State | Source |
|---|---|---|
| **Capability layer** | General game-logic generator beyond fetch-quest; relates to World Engine W5 (meaning/playability). | Q1 / BACKLOG §A |

**Discipline:** new brainstorms produce a spec + a futurelog row, not implementation, unless on the
critical path of the active epoch.
