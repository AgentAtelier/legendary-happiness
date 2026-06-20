# Backlog — Finalized Prompts (paste-ready for the CLI AI)

**Date:** 2026-06-20 (rev 3 — NQ1–NQ10 folded in)
**Order:** B-prompts first (small, parallel-safe), then C-slices in the agreed sequence. Each C-slice is
larger — the prompt tells the CLI AI to produce a short spec+plan, get it reviewed, then implement.

## Standing rules (paste at the top of every handoff)
> Read `AGENTS.md` + `docs/current/SLICE1-RPG-FETCH-QUEST.md`. **Dedicated branch/worktree** (Q13). TDD
> red→green. Tests: `cd foundry && .venv/bin/python -m pytest tests/ -q`. **Godot-in-the-loop gate:** after
> any `godot_template/`/`scene_compiler.py` change, scaffold a build, `godot --headless --path <build>
> --quit`, grep stderr `SCRIPT ERROR|Parse Error|Failed to load` = 0; regenerate builds after shell changes.
> **Eval-first (Q15):** every generation change adds/extends a `foundry/eval/` signal. Single-line GBNF.
> Never mutate real `asset_lexicon.json` in tests. qwen stochastic → live claims twice. Manifest contract:
> `room_size, yaw, surface, decor`. Never touch `addons/godot_ai`. Commit per task with commit-proof.

---

# READY PROMPTS

## P-E · Carryable items + target realism  [Q1=C, NQ1=a]
> Add 10 small **pickable** carryable generators (≤0.3 m, `decor=false`): **key, book, cup, gem, bottle,
> scroll, coin-pouch, candle, dagger, ring** — built from primitive boxes/cylinders (mirror the rug/painting
> thin-box pattern): each = `_build_*_geometry` + `_BUILDERS` + `compiler.GENERATORS`/`PARAM_RANGES` +
> grammar branch + lexicon envelope + **live gate-passing build test**.
> Then: extend `RoomPlanner` grammar to allow carryables; `room_layout` places them `surface:"on"` on a
> furniture top (y-top + offset) or floor if none (Q2); change `_cmd_quest`/behaviour-gen so the **quest
> target is a carryable**, named in dialogue by category(+material) ("find my brass key on the table").
> Furniture stays pickable scenery. **Eval:** "target-is-carryable + reachable + named-in-dialogue" signal.
> **Verify:** headless playthrough — wrong carryable → wrong line; right → thank → win. Run-twice.

## P-F · 20 stress-test prop generators  [Q3, NQ2=C hybrid]
> Add these 20 generators (≈12 themed-useful + ≈8 deliberate edge-cases). Per item: builder +
> `_BUILDERS` + `GENERATORS`/`PARAM_RANGES` + grammar + lexicon envelope + **live gate-passing build test**.
> Build in batches of 5, commit each. Extend the eval gate-pass corpus to cover every new generator.
>
> **Themed-useful (12):** barrel, crate, chest (lidded box), stool, bench, wardrobe (tall closed),
> desk (table variant), lantern (tall thin + emissive), pot/urn, weapon-rack (tall narrow frame),
> pillar, planter.
> **Edge-case stressors (8):** huge_table (size-max), tiny_stool (size-min), partition (very thin + large
> area), tall_post (very tall narrow), wide_platform (wide + flat), many_leg_table (8 legs — part count),
> ladder (many thin rungs — part count + thinness), L_bench (asymmetric/aspect).
> **Goal of the stressors:** each pushes one gate/topology axis; if any fails the gate, that's a generator
> bug worth a ticket — do NOT loosen the gate to pass them without justification.

## P-G · Material & visual richness  [Q5=all, NQ3=a, Q7=default]
> 1. **Painting modes (all):** `blank | solid | pattern | image`; both `pattern` and `image` are
>    **procedurally generated** canvas textures (NQ3=a — no external files), baked like existing materials.
> 2. **Per-theme lighting (deterministic):** derive `DirectionalLight3D`/ambient color+energy from theme
>    keywords in the prompt (warm forge vs cool hermit) in `scene_compiler`.
> 3. **Fabric material family** for rugs (extend `materials.py` + a `_fabric_color_nodes` builder).
> TDD + headless-verify each; eval signals: "painting mode honored", "theme→light deterministic & stable".

---

# DESIGN-FIRST SLICES (sequenced — spec+plan then implement)

## C-0 · Room control rules / theme tables  [Q6+Q13, NQ10=c]  — DO FIRST
> Build a deterministic **control layer** over RoomPlanner: per-theme **tables** (theme → required props,
> palette bands, density min/max, must-include) **plus** global **guards** (NPC clearance, min/max density,
> at-least-one-seat). The LLM fills within the table; guards clamp + emit Decision Points. Seed themes from
> **R4** (see chat). Keep stochastic variety *within* the rules. Eval: "variety-within-rules" + "guards
> never violated" signals. (This shapes every later room — land it early.)

## C-1 · Audio — in-engine synth  [Q4=C, NQ4=b]
> Generation-first SFX via Godot `AudioStreamGenerator`/procedural DSP in GDScript: footstep, pickup, talk,
> win, (later) combat hit. A small reusable `audio.gd` autoload the shell triggers on events. No sound
> files. Verify headless that streams instantiate without error; manual listen for the cues.

## C-2 · Inventory  [systems #1]
> Carry/hold multiple carryables (from P-E), simple HUD list, select-active, deliver-active to NPC.
> Spec+plan first. Eval: "deliver correct item → win; wrong → wrong line" still holds with N items.

## C-3 · NPC quest-state persistence  [systems #2, NQ9=a]
> Wire NPC quest state (idle→given→done) into the **existing world-model transactional log** (reuse, don't
> add a parallel save system). Survives reload. Spec the world-model touchpoints first.

## C-4 · Multiple NPCs / multiple quests  [systems #3]
> >1 NPC per room, a quest each (behaviour-gen per NPC), HUD tracks the active quest. Decor-vs-target and
> carryable-target rules from P-E still hold per NPC.

## C-5 · Multi-room graph + leave-to-win  [systems #4, Q11/Q14, NQ8=b]  — needs R2
> A **graph/grid** of generated rooms connected by doors; traverse via doors; win by delivering AND/OR
> reaching an exit. Connection/generation/traversal model needs a design pass (R2). Spec first, reviewed.

## C-6 · NPC pathfinding / idle-wander  [systems #5]
> NavMesh bake in the generated room; NPC idle-wander + approach. Spec first.

## C-7 · Camera first/third-person — build-time flag  [Q9, NQ5=b]
> A scaffold/build flag selects first- OR third-person rig (NO runtime swap). Both share the visible body.
> Add the flag to `quest`/`scaffold_project`/`scene_compiler`. Verify both modes headless-load clean.

## C-8 · Basic combat  [Q10, NQ7=a]  — needs R3
> Player melee + ONE enemy type with health + approach-only AI; defeat to proceed/win. Enemy source &
> defeat/win model = R3. Spec first. Eval: "enemy defeatable / win reachable."

## C-9 · Rigged animated humanoid NPC (basic)  [Q10, NQ6=a]  — frontier
> Replace the primitive NPC body with a **rigged GLB + a single idle animation**, gate-passing AND
> animating in Godot headless without error, facing the player. Off-ramp allowed (generated simpler form)
> if the full rig stalls — documented. Its own slice, eval-gated. Spec+plan first.

---

# REMAINING DISCUSSION (R1–R4) — see chat
R1 game-composition/vision · R2 multi-room graph model · R3 combat enemy source & win model ·
R4 seed theme set for the control tables.
