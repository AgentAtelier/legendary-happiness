# Brainstorm Prompts for External AIs — "easiest → hardest things we could build"

**Goal:** gather divergent, *grounded* idea-lists from several AIs, by domain, to compare against our own.
**How to use:** give each AI the **SHARED CONTEXT** block, then **ONE domain prompt**. Use a **fresh chat per
domain prompt** (and per AI) — these are divergent brainstorms; you don't want anchoring on a prior answer or
context bloat. Ask each to use the **OUTPUT FORMAT** so the lists are comparable.

---

## SHARED CONTEXT (paste at the top of every brainstorm chat)

> **The project — "Forge": a generation-first RPG sandbox.**
> A Python "foundry" generates a small, playable 3D RPG from a text prompt, end to end:
> 1. **Assets** — parametric Blender generators build ~37 categories of GLB props (furniture, small
>    carryable items, decor, plus deliberate stress-test shapes), each with a procedural material/texture
>    bake, gated for quality (watertight, poly budget, scale envelope). A single **category registry** is the
>    source of truth; assets are built **on demand** and cached.
> 2. **Rooms** — a local LLM (qwen, run locally, stochastic) picks a room size + a themed set of props within
>    a **deterministic control layer** (per-theme tables: required props, palette, density bands + global
>    guards). Deterministic layout places furniture on a grid, carryables on surfaces, paintings on walls,
>    rugs as underlays; guarantees a winnable target.
> 3. **Quests** — a second grammar-constrained LLM call generates fetch-quest behavior: NPC role, a target
>    (a pickable carryable), and 4 dialogue lines (greet/ask/wrong/thank), validated/repaired deterministically.
>    Supports **multiple NPCs**, each with a distinct quest.
> 4. **Game** — compiles to a **disposable Godot 4.7 project** (regenerated per run): first-person player
>    (third-person via a build flag), raycast interaction, **multi-item inventory** (pick up / cycle / drop),
>    NPC dialogue (space-to-advance), procedural **audio** (in-engine synth), lights/walls/materials, a win
>    screen. NPC **quest-state persists** via a world-model transactional log (survives reload).
>
> **How we work:** one human developer + AI coding assistants. TDD, an **eval harness** with deterministic
> "signals", and a non-negotiable **Godot-in-the-loop** gate (a generated build must actually open and play).
> **Hardware:** one local 16 GB GPU running qwen; Blender; Python; Godot 4.7. No cloud LLM.
>
> **Philosophy:** (a) **generation-first** — generate outputs via the pipeline, don't hand-author specific
> game content; hand-crafting is a documented last resort. (b) **Broad & modular** — there is no fixed game;
> the open-world RPG is a *lighthouse*, not a spec. When a choice is narrow-vs-broad, go broad. Build every
> subsystem so it **stands alone and could be spun out as its own product** (the asset foundry, the room
> generator, the quest generator, etc.). (c) We are in an **exploration phase**: include things, keep options
> open, and find the *gold* — features with outsized value or novelty for the effort.
>
> **Already built:** assets+materials, themed room-gen, fetch-quest + multi-NPC dialogue-gen, generate-on-demand,
> disposable Godot scaffolding, first/third-person shell, pickup+inventory+drop, persistence, procedural audio,
> eval harness. **Planned next:** multi-room graph, NPC pathfinding, basic combat, a rigged animated humanoid NPC.

## OUTPUT FORMAT (ask every AI to follow this)

> Return a single list, **ordered easiest → hardest to implement on this stack**. For each item:
> `name — [S/M/L effort] — what it is in one line — value/novelty (and: could this be "gold"? why) — what
> it concretely touches in the pipeline (assets / room-gen / quest-gen / Godot shell / eval).`
> Be specific to this generation-first + local-LLM + Godot stack. Prefer ideas that compose with what exists.
> Aim for 12–20 items. Flag your top 3 "gold" bets and your single riskiest-but-highest-upside idea.

---

## DOMAIN PROMPT 1 — Core gameplay loops & mechanics
> Within **core gameplay** — the verbs, moment-to-moment loops, progression, win/fail, and how the player
> interacts with items and the world — list easiest→hardest things we could build. Think beyond fetch:
> what turns the existing pickup/inventory/quest pieces into a *game*? Consider item interactions
> (use/combine/throw/place), objectives, rewards, difficulty, and failure states.

## DOMAIN PROMPT 2 — Procedural generation & content depth
> Within **procedural generation** — assets, rooms, quests, and variety — list easiest→hardest things we could
> build. Where can generation go deeper or broader: new asset kinds, richer materials/textures, smarter/themed
> layout, generated quest *types* beyond fetch, generated narrative/structure, controllability vs variety?
> This is the heart of "generation-first" — what's the frontier worth pushing?

## DOMAIN PROMPT 3 — NPCs, dialogue & character AI
> Within **NPCs and characters** — list easiest→hardest things we could build. Today NPCs give a fetch quest
> with 4 canned lines. Consider: richer/branching dialogue, LLM-driven *live* conversation, NPC personalities,
> behaviors/schedules/needs, relationships, memory, and how far a small local LLM can believably carry a
> character. Where's the novelty, and where are the failure modes of leaning on a stochastic local model?

## DOMAIN PROMPT 4 — World structure & exploration
> Within **world & exploration** — list easiest→hardest things we could build. Today it's a single generated
> room. Consider: doors/locks/keys, multi-room layouts (graph/grid), traversal, an explorable world, world
> persistence/state, points of interest, secrets, and how room-gen scales into something you *explore*.

## DOMAIN PROMPT 5 — Game feel, presentation & UX
> Within **feel, presentation & UX** — list easiest→hardest things we could build. Consider: camera, controls
> (sprint/crouch/feedback), audio depth, lighting/mood/post-processing, UI (quest log, tooltips, menus, map),
> "juice"/feedback, accessibility, and anything that makes a *generated* room read as a place worth being in.

## (Optional) DOMAIN PROMPT 6 — Pipeline, eval & extractability
> Within **pipeline & tooling** — list easiest→hardest things we could build. Consider: stronger eval signals,
> regression/variety metrics, debugging/inspection tools, determinism/seeding, performance (parallel builds,
> caching), and — per our "modular" philosophy — what it would take to **extract a subsystem** (e.g. the asset
> foundry or room generator) as a standalone product/tool.
