# Consolidated Backlog (deduped from all AI brainstorms + ours)

**Date:** 2026-06-20 (rev 2 — reclassified per feedback). Source: 5 domain prompts × multiple external
AIs + our own list. De-duplicated by *concept*. Items already shipped are excluded (see bottom).

> **Taxonomy (corrected):** LIST 1 = do now, no discussion. LIST 2 = genuinely not pursuing (hard
> blockers). **LIST 3 = the broad "interesting ideas" bucket — anything worth keeping on the table,
> NOT pre-filtered by readiness.** Greenlit picks are called out at the top of LIST 3.

---

## LIST 1 — EASY: add without discussion (all ~S, high consensus, compose cleanly)

1. **Quest log / objective panel** — toggle UI listing active quests + targets (multi-NPC needs it).
2. **Interaction reticle + name tooltip** — crosshair state changes on hover; show prop/NPC name (extends the existing hover highlight).
3. **Sprint/crouch + camera juice** — FOV kick on sprint, crouch lerp, subtle head-bob.
4. **Pickup/drop/win "juice"** — tween bounce + small screen shake + particle puff on item & quest events.
5. **Post-processing stack** — tonemap (ACES) + SSAO + bloom + per-theme fog/exposure. Biggest cheap visual win.
6. **Ambient room soundscapes** — extend the C-1 synth with a per-theme background drone + crossfade.
7. **Footstep surface audio** — floor material → footstep timbre.
8. **Readable lore / item examine** — an "examine" action calls the LLM for a one-line flavor text; reuse the dialogue UI.
9. **Item use / consume** — potion/food/torch → simple effect (heal, light, speed). Gives inventory a verb.
10. **Item throw** — held item becomes a physics projectile.
11. **Place item on a surface** — drop onto table/shelf; enables "deliver to location."
12. **Openable containers** — chest/drawer/cabinet holds & dispenses carryables.
13. **Locked door + key (single room)** — a key carryable opens a locked door/container. (Foundation for C-5.)
14. **Multi-quest win + counter** — victory = all NPC quests complete; HUD counter.
15. **Quest-target findability marker** — subtle glow on the *active* quest target.
16. **More themes** — add rows to the data-driven theme table.
17. **Dialogue idle barks + variation pool** — a few rotating idle/greet lines.
18. **Subtitles / dialogue scrollback** — on-screen transcript of NPC lines.
19. ~~Day/time tint (build flag)~~ → **PROMOTED to a real day/night CYCLE — see LIST 3 ★ Greenlit.**
20. **Light-emitting props** — lamp/torch/window props that actually cast light, per theme.
21. **Inventory weight or slot cap** — makes the multi-item inventory a real choice.
22. **Item durability** — limited uses; degrade/break state.
23. **Per-prop texture/weathering variation** — seed-driven dirt/wear masks so rooms aren't monochrome.
24. **NPC idle micro-animation** — breath/sway/look-at via Godot tweens (life before the rig).
25. **[OPEN ITEM, folded in] Multi-NPC target integrity** — ≥`npc_count` distinct, model-driven carryable targets (today every NPC defaults to the same injected `key_auto`).

---

## LIST 2 — IGNORE (genuinely not pursuing now — hard blockers)

- **Multiplayer / "Forge Live" collaborative worlds** — networking scope contradicts single-dev / disposable focus.
- **Live voice (STT/TTS) conversation** — STT+LLM+TTS serial on one 16 GB GPU = multi-second latency that breaks immersion.
- **REST API / SaaS server** — *(what it is: wrapping the generator behind a web/HTTP endpoint so a website or other apps can request generations remotely — i.e. running Forge as a hosted online service)* — premature productization, not gameplay.
- **Local image-gen NPC portraits (SDXL/Flux)** — a second heavy GPU model fights qwen + Blender for VRAM.
- **Real-time on-demand prop gen *during* play** — Blender build latency (seconds) breaks live play; already done at build time.
- **Live-reload Godot editor bridge** — fragile engine RPC; the disposable-build loop is acceptable.
- **Diegetic physical inventory/menus** — high-friction novelty UX; standard UI is better for testing.

---

## LIST 3 — INTERESTING BUCKET (broad; not filtered by readiness)

### ★ Greenlit now (you called these in)
- **Day/night cycle (runtime)** — [S/M] real sun-angle + sky/ambient/fog cycle over time (not just a build flag). *anvil_sim has a `time` module to mirror.* — shell + room-gen.
- **Exteriors / terrain / biomes — get started** — [L, but begin] open/outdoor rooms with terrain floors, vegetation, sky. *Big head start: `anvil_world` already models terrain heights, vegetation densities, regions, and `WeatherState`.* — assets + room-gen + shell.

### A. Already-planned big slices (sequenced)
- C-5 multi-room graph + doors + cross-room persistence
- C-6 NPC pathfinding / idle-wander
- C-8 combat (+ death/respawn, enemy AI, stealth/vision, destructibles, hazards/traps)
- C-9 rigged + animated humanoid NPC

### B. Gold gameplay
- Quest variety beyond fetch (deliver / place / talk-to / investigate / escort)
- Quest chains / dependencies (multi-step, cross-NPC) — repeatedly flagged top gold
- Crafting / item-combine (LLM recipes)
- Trading / barter / economy
- Environmental puzzles (levers / pressure plates / switches)
- Secret rooms / hidden passages
- POI / environmental-storytelling vignettes

### C. NPC depth & society sim — **largely DESIGNED & partly BUILT in `anvil_sim`** (Rust)
- **Needs-driven NPCs** — anvil_sim `needs`: 7-need model (food/water/shelter/safety/sleep/companionship/joy; joy only from "catalyst events").
- **Layered personality/emotion** — anvil_sim `soul`: stable Substrate traits → 4-axis emotional state (filters perception) → utility-scored actions.
- **Skills / practice / progression** ("skill tree") — anvil_sim `skill` (affordance/fluency/practice/profile).
- **Settlements: families, memory, relationships/connections** — anvil_sim `settlement`.
- **Factions** — anvil_sim "owns faction state."
- **Emergent events / contagion / joy** ("systemic/immersive-sim") — anvil_sim `catastrophe` (event/propagation/signal) + `system/joy`.
- LLM-driven branching / live dialogue; NPC-NPC gossip — pairs with the above.
> **⚠ Strategic question (for us):** this depth lives in a *separate Rust/Bevy stack (Anvil)*, engine-free and deterministic. Forge is Python+Godot. Options: (a) port concepts/design into Forge; (b) expose `anvil_sim` to Python via FFI (PyO3) as the "brain"; (c) keep Forge as a generation/render testbed and converge on Anvil later. **Big decision — don't pick blind.**

### D. Generation depth
- LLM-controllable generation sliders / "mood" meta-params
- Asset-on-asset composition (bookshelf + generated books)
- Multi-prop composites/prefabs + layout grammar (alcoves, windows, hallways)
- Generated quest-item descriptions / per-room narrative framing

### E. World / exploration extras
- Persistent (seed-stable) world / overworld — *anvil has `WorldAuthored`/`WorldRuntime` + deterministic RNG.*
- Weather — *anvil `WeatherState`.*
- Verticality / multi-floor (needs 2D-grid refactor)
- Minimap / world map (with multi-room)

### F. Pipeline & eval
- Winnable/reachability oracle + automated playtest bot (extend V-1) + variety metrics + screenshot-diff regression
- Extract the asset foundry as a standalone CLI/API
- Extract the room generator as a standalone tool
- Seed explorer / generation inspector UI + transactional-log viewer

### G. Parking (niche / low-priority, revisit later)
- LOD auto-generation · full adaptive music · cinematic dialogue camera · mounts/vehicles

---

## Excluded as ALREADY SHIPPED (so they don't reappear)
Hover highlight (P-C-1), crosshair + named prompts + carry-in-view + NPC nameplate (P-B), semantic
chairs-around-tables (U-4), per-theme lighting + fabric family + painting modes (P-G), procedural
audio footstep/pickup/talk/win (C-1), multi-item inventory (C-2), persistence (C-3), multi-NPC (C-4),
deterministic seed (P-H-1), parallel builds (P-L-1), category registry (T-4), tiny-room scaling (T-5),
RoomPlanner parse fallback (T-1), Godot-in-the-loop playtest probe (V-1).
