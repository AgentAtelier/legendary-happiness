# Consolidated Backlog (deduped from all AI brainstorms + ours)

**Date:** 2026-06-20. Source: 5 domain prompts × multiple external AIs + our own list.
De-duplicated by *concept*. Items already shipped are excluded (see bottom).

---

## LIST 1 — EASY: add without discussion (all ~S, high consensus, compose cleanly)

1. **Quest log / objective panel** — toggle UI listing active quests + targets (multi-NPC needs it).
2. **Interaction reticle + name tooltip** — crosshair state changes on hover; show prop/NPC name (extends the existing hover highlight).
3. **Sprint/crouch + camera juice** — FOV kick on sprint, crouch lerp, subtle head-bob.
4. **Pickup/drop/win "juice"** — tween bounce + small screen shake + particle puff on item & quest events.
5. **Post-processing stack** — tonemap (ACES) + SSAO + bloom + per-theme fog/exposure (per-theme *lights* already exist; this adds the WorldEnvironment stack). Biggest cheap visual win.
6. **Ambient room soundscapes** — extend the C-1 synth with a per-theme background drone + crossfade.
7. **Footstep surface audio** — floor material → footstep timbre.
8. **Readable lore / item examine** — an "examine" action calls the LLM for a one-line flavor text; reuse the dialogue UI.
9. **Item use / consume** — potion/food/torch → simple effect (heal, light, speed). Gives inventory a verb.
10. **Item throw** — held item becomes a physics projectile.
11. **Place item on a surface** — drop onto table/shelf; enables "deliver to location."
12. **Openable containers** — chest/drawer/cabinet holds & dispenses carryables.
13. **Locked door + key (single room)** — a key carryable opens a locked door/container. (Foundation for C-5; self-contained now.)
14. **Multi-quest win + counter** — victory = all NPC quests complete; HUD counter.
15. **Quest-target findability marker** — subtle glow/outline on the *active* quest target (fixes the "target indistinguishable from other props" playtest pain).
16. **More themes** — add rows to the data-driven theme table.
17. **Dialogue idle barks + variation pool** — a few rotating idle/greet lines so NPCs aren't static.
18. **Subtitles / dialogue scrollback** — on-screen transcript of NPC lines (accessibility + clarity).
19. **Day/time tint** — build-flag time-of-day sky/light tint.
20. **Light-emitting props** — lamp/torch/window props that actually cast light, per theme.
21. **Inventory weight or slot cap** — makes the multi-item inventory a real choice.
22. **Item durability** — limited uses; degrade/break state.
23. **Per-prop texture/weathering variation** — deepen U-5 with seed-driven dirt/wear masks so rooms aren't monochrome.
24. **NPC idle micro-animation** — breath/sway/look-at via Godot tweens (life before the rig).
25. **[OPEN ITEM, folded in] Multi-NPC target integrity** — guarantee ≥`npc_count` distinct carryables and make the carryable target actually model-driven (today every NPC defaults to the same injected `key_auto`).

---

## LIST 2 — IGNORE (one-line reason)

- **Live voice (STT/TTS) conversation** — latency on a 16 GB GPU shatters immersion; huge scope, low ROI now.
- **Multiplayer / "Forge Live" collaborative worlds** — networking scope contradicts the single-dev, disposable-build focus.
- **REST API / SaaS server** — premature productization, not gameplay.
- **Local image-gen NPC portraits (SDXL/Flux)** — a second heavy GPU model fights qwen + Blender for VRAM.
- **Real-time on-demand prop gen *during play*** — Blender build latency (seconds) breaks live play; already done at build time.
- **Live-reload Godot editor bridge** — fragile engine RPC; the disposable-build loop is acceptable.
- **Persistent non-disposable overworld** — contradicts the disposable-build model; revisit only if seed-stable regen is proven.
- **Verticality / multi-floor** — breaks the 2D grid; big refactor for little near-term value.
- **Procedural exteriors / terrain / biomes** — large asset + render scope; interiors first.
- **Full adaptive music system** — musical coherence is hard; ambient soundscapes give most of the value cheaper.
- **Diegetic physical inventory/menus** — high-friction novelty UX; standard UI is better for testing.
- **Single-room minimap / world map** — low value in one small room; revisit with multi-room.
- **LOD auto-generation** — perf optimization premature at current scene scale.
- **Cinematic "director" dialogue camera** — NPCs are static/unrigged; revisit after C-9.
- **Mounted / vehicle interaction** — niche; needs rig+anim; off-genre now.
- **Skill / perk tree** — needs combat + progression systems first; premature.
- **Faction / reputation system** — needs mature multi-NPC + persistence; too big now.
- **Elemental / systemic immersive-sim interactions** — highest-risk; needs combat+physics+semantics bridge; far off.

---

## LIST 3 — WHAT'S LEFT (needs discussion / sequencing — the meaty & gold)

**A. Already-planned big slices (sequenced):**
- C-5 multi-room graph + doors + cross-room persistence
- C-6 NPC pathfinding / idle-wander
- C-8 combat (+ death/respawn, enemy AI, stealth/vision, destructibles, hazards/traps)
- C-9 rigged + animated humanoid NPC

**B. Gold gameplay (need design):**
- Quest variety beyond fetch (deliver / place / talk-to / investigate / escort)
- Quest chains / dependencies (multi-step, cross-NPC) — repeatedly flagged top gold
- Crafting / item-combine (LLM recipes)
- Trading / barter / economy (coin-pouch → buy)
- Environmental puzzles (levers / pressure plates / switches)
- Secret rooms / hidden passages
- POI / environmental-storytelling vignettes (prop clusters + a line)

**C. Gold NPC depth (need design):**
- LLM-driven branching / live dialogue (beyond 4 canned lines)
- NPC schedules / needs / memory / relationships
- NPC-NPC gossip (via the world-model log)

**D. Generation depth (gold):**
- LLM-controllable generation sliders / "mood" meta-params
- Asset-on-asset composition (bookshelf + generated books)
- Multi-prop composites/prefabs + layout grammar (alcoves, windows, hallways)
- Generated quest-item descriptions / per-room narrative framing

**E. Pipeline & eval (you want eval pushed hard):**
- Eval: reachability/winnable oracle + automated playtest bot (extend the V-1 probe) + variety metrics + screenshot-diff regression
- Extract the **asset foundry** as a standalone CLI/API (modular product)
- Extract the **room generator** as a standalone tool
- Seed explorer / generation inspector UI + transactional-log viewer

---

## Excluded as ALREADY SHIPPED (so they don't reappear)
Hover highlight (P-C-1), crosshair + named prompts + carry-in-view + NPC nameplate (P-B), semantic
chairs-around-tables (U-4), per-theme lighting + fabric family + painting modes (P-G), procedural
audio footstep/pickup/talk/win (C-1), multi-item inventory (C-2), persistence (C-3), multi-NPC (C-4),
deterministic seed (P-H-1), parallel builds (P-L-1), category registry (T-4), tiny-room scaling (T-5),
RoomPlanner parse fallback (T-1), Godot-in-the-loop playtest probe (V-1, partial).
