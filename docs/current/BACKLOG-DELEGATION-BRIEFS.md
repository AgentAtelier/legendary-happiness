# Backlog — Delegation Briefs (prompts for the CLI AI)

**Date:** 2026-06-20
**How to use:** hand the CLI AI one **package** at a time, in order within a section. Each package is a
self-contained mini-slice. READY packages need no further input; BLOCKED packages wait on an answer
from `OPEN-QUESTIONS` (see the bottom / the chat list) — don't start those until the gating Q is answered.

## Standing rules (apply to EVERY package — paste once at the top of each handoff)

> Read `AGENTS.md` and `docs/current/SLICE1-RPG-FETCH-QUEST.md` first. Work on a **dedicated branch**
> (not in-place on a shared checkout — that caused stale-build bugs last time). TDD red→green. Foundry
> tests: `cd foundry && .venv/bin/python -m pytest tests/ -q`. **Godot-in-the-loop is the gate and the
> structural `.tscn`/probe tests are NOT sufficient**: after ANY change to `foundry/godot_template/`
> or `scene_compiler.py`, scaffold a build and run `godot --headless --path <build> --quit`, then grep
> stderr for `SCRIPT ERROR|Parse Error|Failed to load script` (must be 0). Regenerate builds after
> shell-script changes (old builds carry old scripts). Single-line GBNF only. Never mutate the real
> `asset_lexicon.json` in tests (use a `/tmp` copy). qwen is stochastic — any live claim runs twice.
> Honor the manifest contract (`room_size`, `yaw`, `surface`, `decor`). Never touch `addons/godot_ai`.
> Commit per task with commit-proof (`git log --oneline -n` + `git status`).

---

# SECTION A — READY (no decisions needed)

## P-A · Player scale & eye-height fix  [shell · S]
> **Bug:** eye height ≈ 2.6 m (camera local `y=1.7` stacked on player spawn `y=1.0`; capsule centre
> settles ~0.9 m off floor) → "hovering, player bigger than the scene". Capsule is also too wide.
> In `foundry/scene_compiler.py`: set the Camera3D local transform to eye height ~0.7 above the player
> origin (so world eye ≈ 1.6 m once grounded), reduce the player `CapsuleShape3D`/`CapsuleMesh`
> `radius` 0.5→0.3, and reconcile `_PLAYER_SPAWN_Y` so the capsule rests on the floor (bottom at y≈0).
> **Verify:** scaffold a build, headless-load (0 script errors), and add/extend a structural test
> asserting the camera local y and capsule radius. Confirm in-editor the view feels eye-level (paste a
> screenshot or the transform values). Commit-proof.

## P-B · HUD & interaction UX pack  [shell · S]
> In `foundry/godot_template/scripts/hud.gd` (+ `scene_compiler.py` HUD nodes) and `interaction.gd`:
> 1. Add a **crosshair/reticle** (small centered Control) so the raycast is aimable.
> 2. Interact prompt names the target ("Press E to talk to the {npc_role}" / "Press E to pick up the
>    {category}") — read the tag/role already available to `interaction.gd`/`npc.gd`.
> 3. Carry the picked-up prop **in view**: on pickup, reparent/visually attach the prop in front of the
>    camera (or show a held-item indicator). Add a **drop** key (G).
> 4. `win_screen.gd`: show a "You won!" label and a "press R to restart / Esc to quit" line; wire the keys.
> 5. **NPC nameplate**: a billboard `Label3D` over the NPC showing `npc_role`.
> **Verify:** headless-load clean; scripted playthrough still reaches WinScreen; manual screenshot of
> crosshair + held item + nameplate. Commit per item.

## P-C-1 · Highlight the interactable under the crosshair  [shell · S]
> In `interaction.gd` + the prop nodes: when the raycast hits a `pickup`/`talk` node, apply a visible
> highlight (emissive/outline material or a scale pulse) and clear it when not hovered. This makes the
> quest target reachable by *looking*, not just guessing. (Naming the specific target is P-C-2, gated
> on Q1.) **Verify:** headless-load clean; manual confirm the hovered prop highlights. Commit-proof.

## P-D · Close the Godot smoke-probe gap  [eval · S]
> The probes reimplement interaction, so a parse error in `interaction.gd` passed the suite (it only
> surfaced on a real launch). In `foundry/tests/test_godot_smoke.py`: add an assertion that a freshly
> scaffolded build, launched with `godot --headless --path <build> --quit`, produces **0** lines
> matching `SCRIPT ERROR|Parse Error|Failed to load script`. Bonus: have `probe_playthrough.gd` drive
> the real `interaction.gd` path rather than a copy. **Verify:** the new assertion fails if you
> reintroduce the old merged-line bug, passes on `main`. Commit-proof.

## P-H-1 · Seedable RoomPlanner  [gen · S]
> Add an optional `--seed` to `python -m foundry quest` and thread a seed into `RoomPlanner`/the LLM
> sampling so a given (prompt, seed) reproduces the same room — without removing stochastic variety
> when no seed is passed. TDD the deterministic plumbing with a stub LLM. **Verify:** same seed →
> identical manifest twice. Commit-proof.

## P-K · Eval oracle extensions  [eval · M]
> Extend `foundry/eval/` with signals: (a) **room variety** — generate N rooms for one prompt across
> seeds and score size/prop-count/palette spread; (b) **decor-never-target** invariant; (c)
> **headless-load-clean** as a hard signal. Add to the quest corpus. TDD with synthetic specs; keep
> prior eval tests green. Commit-proof.

## P-L-1 · Parallel generate-on-demand builds  [infra · M]
> `asset_ensure.ensure_assets` builds missing GLBs serially (Blender per asset). Parallelize across
> processes (bounded pool) since each `forge()` is independent. Keep the `/tmp` lexicon-copy rule and
> determinism. TDD the orchestration with a stub builder (assert all missing built, existing skipped,
> bounded concurrency). **Verify:** a multi-missing room builds faster, still gate-passing. Commit-proof.

---

# SECTION B — BLOCKED (need an OPEN-QUESTION answer first)

## P-C-2 · NPC names the real target  [gen · M] — gated on **Q1, Q2**
> Make the fetch coherent: the NPC's `ask`/`wrong`/`thank` reference the actual target (category +
> material + rough location), OR the target becomes a small carryable item (P-E). Exact shape depends
> on Q1 (realism approach) and Q2 (carryable catalogue).

## P-E · Small carryable items as the real fetch target  [gen · M-L] — gated on **Q1, Q2**
> New tiny generator(s) (e.g. cup/tool/book/key/gem) placed **on** furniture; the quest target becomes
> one of these, so "find my X" matches a thing you actually carry. Needs the carryable catalogue (Q2),
> a surface-attach placement rule in `room_layout`, and a behaviour-gen change so the target is a
> carryable, not furniture. Resolves the item-vs-prop realism gap.

## P-F · New prop generators  [gen · M] — gated on **Q3**
> Add parametric Blender generators for the chosen set (candidates: barrel, crate, bed, lamp, stool,
> anvil). Each: `_build_*_geometry` + `_BUILDERS` + `compiler.GENERATORS`/`PARAM_RANGES` + grammar
> branch + lexicon envelope + live gate-passing build test. Priority/which-ones from Q3.

## P-G · Material & visual richness  [gen · M] — gated on **Q5, Q7**
> (a) Painting **canvas content** (Q5: blank/solid/generated-pattern/image); (b) per-theme **lighting
> mood** derived deterministically from theme keywords (Q7); (c) optional **fabric material family**
> for rugs. Each part TDD'd + headless-verified.

## P-I · Audio / SFX  [shell · S-M] — gated on **Q4**
> Footstep/pickup/win sounds. We have **no** sound assets or audio generator today, so this needs a
> source decision (Q4: skip / source free SFX / synth-generate). Brief finalized after Q4.

## P-J · Systems  [L] — gated on **Q8** (priority) + per-item
> Candidates, each its own slice: inventory UI; NPC quest-state persistence via the world-model;
> multiple NPCs/quests; multi-room + exit door; NPC pathfinding/idle-wander. Q8 sets order; Q12/Q14
> shape multi-room & win-by-leaving.

## P-M · Frontier  [L] — gated on **Q9, Q10, Q11**
> Third-person vs visible-first-person body (Q9); full rigged+animated humanoid NPC (Q10, the single
> hardest item); combat as a second verb (Q11); biomes/alt shells. Each becomes its own spec when greenlit.

---

# OPEN QUESTIONS (answer these to unblock Section B)
See the numbered list in chat (Q1–Q15). Each blocked package above cites the Qs it needs.
