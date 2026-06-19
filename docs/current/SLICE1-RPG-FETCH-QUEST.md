# Slice 1 — One-Room RPG Fetch Quest (generation-first)

**Date:** 2026-06-19
**Status:** design locked, prompts ready for CLI-AI implementation
**Premise:** GENERATION-FIRST. Per the `handcraft-last-resort` principle, we do not hand-author
any *specific game output* (shell, components, NPC, character) until generation via our pipeline is
proven inadequate. Handcraft is a documented off-ramp, never the start. No imported stand-in
character — the NPC body is generated from the ground up.

## The game (the target)

One prompt → a single navigable room of generated props + an NPC. The NPC gives a fetch quest
("find my X"). The player searches the cluttered room, picks props up, brings one to the NPC. Wrong
item → the NPC says so. Right item → the NPC thanks the player → **WIN**. That is the whole,
complete, tiny RPG.

## The seam (what the LLM does / never does)

- **LLM (per output):** picks the NPC's role from the room theme; picks *which already-placed prop*
  is the quest target; writes the dialogue lines. Nouns + words only.
- **LLM never:** writes GDScript, positions anything in 3D, or invents rules.
- **Pipeline tooling (written once, reused for every game — this IS the approach, not handcrafting):**
  the closed-vocabulary grammar, the behaviour-gen call, the dialogue validator, the deterministic
  spec→Godot scene-compiler, the generic shell templates, the interaction-component templates, the
  character generator. Built once; every game is produced by running them.

## Pipeline

1. **Asset-gen** *(exists)* — prompt → props generated + placed → `.glb` published into `rpg/assets`
   (`foundry/publish.py`). Produces a **placed-entity manifest** (ids + categories + material/wear).
2. **Behaviour-gen** *(NEW, P1)* — a second grammar-constrained LLM call that sees the manifest and
   emits a **quest spec** (NPC role, target entity id, dialogue).
3. **Scene-compile** *(NEW, P3)* — deterministic Python turns quest spec + assets into a runnable
   Godot scene, wiring components by a fixed tag→behaviour table.
4. **Play** — the generated Godot scene runs on the generated shell.

## Repos

- **Forge** `/home/mrg/dev/games/Forge` — `foundry/` python brain. P1, P2, P3, P7, P8 land here.
- **rpg** `/home/mrg/dev/games/rpg` — Godot game (Godot 4.6, Jolt). P4, P5 land here. The existing
  `scripts/` are messy DevForge auto-gen — **reference only, do not build on them.** Never touch
  `addons/godot_ai` (upstream Odysseus — see `upstream-fork-policy`).

## Standing rules (every prompt)

All `AGENTS.md` rules apply: TDD (red→green), scope discipline, **commit-proof reporting (paste
`git log --oneline -n` + `git status`)**, foundry venv + determinism gate, **single-line GBNF only**
(multi-line alternations silently disable constraints — `llamacpp-peg-grammar`), never mutate the
real `asset_lexicon.json` (use a `/tmp` copy), never commit `.venv`/zips, never patch
`godot-ai`/Odysseus. **qwen is stochastic — any live claim must be backed by running TWICE and
comparing** (`devforge-audit-workflow`). Work under `qwen-good-enough` + `handcraft-last-resort`:
exhaust deterministic/prompt/architectural fixes before blaming the model OR reaching for handcraft.

## Highest-risk item, stated honestly

**P7 (procedural rigged animated humanoid → GLB) is the single hardest thing in this slice — harder
than the gameplay layer.** It may not fully land in one pass and may become its own slice. It is
sequenced LAST so a fully playable game exists (P6) before it; until P7 lands, the compiler uses a
**generated primitive marker** for the NPC body (a low-poly form from our existing primitive
generators — generated, NOT imported, NOT hand-modelled). This honours "no stand-in import" while
keeping the loop testable.

---

# The prompts

Hand these to the CLI AI one at a time, verifying each before the next.

## P0 — Setup & scope

> Read `/home/mrg/dev/games/Forge/AGENTS.md` and `docs/current/SLICE1-RPG-FETCH-QUEST.md` in full.
> We are building a one-room RPG fetch-quest slice, **generation-first** (no handcrafting a specific
> output, no imported character — see the doc's premise). Create a working branch off `main`
> (`feat/slice1-rpg-fetch-quest`). Confirm: the foundry venv runs, the existing test suite is green
> (report the count), and `main` is the 375-green baseline. Paste `git log --oneline -5` and
> `git status`. Do nothing else.

## P1 — Quest-spec grammar + behaviour-gen call (Forge)  ·  the brain

> **Goal:** a second, grammar-constrained LLM call that reads the *placed-entity manifest* and emits
> a **quest spec**. Mirror the existing asset planner's grammar-constrained call and the
> `material_resolver`/`age_resolver` module style.
>
> **Closed vocabulary (the only things the LLM chooses):**
> - `npc_role`: short string the LLM derives from the room theme (e.g. "hermit", "innkeeper").
> - `target_entity`: must be an **id that exists in the manifest** (the LLM picks one of the placed
>   props). Hard-validated against the manifest — a dangling id is rejected.
> - `dialogue`: `{greet, ask, wrong, thank}` — short free-text lines (this is the deliberate probe
>   of whether qwen can carry an NPC).
> - `objective`: fixed shape `{type:"fetch", target: <target_entity>, giver:"npc"}`.
>
> **Grammar:** GBNF, **single line** per the rule. Structure constrained; dialogue values are
> bounded free text (cap length in the grammar/validator, not unbounded).
>
> **Dialogue validator + fallback** (`foundry/`): a line is valid if it is within a length band,
> contains no code/markup/JSON, and (cheaply, deterministically) references the quest (e.g. mentions
> the target's category or a generic quest word). On failure, substitute a deterministic canned line
> (`"I am looking for the {category}. Bring it to me?"` etc.). The fallback firing is itself an event
> (feeds P2).
>
> **TDD:** unit-test with a **stub LLM** (no llama): (a) a manifest of 4 props → spec references a
> real id; (b) LLM returns a dangling id → rejected/Decision-Point; (c) junk dialogue → fallback
> fires; (d) good dialogue → passes through. No Blender, no network. Then ONE live `--live` smoke run,
> **twice**, reporting both quest specs side by side (show the stochastic spread).
>
> Report with commit-proof. Do not wire into Godot yet.

## P2 — Gameplay Decision Points (Forge)  ·  explainable failure

> Extend the existing Decision-Point layer (`foundry/decisions.py`, dual-register technical+plain,
> template registry, `render_cli`, `to_dict`) to the quest layer. Emit non-blocking Decision Points
> for: **no eligible target prop in the manifest** ("the quest needs something to fetch but the room
> is empty — add a prop?"); **dangling target id** from P1; **dialogue fallback fired** (transparency:
> "the model's line was unusable, used a template"); **NPC role empty/duplicated**. Each carries
> actionable choices and separates data from presentation, exactly like the material/age conflict
> DPs. TDD with synthetic specs (no llama). Confirm existing DP tests stay green. Commit-proof.

## P3 — Deterministic spec→Godot scene-compiler (Forge → rpg bridge)  ·  assembly

> **Goal:** deterministic Python that turns (quest spec + placed assets) into a **runnable Godot
> scene** (`.tscn`) for the rpg project, wiring everything by a **fixed tag→behaviour table** — the
> LLM never appears here. Mirror `foundry/publish.py` (the existing Godot bridge) for path/resource
> handling.
>
> The compiler:
> - instances each placed `.glb` at its position;
> - attaches a component by tag: target prop → `pickup`; other props → inert; NPC → `talk`+`give`;
> - drops in the **generic shell** (player, camera, HUD, win-screen — placeholders here; real
>   templates land in P4) and a **player spawn**;
> - for the NPC body, emits a **generated primitive marker** for now (a low-poly form from our
>   existing primitive generators — generated, not imported), to be replaced by P7;
> - writes the objective + dialogue into the scene as **data** (node metadata / a small resource the
>   loader reads) — never as code.
>
> **TDD:** the compiler output is text (`.tscn`) — assert structurally without launching Godot: the
> scene references the right node names, the target prop carries the `pickup` tag, the NPC carries
> `talk`+`give`, the dialogue/objective data round-trips. Commit-proof.

## P4 — Generic game-shell templates (rpg / Godot)  ·  the engine, generated not handcrafted

> **Goal:** the generic, reusable shell as **deterministic templates the P3 compiler stitches**, NOT
> a hand-built scene per game. Author once: player controller (first-person, Godot 4.6 + Jolt to
> match `project.godot`), camera, interaction raycast + "press E" prompt, a minimal HUD (objective
> line + interact prompt), a win screen. Reference (do not copy) the existing
> `playermovement.gd`/`pickupsystem.gd` to match project conventions, but write **clean** code; never
> touch `addons/godot_ai`.
>
> **Verify headlessly:** load the compiled scene with `godot --headless` (or the project's smoke
> harness) and assert it instantiates without error, the player + camera + HUD nodes exist, and the
> interaction raycast is live. Report the exact command + output. Commit-proof. (If a piece genuinely
> cannot be template-generated and must be hand-authored, that is allowed ONLY as a documented
> off-ramp with the evidence of what was tried — per `handcraft-last-resort`.)

## P5 — Interaction components + dialogue runner (rpg / Godot)  ·  the verbs

> Three small, generic, reusable component scripts the compiler attaches by tag:
> - **`pickup`** — raycast + E picks the prop up (carried in hand / one-slot), emits `picked_up(id)`.
> - **`talk`** — on E near the NPC, runs the dialogue runner: shows `greet`, then `ask`; advances a
>   simple NPC state machine (idle → quest-given → done).
> - **`give`** — talking to the NPC *while carrying* an item: if it is the target → show `thank`,
>   emit `quest_complete` → win screen; else → show `wrong`, keep searching.
>
> The **dialogue runner** is a tiny generic UI that displays the lines from the scene data (it never
> generates text). **Verify:** headless/unit where possible; then a scripted in-engine playthrough
> (walk → talk → pick wrong → wrong line → pick right → thank → win) driven by input simulation or a
> test harness, with the transcript pasted. Commit-proof.

## P6 — First end-to-end playable + live run (Forge + rpg)  ·  MILESTONE

> Wire P1→P3 into the live forge entrypoint so **one prompt produces the compiled, playable scene**.
> Run the full path on 2–3 room prompts (e.g. "a hermit's shack", "a blacksmith's back room"),
> **twice each** (qwen stochastic), and capture: the quest spec, the dialogue (and whether fallback
> fired), the compiled scene, and a headless load + scripted playthrough result. Produce a short
> report: for each prompt, did a solvable, winnable quest come out? Where did dialogue read as a real
> NPC vs. fall back? This is the honest read on **"can qwen carry an NPC."** Commit-proof. Expect
> rough edges — document them as the next tickets, do not paper over them.

## P7 — Character generation v1 (Forge / Blender foundry)  ·  the frontier, highest risk

> **Goal (hard, may slip to its own slice — be honest):** replace the generated primitive NPC marker
> with a **procedurally generated stylized humanoid → GLB**, from the ground up (no import). Extend
> the Blender foundry (mirror the existing mesh+material+bake→GLB generators and the closed style
> grammar from `asset-foundry-design`).
>
> Scope it minimally and verify ruthlessly:
> - a parametric low-poly stylized humanoid (proportions/palette chosen by the LLM within a closed
>   grammar, geometry built deterministically — topologist-not-geometer);
> - a **basic rig + a single idle animation** exported cleanly in the GLB;
> - a **quality gate**: watertight/poly-budget/scale like existing assets, PLUS "loads + animates in
>   Godot headless without error" and "faces the player".
> - **Off-ramp (still generated):** if a rigged animated humanoid proves intractable this pass, fall
>   back to a *generated* simpler character form (e.g. a generated golem/totem from primitives with a
>   simple idle bob) — never an import, never a hand-model. Document exactly what failed so the full
>   humanoid becomes a clean next-slice ticket.
>
> TDD/verify the deterministic parts; run the generator **twice** and confirm stable, gate-passing
> output. Commit-proof.

## P8 — Playability oracle + eval extension (Forge)  ·  the verification system

> Extend the eval harness (`foundry/eval/`: run/stability/regression/augment, signals, sampler,
> report) with a **playability oracle** — deterministic checks that a generated quest is actually a
> game: target entity exists in the scene; giver (NPC) exists; the win condition is reachable
> (target is gettable and deliverable); dialogue passed validation (and whether fallback fired);
> compiled scene loads headlessly. Add these as signals so a broken/unwinnable quest surfaces
> automatically (the harness should "write its own next ticket" the way the age regression did). Add
> a small quest corpus. TDD with synthetic specs; confirm prior eval tests green. Commit-proof.

---

## On the todo list (committed, not skipped)

- **Full rigged humanoid character generation** if P7 only reaches the off-ramp form.
- **NPC memory / persistence** via the P8 world-model (the quest spec is already the initial world
  state; wiring NPC quest-state into the transactional log comes later).
- **Multi-room, combat, inventory UI, NPC pathfinding** — explicitly out of this slice.

---

# Round 2 follow-ups (post-audit, 2026-06-19)

Audit verified FIX-0..3 work in real Godot (props render, floor+collision, humanoid resolves,
live `quest` command produces coherent qwen dialogue). Two gaps remained:

## FIX-5 — make wrong-item reactions reachable

Today only the target prop is tagged `pickup`; distractors are `inert` (no collider, not
pickable), so the player can only ever carry the correct item → the NPC's `wrong` branch is dead
code. Make **all** props pickable so the chosen "react to wrong items" feature works:
- `scene_compiler.py`: tag every prop `pickup` (not just the target), each with a
  `StaticBody3D`+`CollisionShape3D` so the raycast hits it; keep the quest target marked so only it
  satisfies `npc.gd`'s `carried == target` check. (Win logic already keys on the id, not the tag.)
- `pickup.gd`: support **switching** the carried item — picking up a different prop restores the
  previously-carried prop's visibility and carries the new one — so the player can try wrong items
  then the right one. Store the prop's node id (must match `target_entity`).
- Extend the Godot-in-the-loop probe (FIX-4 path) to assert: pick distractor → talk → `wrong`
  line shown; pick target → talk → `thank` → WinScreen visible.
- Update structural unit tests for the new per-prop collider/tag shape. Commit-proof, run-twice.

## FIX-6 — multi-model comparison runner (uses the hub swap)

Sequential, because 16 GB VRAM holds one model at a time. A script (e.g.
`foundry/quest_compare.py`) that, given a prompt + a list of model fragments + a scene prefix:
1. records the currently-loaded model (to restore at the end);
2. for each fragment: swap via the hub (`POST http://127.0.0.1:8003/api/swap` with `{fragment}`,
   stream the job until done) **or** `forge-model apply <fragment>`; wait for `:8002` `/health`;
3. runs `python -m foundry quest --request "<prompt>" --scene <prefix>_<alias>`;
4. captures each spec (npc_role, target, dialogue) into a comparison table;
5. restores the original model at the end.
Output: 4 scenes `<prefix>_<alias>.tscn` + a side-by-side dialogue table. The user then opens each
in Godot to compare. Verify the swap+health+restore loop against the real hub. Commit-proof.
