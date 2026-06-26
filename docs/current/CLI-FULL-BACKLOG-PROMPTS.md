# CLI Full-Backlog Prompts — every open item, dependency-ordered

**You (the CLI implementer) own ALL implementation in this doc.** The orchestrator stays free for
live multi-model verification and design. Work the bundles **in order** (each is a stop-and-verify
unit); within a bundle, TDD red→green, one logical change per commit.

Read `AGENTS.md` first — it is the *how*. This doc is the *what*, grounded in the **actual tree as of
HEAD `0cc11ea`** (not the old roadmap, which lists work already done). Reference briefs are cited, not
repeated.

---

## 🔴 Standing rules (the three that bit us last round — non-negotiable)

1. **VERIFY-FIRST, every item.** The named feature may already be partially or fully implemented by a
   prior session. **Before writing code, grep/read the real files** named in the bundle. If a feature
   already exists and works, **say so in your report and skip it — do not fabricate or re-implement
   work.** (Last round a whole bundle was already done; the prompt didn't check.)
2. **Dedicated worktree.** Create an isolated git worktree off HEAD and work there
   (`git worktree add ../forge-cli-backlog -b feat/cli-backlog`). Do **not** commit onto another
   branch in the main checkout.
3. **Report the FULL suite total.** End every turn with the literal output of
   `cd foundry && .venv/bin/python -m pytest tests/ -q` (the **total** count, e.g. "962 passed") **and**
   `... tests/test_godot_smoke.py -q`. No subsets. Last round a run reported "883" when the real total
   was 943 — that means tests weren't collected; investigate before reporting green.

**Also always:** structured LLM output via llama.cpp `json_schema` (never `grammar=None`);
determinism in the build path (byte-identical for identical specs); single-line GBNF; never mutate the
real `asset_lexicon.json`; never touch `addons/godot_ai`/`Odysseus`/vendored upstream. After any change
under `foundry/godot_template/` or `scene_compiler.py`: scaffold a build, `godot --headless --path
<build> --quit`, grep stderr for `SCRIPT ERROR|Parse Error|Failed to load` = 0, and **regenerate
builds** (old builds keep old scripts). Verify behavior through the REAL scripts via
`probe_playthrough.gd`, never a reimplementation.

**Testing split:** you run the FULL unit suite + Godot smoke + headless-load (the fast, deterministic
gates). Anything that needs **live multi-model** confirmation (does the LLM actually emit valid
quests/souls/needs across models?) — write the **stub-LLM unit test** for it and **flag it in your
report for the orchestrator to run live**. Don't block on a live run.

---

## Shared data contracts (agree these once; every bundle reads/writes them)

### `quest_data` v2 (CB-1 produces; CB-2/CB-4/CB-5 consume)
```jsonc
"npcs": { "npc_0": {
  "npc_id": "npc_0", "npc_role": "...", "quest_id": "q_npc_0",
  "dialogue": {...}, "idle_barks": [...], "soul": {...}, "npc_placement": {...},
  "objective": {
    "type": "fetch|deliver|place|talk",
    "target": "<entity_id for fetch/deliver/place; npc_id for talk>",
    "giver": "npc",
    "recipient": "<npc_id>"  | null,   // deliver only
    "location":  "<entity_id>" | null, // place only (a furniture surface)
    "depends_on": []                    // chain prereqs: list of quest_id
  }
}}
```
- **`foundry/quest_validator.py` already exists** (orchestrator-committed `c95a341`). USE it — do not
  rewrite. `objective_winnable(objective, manifest=…, npc_ids=…) -> (bool, reason)` defines winnability
  per type (carryable/surface facts from `category_registry`); `chain_solvable(quests) -> (bool,
  reason)` validates the depends_on DAG. Every generated quest set must pass both.

### Other contracts (define inline in the bundle that introduces them, mirror this style)
- **room-graph / door schema** (CB-4): room nodes + door edges (id, from_room, to_room, locked,
  key_entity) + per-room manifest; a start→exit path must always exist.
- **event-consequence schema** (CB-5): event id, precursors, spatial origin, consequences (room/need
  mutations), spawned emergent quest_id.
- **enemy spec schema** (CB-6): enemy id, archetype, health, damage, placement — a NEW entity type,
  **not** an extension of `quest_data`/`npc.gd`.

---

## CB-1 · Quest depth — objective types + chains  (B9)  [foundation: do first]
**Open.** `behaviour_gen.py` hardcodes `objective.type="fetch"` everywhere (lines ~170, 551); only the
validator exists.
- **Generate** deliver / place / talk objectives + optional `depends_on` chains. Extend the
  multi-NPC `json_schema` (`_multi_npc_json_schema`) so the model may choose a type and fill
  `recipient` (deliver) / `location` (place) / target-npc (talk); default stays `fetch`. Post-parse,
  validate **every** quest with `quest_validator.objective_winnable` + `chain_solvable`; on failure,
  fire a Decision Point and **fall back to a winnable fetch** (legibility: the report says it downgraded).
- **Generalize the oracle:** `eval/signals.py::compute_quest_signals` currently tags any
  non-`fetch` as `quest_unwinnable` (line ~499). Replace that with a call into `quest_validator` so
  each type is judged by its real win condition; keep `check_all_npcs_winnable` honest for all types.
- **Runtime:** new `foundry/godot_template/scripts/quest_manager.gd` (autoload) tracks per-quest
  completion across types (fetch=carry, deliver=carry-to-recipient, place=placed-on-location,
  talk=spoke) + chain gating (a quest with unmet `depends_on` is locked). Wire `npc.gd` deliver/talk
  hooks. Emit `quest_data` v2.
- *Verify:* stub-LLM unit tests for each objective type + chain DAG; `probe_playthrough.gd` completes
  a deliver and a place quest end-to-end; full suite + smoke. **Flag for orchestrator:** live run that
  the model actually produces varied valid types across ≥9B models.

## CB-2 · Item verbs — the rest of B3  [needs CB-1 for place objective]
**Partially done** — VERIFY: weight/slot-cap/durability/throw already exist in `player.gd` (`B3:`
markers). **Open:** place-on-surface, openable containers, locked door+key, use/consume. Follow
`EASY-BATCH-PROMPTS.md` §EB-3 for scope.
- **Place-on-surface** (pairs with CB-1 `place` objective): place a held item onto a table/shelf top;
  this is the runtime that satisfies a `place` quest.
- **Openable containers** (`container.gd`): chest/drawer/cabinet opens on raycast, dispenses
  carryables into inventory.
- **Locked door + key** (`door.gd`): a key carryable opens a locked door/container; quest-gen may set
  the key as a fetch target. (CB-4 reuses this for inter-room doors.)
- **Use/consume:** "use" on flagged carryables (potion/food/torch) → simple effect (heal/light/speed),
  item consumed. Add per-item carryable/verb flags to **`category_registry`** (single source of truth).
- *Verify:* `probe_playthrough.gd` exercises place/open/lock/use through the REAL scripts; eval signal
  "placed-delivery winnable"; full suite + smoke + headless 0-errors.

## CB-3 · Living NPCs — navmesh + needs/utility  (B6)
**Open** (no `NavigationRegion3D`; no `npc_sim.py`). Brief: `ANVIL-PORT-ASSESSMENT.md` §G2 +
`BACKLOG-PROMPTS-READY.md` §C-6.
- **C-6 navmesh / idle-wander:** bake a `NavigationRegion3D` per room (at runtime in `npc.gd`'s
  `_ready`, or emitted by `scene_compiler.py`); NPCs path + idle-wander.
- **G2 needs + utility loop** (`foundry/npc_sim.py`): 7 needs + decay + ~21-action catalogue +
  utility-max selection; NPCs path to satisfy needs (uses C-6). Build-time decides the catalogue;
  runtime ticks it.
- *Verify:* headless load clean; NPCs move and act on needs; stub tests for utility selection.
  **Flag for orchestrator:** live "NPCs read as distinct/act on needs."

## CB-4 · Multi-room world structure  (B7, C-5)  [needs CB-2 locked-door]
**Open.** Brief: `BACKLOG-PROMPTS-READY.md` §C-5.
- Multi-room graph + doors + cross-room persistence; build on CB-2's locked-door + a door-clearance
  guard. Define the **room-graph/door schema** (above). A start→exit path must ALWAYS exist
  (deterministic validator + eval signal).
- *Verify:* explore connected rooms; state persists across doors; full suite + smoke.

## CB-5 · Emergent events  (B8, G3)  [needs CB-3 needs + CB-1 quest-gen]
**Open.** Brief: `ANVIL-PORT-ASSESSMENT.md` §G3.
- `foundry/world_events.py`: themed event pick + precursor signals + spatial propagation +
  consequences → mutate room/needs → **spawn an emergent quest** (reuses CB-1 quest-gen). Define the
  **event-consequence schema** (above).
- *Verify:* an event visibly changes the world and produces a solvable quest (validate via
  `quest_validator`); stub tests. **Flag for orchestrator:** live run-twice.

## CB-6 · Combat + skills  (B10, C-8)
**Open** (VERIFY: grep hits were false positives). Brief: `BACKLOG-PROMPTS-READY.md` §C-8 +
`ANVIL-PORT-ASSESSMENT.md` skill section.
- New `enemy.gd` entity (NOT `npc.gd`), `health`/`combat.gd`: melee + a golem enemy + health +
  death/respawn; hazards optional. Skill domains/affordances/practice on combat/crafting verbs. Define
  the **enemy spec schema** (above).
- *Verify:* a combat room is winnable; player can die & recover; skills advance; full suite + smoke.

## CB-7 · Frontier — rigged humanoid + exteriors  (B11, C-9)
**Open.** Brief: `BACKLOG-PROMPTS-READY.md` §C-9.
- **Rigged animated humanoid:** `Skeleton3D` + `AnimationPlayer` NPC (idle/walk) — verify it animates
  in Godot headless.
- **Exteriors / terrain — first outdoor room:** terrain floor + vegetation + sky (build-time room-gen
  extension). One outdoor room loads clean.
- *Verify:* humanoid animates headless; an exterior room loads clean; full suite + smoke.

## CB-8 · V hardening + content  (V follow-ups + EB-6)  [parallel; do any time]
**Open** (surfaced by the live V run). Brief: `V-VISUAL-EVAL-DESIGN.md`, `EASY-BATCH-PROMPTS.md` §EB-6.
- **V harness fixes:** `book_worn_oak` renders blank (flat prop under-framed by the turntable camera —
  fit camera to prop AABB); the `humanoid_rough_granite` + `key_worn_oak` capture errors (Godot
  subprocess failure under load — raise import/capture timeout or serialize captures); scene capture
  uses an orbit-at-radius-8 that sees through walls → use a **player-eye** framing.
- **CLIP aesthetic head:** `aesthetic.py`'s `_AestheticHead` (ViT-B-32 + 256 head) doesn't match public
  LAION weights → score always `None`. Rearchitect to the real LAION-V2 MLP + ViT-L/14 and load the
  public predictor weights, OR document it as ranking-only-disabled.
- **V Task 6:** closed auto-reroll loop (regenerate flagged props/scenes).
- **EB-6 content:** VERIFY `examine→LLM flavor` wiring (`examine_validator.py` + `interaction.gd` exist
  — confirm it's live); add more themes (crypt/armory/workshop/kitchen) to the data-driven theme table.
- *Verify:* full suite + smoke. **Flag for orchestrator:** the live V batch re-run (needs the Qwen3-VL
  GPU swap — orchestrator owns it; see memory `vlm-vision-api-gotcha`).

---

## Done — do NOT re-implement (verified in tree)
Spine 1–3 · G1 Soul · E1 materials · V core (chat/completions API + render harness) · B0 winnable
oracle · B1 (quest-log/reticle/glow/juice/subtitles/multi-quest-win + sprint/crouch/head-bob) · B2
(post-proc/SSAO/bloom/fog + light-emitting props + ambient/footstep audio + runtime day/night) ·
B3-partial (weight/slot-cap/durability/throw) · `quest_validator.py` (objective + chain winnability).
