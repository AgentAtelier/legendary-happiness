# Bundle (CLI AI) — Playability & Atmosphere

**Track B of a two-track parallel split.** This bundle is *all Godot-shell + scene-env* work:
deterministic, unit/smoke-gated, **no live LLM required**. The other track (orchestrator) owns the
Python sim + quest generation in parallel. Read `AGENTS.md` first; this doc is the *what*, AGENTS is
the *how*.

> **Why this is parallel-safe — DO NOT cross these lines (the other AI is editing the other side):**
> 1. **You own `scene_compiler.py`** (env / lighting / post-processing / audio / light-emitting props).
>    The other track does **not** touch it.
> 2. **You must NOT touch `foundry/godot_template/scripts/npc.gd`.** NPC idle micro-animation (EB-1)
>    is **moved to the other track** because it lives in `npc.gd`. Skip it here.
> 3. **The shared contract is the `quest_data` JSON** (see “Quest-data contract” below). You only
>    **read** it in the HUD/quest-log; you never write or restructure it. The other track produces it.
> 4. Other files reserved for the other track (don't edit): `behaviour_gen.py`, `soul.py`, `brief.py`,
>    `interpreter.py`, `decisions.py`, `category_registry.py`, `quest_manager.gd` (new), validators.

## Standing rules (in addition to AGENTS.md)
Paste-equivalent of `EASY-BATCH-PROMPTS.md` header. Work on a **dedicated branch/worktree**. TDD
red→green, one logical change per commit with commit-proof (`git log --oneline -n` + `git status`).
**Always run the FULL gate, never a subset:**
```
cd foundry && .venv/bin/python -m pytest tests/ -q
cd foundry && .venv/bin/python -m pytest tests/test_godot_smoke.py -q
```
After any change under `foundry/godot_template/` or to `scene_compiler.py`: scaffold a build,
`godot --headless --path <build> --quit`, and grep stderr for `SCRIPT ERROR|Parse Error|Failed to
load` = **0**. Old builds keep old scripts — **regenerate builds** before judging. Verify behavior
through the REAL scripts via `probe_playthrough.gd`, never a reimplementation. Single-line GBNF only;
never mutate the real `asset_lexicon.json`. Never touch `addons/godot_ai` / vendored upstream.

---

## Your files (ownership map)
- **Godot shell (`foundry/godot_template/scripts/`)**: `player.gd`, `hud.gd`, `win_screen.gd`,
  `audio.gd`, `day_night.gd`, `pickup.gd`, `interaction.gd`, **new** `reticle.gd`, **new**
  `quest_log.gd`. Plus `probe_playthrough.gd` / `probe_smoke.gd` for verification.
- **Scene env (`foundry/scene_compiler.py`)**: the `WorldEnvironment`/post-processing, interior
  lighting, light-emitting props, and audio-autoload emission sections.
- **Tests**: `foundry/tests/` (your new unit tests), `foundry/tests/test_godot_smoke.py`, and any
  `foundry/eval/` signal you add.

---

## Work items

### B1 · Playability — EB-2 (Interaction & HUD) + EB-1 movement only
Implement **EB-2** in full (`EASY-BATCH-PROMPTS.md` §EB-2): quest-log panel (toggle, reads
`quest_data`, multi-NPC), reticle + name tooltip (reuse `_build_prompt` metadata), quest-target
findability marker (emissive/outline on the *active* target only), pickup/deliver/win juice,
subtitles/scrollback, multi-quest win + "X / N" counter.
Implement **EB-1 movement only** (§EB-1 first bullet): sprint/crouch + camera juice (FOV widen on
sprint, lower+slow on crouch, subtle head-bob). **Skip the EB-1 “NPC idle micro-animation” bullet —
that is the other track’s (`npc.gd`).**
- *Verify:* extend `probe_playthrough.gd` to assert the quest-log is populated and win fires only
  after all quests complete; headless 0-errors.

### B2 · Atmosphere — EB-5 (Visual richness) + EB-4 (Audio) + runtime day/night
Implement **EB-5** (§EB-5): `WorldEnvironment` post-processing stack (ACES tonemap + SSAO + bloom +
per-theme fog/exposure) and light-emitting props (lamp/torch/window → real `OmniLight3D`/
`SpotLight3D`, placed per theme) — emitted from `scene_compiler.py`.
Implement **EB-4** (§EB-4): per-theme ambient soundscape (crossfade on enter) + footstep surface
audio (raycast floor material → timbre), via `audio.gd` + the audio autoload.
Implement the **runtime day/night cycle** (`day_night.gd`): real sun-angle + sky/ambient/fog
progression over time (a runtime cycle, NOT a build flag). Mirror `anvil_sim::time` conceptually.
- *Verify:* headless-load clean; screenshot from spawn per setting; eval signal “env stack present +
  deterministic per (theme, seed)”; smoke test asserts the audio autoload + ambient stream
  instantiate (mirror the existing `_check_audio_synth`); day/night screenshots at 2 phases.

---

## Quest-data contract (READ-only — the seam with the other track)
The quest log and HUD read `scenes/<scene>_quest_data.json`. **Today** every objective is
`type:"fetch"`; the other track is extending it. Build your quest-log/HUD to read the **v2 shape
below and degrade gracefully** so you can ship now and new types light up automatically:

```jsonc
"npcs": {
  "npc_0": {
    "npc_id": "npc_0",
    "npc_role": "steward",
    "quest_id": "q_npc_0",                 // NEW (may be absent on old data → fall back to npc_id)
    "dialogue": { "greet": "...", "ask": "...", "wrong": "...", "thank": "..." },
    "objective": {
      "type": "fetch",                     // one of: fetch | deliver | place | talk  (treat unknown as generic)
      "target": "key_0",                   // entity_id for fetch/deliver/place; npc_id for talk
      "giver": "npc",
      "recipient": null,                   // deliver: npc_id to bring the item to (else null/absent)
      "location": null,                    // place: surface/location entity_id (else null/absent)
      "depends_on": []                     // chain prereqs: list of quest_id (empty = available immediately)
    },
    "idle_barks": ["..."],
    "soul": { "...": "..." },
    "npc_placement": { "...": "..." }
  }
}
```
Rules for your reader:
- Render each quest line by `type`: fetch="Find {target}", deliver="Bring {target} to {recipient}",
  place="Place {target} on {location}", talk="Speak with {target}". Unknown type → show the raw
  `type` + target, never crash.
- A quest with non-empty `depends_on` whose prereqs aren’t complete shows as **locked/greyed**;
  otherwise **active**. (Completion state is runtime — you track it in the HUD as quests resolve.)
- Missing optional fields (`quest_id`, `recipient`, `location`, `depends_on`) must be tolerated
  (old fetch-only data has none). Use human labels via existing prop/NPC metadata.
- **Do not** invent new `quest_data` fields or change its structure. If you need a field that isn’t
  here, flag it — the other track adds it on the producing side.

## Definition of done (per pillar — every item)
- **Capability** shipped + **Legibility**: anything player-visible that the build “did” should be
  representable (the HUD/quest-log makes the quest legible; the env stack is deterministic per
  theme+seed). **Interpretation** is the other track’s side for quests; you consume it.
- FULL `pytest tests/` green + `test_godot_smoke.py` green + headless 0-errors on a freshly
  scaffolded build. Commit per item with proof.
