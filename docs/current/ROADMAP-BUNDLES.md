# Execution Roadmap — Bundles (Anvil ports + LIST 3 + remaining)

> **📍 LIVE STATUS lives in `PROJECT-STATE.md`** (updated 2026-06-22). Spine slices 1–3, G1 Soul, the
> E1 material pipeline, and V (visual-eval, code) are DONE; the backlog below is the *future* work,
> to be driven through the spine one verified bundle at a time after V's real-run is calibrated.
>
> **⚠ DIRECTION UPDATE (2026-06-21): everything below now rides the Interpretation Spine.**
> See `SPINE-DESIGN.md`. Forge is a *general* embodied-3D-game generator, not this one RPG.
> The new definition-of-done has **three pillars**: Capability + Interpretation (free prompt →
> engine vocabulary) + Legibility (a build report saying understood / built / assumed /
> couldn't-do). A bundle is not "done" until its capability is expressed in the shared **Brief**
> and surfaces in the **Build Report**. Sequencing: **Spine Slice 1 (rooms)** → **Slice 2
> (quests ride the spine, incl. the parked per-NPC grammared dialogue fix)** → then the bundles
> below, each refactored to "add a Brief section + a generator that consumes it + its Decision
> Points + its report lines." The bundle *content* stands; the *bar* rose.

Each **bundle = one stop-and-verify cycle**: the CLI AI does it, then we run the live checkpoint
(headless gate + `test_godot_smoke.py` + a real playthrough; live run-twice for generation changes)
and fix before the next. **Standing rules + gate discipline:** see `EASY-BATCH-PROMPTS.md` header
(applies to every bundle). Detailed briefs already written are *referenced*, not repeated:
- `EASY-BATCH-PROMPTS.md` → EB-1…EB-7
- `ANVIL-PORT-ASSESSMENT.md` → G1/G2/G3 (+ silver/bronze)
- `BACKLOG-PROMPTS-READY.md` → C-5/C-6/C-8/C-9
New prompts (1–2 lines) are inline below. Order is dependency-correct; bundles within a tier can swap.

---

## B0 · Gate & eval hardening  (do first — small)
- **Multi-NPC playthrough probe** — extend `probe_playthrough.gd` to drive 2 NPCs end-to-end (talk→deliver each→all-win); add to `test_godot_smoke.py`.
- **Winnable/reachability oracle** — eval signal: target is gettable + deliverable for every NPC.
- Delete stale `builds/chk_*`.
- *Verify:* full suite + smoke green; oracle flags a deliberately-broken quest.

## B1 · Playability polish
- EB-2 (quest log, reticle+tooltip, target findability glow, juice, subtitles, multi-quest win) + EB-1 (sprint/crouch + camera juice + NPC idle micro-anim).
- *Verify:* play a room — quests readable, target findable, feel is right; headless 0-errors.

## B2 · Atmosphere
- EB-5 (post-processing stack + light-emitting props) + EB-4 (ambient soundscapes + footstep surfaces).
- **Day/night cycle (runtime)** [new] — Goal: real sun-angle + sky/ambient/fog progression over time (not a build flag); mirror `anvil_sim::time`. Files: `scene_compiler` (env/sun) + a small `day_night.gd`. *Verify:* headless load clean + screenshots at 2 phases.
- *Verify:* a generated room reads as a *place*; day/night visibly shifts.

## B3 · Item verbs
- EB-3 (use/consume, throw, place-on-surface, openable containers, locked door+key, weight, durability).
- *Verify:* playthrough probe exercises use/throw/place/open/lock through the real scripts.

## B4 · Content & narrative-lite
- EB-6 (examine→LLM flavor, idle barks, more themes).
- *Verify:* stub-LLM unit tests + one live run-twice.

## B5 · NPC character  (Anvil G1 + silver)
- **G1 Layered Soul** [ANVIL-PORT] — Goal: extend behaviour-gen grammar so the LLM assigns a Substrate (courage/generosity/stability) + initial emotional axes per NPC; store in quest_data; dialogue tone + idle-bark + (later) action choice read the axes; events nudge axes, persisted via the C-3 log. Files: `behaviour_gen` grammar + `soul.py` + `npc.gd`. *Eval:* "every NPC has a valid soul; tone varies with substrate."
- **NPC memory** [silver, `anvil settlement/memory`] — NPCs record/recall events on the C-3 world-model log; dialogue may reference them.
- **TimeBlock preferences** [silver] — tag idle behavior by day-phase (pairs with B2 day/night).
- *Verify:* two NPCs read as *distinct characters*; tone differs; memory line surfaces. Live run-twice.

## B6 · Living NPCs  (Anvil G2 + C-6)
- **C-6 NPC pathfinding / idle-wander** [BACKLOG-PROMPTS] — navmesh per room; NPCs move.
- **G2 Needs + utility-action loop** [ANVIL-PORT] — `npc_sim.py`: 7 needs + decay + ~21-action catalogue + utility-max selection; NPCs path to satisfy needs (uses C-6 + TimeBlock).
- **Connection layers + mood contagion** [silver] — Family/Proximity/Village weighted graph; emotion spreads.
- *Verify:* NPCs move and act on needs; an event's mood spreads. Headless + manual.

## B7 · World structure  (C-5)
- **C-5 multi-room graph + doors + cross-room persistence** [BACKLOG-PROMPTS] — builds on B3's locked-door + C-0 door-clearance guard.
- *Verify:* explore connected rooms; state persists across doors; start→exit path always exists.

## B8 · Emergent events  (Anvil G3)
- **G3 Catastrophe/world-events engine** [ANVIL-PORT] — `world_events.py`: themed event pick + precursor signals + spatial propagation + consequences → mutate room/needs → spawn an emergent quest.
- *Verify:* an event visibly changes the world and produces a solvable quest. Run-twice.

## B9 · Gold gameplay  (LIST 3 §B top picks)
- **Quest variety beyond fetch** [new] — extend quest grammar with deliver-to-NPC / place-at-location / talk-to-X; deterministic validators each.
- **Quest chains / dependencies** [new] — quest graph (A's reward unlocks B); validate solvable DAG.
- **POI / environmental vignettes** [new] — deterministic prop-cluster templates + one LLM line ("a scene happened here").
- *Verify:* a chained, multi-type quest is generated and completable. Run-twice.

## B10 · Combat + skills  (C-8 + silver)
- **C-8 combat** [BACKLOG-PROMPTS] — melee + golem enemy + health + death/respawn; hazards optional.
- **Skill domains / affordances / practice** [silver, `anvil skill/*`] — progression on combat/crafting verbs.
- *Verify:* a combat room is winnable; player can die & recover; skills advance.

## B11 · Frontier
- **C-9 rigged animated humanoid NPC** [BACKLOG-PROMPTS] + **Perceptibility→animation** [bronze].
- **Exteriors / terrain / biomes — start** [new, greenlit] — first outdoor room: terrain floor + vegetation + sky; `anvil_world` models terrain/vegetation/weather to mirror.
- *Verify:* humanoid animates in Godot headless; an exterior room loads clean.

---

## Later pool (pull into a bundle when ready — not yet sequenced)
LIST 3 §B remainder: crafting/item-combine · trading/economy · environmental puzzles (levers/plates) ·
secret rooms. §D generation depth: mood sliders · asset-on-asset composition · prefab clusters/layout
grammar · item descriptions. §F pipeline: variety metrics · screenshot-diff regression · extract
asset-foundry & room-gen as standalone tools · inspector/seed-explorer UI. Silver/bronze tail:
CatalystEvent/Joy · age curves · settlement economy/family · targeting helper.
