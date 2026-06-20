# Easy Batch — Delegation Packages (LIST 1 + fixes)

Hand the CLI AI one **package (EB-n)** at a time. Each is a coherent commit-group. All are ~S effort,
high-consensus, and compose with what exists.

## Standing rules (paste at the top of every handoff)
> Read `AGENTS.md` + `docs/current/SLICE1-RPG-FETCH-QUEST.md`. Work on a **dedicated branch/worktree**.
> TDD red→green. **Run the full suite AND the Godot gate explicitly:**
> `cd foundry && .venv/bin/python -m pytest tests/ -q` **and** `... tests/test_godot_smoke.py -q`.
> ⚠️ The Godot-in-the-loop tests are THE gate and were skipped in past "N pass" reports — they must be
> green, no exceptions. After any change under `foundry/godot_template/` or to `scene_compiler.py`:
> scaffold a build, `godot --headless --path <build> --quit`, grep stderr for
> `SCRIPT ERROR|Parse Error|Failed to load` = 0, and **regenerate builds** (old builds keep old scripts).
> Behavior is verified through the REAL scripts via `probe_playthrough.gd` — not reimplementations.
> **Eval-first:** any generation change adds/extends a `foundry/eval/` signal. Single-line GBNF; never
> mutate the real `asset_lexicon.json` in tests; qwen stochastic → live claims twice. Commit per item
> with commit-proof (`git log --oneline -n` + `git status`). Never touch `addons/godot_ai`.

---

## EB-1 · Movement & camera feel  [Godot shell]
- **Sprint / crouch + camera juice** — sprint widens FOV (~+8°) and quickens footstep tempo; crouch lowers camera + slows; subtle head-bob on walk.
- **NPC idle micro-animation** — breath scale + slight sway + look-at-player via `AnimationPlayer`/tweens (no rig needed).
> *Verify:* headless-load clean; manual feel pass / screenshot.

## EB-2 · Interaction & HUD  [Godot shell]
- **Quest log panel** — toggle (e.g. J) listing each active NPC quest + its target + status (read from quest_data; works with multi-NPC).
- **Reticle + name tooltip** — crosshair changes shape/color on a pickable/talk hit; floating label shows the prop category / NPC role (reuse `_build_prompt` metadata).
- **Quest-target findability marker** — a subtle emissive/outline on the *active* quest target only (fixes "target indistinguishable from other props").
- **Pickup / deliver / win juice** — tween bounce on pickup, particle puff on drop, small screen-shake + flash on quest-complete/win.
- **Subtitles / dialogue scrollback** — on-screen transcript panel of NPC lines; respects space-to-advance.
- **Multi-quest win + counter** — HUD "X / N quests done"; win when all NPC quests complete (configurable).
> *Verify:* extend `probe_playthrough.gd` to assert quest-log populated + win fires only after all quests; headless 0-errors.

## EB-3 · Item verbs  [Godot shell + assets + quest-gen]
- **Item use / consume** — a "use" action on flagged carryables (potion/food/torch) triggers a simple effect (heal/light/speed); item consumed.
- **Item throw** — held item becomes a short-lived `RigidBody3D` projectile on throw input.
- **Place on a surface** — place a held item onto a table/shelf top; extend quest-gen grammar with a `deliver-to-location` objective using placed surfaces.
- **Openable containers** — chest/drawer/cabinet opens (raycast) and dispenses carryables into inventory.
- **Locked door + key (single room)** — a key carryable opens a locked door/container; quest-gen may set the key as a fetch target.
- **Inventory weight or slot cap** — a carry limit forcing drop/keep decisions; HUD shows usage.
- **Item durability** — limited uses; degrade then break-state.
> *Verify:* `probe_playthrough.gd` exercises use/throw/place/open/lock end-to-end through the real scripts; eval signal "placed-delivery winnable". Add per-item carryable flags to the **category registry** (single source of truth).

## EB-4 · Audio depth  [Godot shell, extends C-1]
- **Ambient room soundscapes** — per-theme background drone layer from the synth; crossfade on room enter.
- **Footstep surface audio** — raycast floor material → footstep timbre (wood/stone/rug).
> *Verify:* smoke test asserts the audio autoload + ambient stream instantiate without error (mirror the existing `_check_audio_synth`).

## EB-5 · Visual richness  [Godot shell + room-gen + assets]
- **Post-processing stack** — `WorldEnvironment`: ACES tonemap + SSAO + bloom + per-theme fog/exposure (per-theme *lights* already exist from P-G; this adds the env stack). Biggest cheap visual win.
- **Day/time tint (build flag)** — `--time dawn|noon|dusk|night` sets sun angle + sky/ambient tint at scaffold time.
- **Light-emitting props** — lamp/torch/window props cast actual `OmniLight3D`/`SpotLight3D`, placed per theme.
> *Verify:* headless-load clean; screenshot from spawn per setting; eval "env stack present + deterministic per (theme, seed)".

## EB-6 · Content & narrative-lite  [quest-gen + room-gen]
- **Readable lore / examine** — an "examine" action calls the LLM for a 1-line flavor text for the looked-at prop; reuse the dialogue UI; deterministic length/validation + canned fallback.
- **Dialogue idle barks + variation pool** — generate a few rotating idle/greet lines per NPC so they aren't static.
- **More themes** — add rows to the data-driven theme table (e.g. crypt, kitchen, armory, workshop), each with palette + density + required props.
> *Verify:* stub-LLM unit tests (no llama) for examine validation + theme-table rows; one live run-twice.

## EB-7 · Fixes (folded in)
- **Multi-NPC target integrity** — today both NPCs default to the same injected `key_auto`. (a) `room_layout` must guarantee **≥ npc_count distinct carryables** when a room is multi-NPC; (b) make the carryable target genuinely model-driven (prefer an LLM-picked carryable; only inject as last resort); (c) ensure `plan_multi` assigns **distinct** carryable targets across NPCs. *Eval:* "N NPCs ⇒ N distinct, reachable, named carryable targets."
- **Verify fabric + texture variety actually surface** — the live kitchen-sink showed rooms reading monochrome and fabric never appearing despite T-3/U-5. Confirm in a real build that ≥2 materials appear per room and fabric reaches its themes; fix the palette/registry wiring if not. *Eval:* "room not monochrome; fabric present in fabric themes."
> *Verify:* live run (≥9B for multi-NPC) + headless playthrough; run-twice.

---

## Suggested order
EB-7 (fixes) → EB-2 (HUD/clarity) → EB-5 (visual win) → EB-3 (item verbs) → EB-4 (audio) → EB-1 (feel) → EB-6 (content).
EB-7 first because it repairs the default play experience; EB-2/EB-5 give the biggest perceived-quality jump next.
