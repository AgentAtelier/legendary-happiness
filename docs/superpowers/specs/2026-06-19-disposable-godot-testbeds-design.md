# Disposable Godot Test-Beds — Design Spec

**Date:** 2026-06-19
**Status:** design approved, ready for implementation plan
**Topic:** the foundry scaffolds a fresh, disposable, version-pinned Godot project per run, instead of
writing every slice into the one shared `rpg` project.

## Why

Two pains, one root cause: everything runs through a single aging `rpg` project.
- **Cruft accretion** — `rpg/scripts/` holds ~97 old DevForge auto-gen scripts mixed with 6 slice scripts.
- **Version drift** — the CLI/tooling is Godot **4.7**, but the `rpg` project declares **4.6** and the
  user's editor is 4.6. A 4.7-touched project + import cache won't open cleanly in a 4.6 editor —
  this is the confirmed-most-likely cause of "Couldn't save scene / dependencies (instance or
  inheritance) couldn't be satisfied."

Making the Godot project a **generated, disposable output** fixes both at the source: nothing accretes,
and every project is born on the pinned version with a clean pre-built import cache.

**Lifecycle decision:** disposable test-beds — the foundry scaffolds a clean project per run, used to
test, then discarded/regenerated. The project is an output, not a hand-maintained artifact. This
extends "generation-first" / "topologist not geometer" to the project shell itself.

## Approach (chosen: A — template-stamp + pre-import)

A maintained, version-pinned template project lives in the foundry. Each run copies it, stamps in the
compiled scene + referenced assets, and pre-imports it headlessly so it opens clean. (Rejected: B
fully-programmatic project.godot generation — reinvents boilerplate, drifts from valid configs; C
shared-core symlinks — fragile importer behavior, not self-contained.)

### Approved sub-decisions
- `builds/` lives at the **repo root, gitignored**.
- The compiled scene is set as the project's **`main_scene`**, so `godot --path builds/<name>` launches it.
- The now-vestigial slice scripts in `rpg/scripts/` are **left in place** (cleanup is out of scope).

## Architecture

### 1. The template — `foundry/godot_template/`  (committed, foundry-owned tooling)
A minimal, valid Godot project:
- `project.godot` — pinned to **Godot 4.7**, Jolt physics, the input actions the shell needs
  (`ui_cancel` for ESC is default; WASD/E are read as raw keycodes in the scripts, so no custom
  actions are required). **No `godot_ai` addon.**
- `scripts/` — the 6 reusable shell scripts **moved here from `rpg/scripts/`** as the canonical copy:
  `player.gd`, `interaction.gd`, `hud.gd`, `win_screen.gd`, `pickup.gd`, `npc.gd`.
- `probe_smoke.gd`, `probe_playthrough.gd` — the Godot-in-the-loop verification probes.
- empty `scenes/` and `assets/`, plus a `.gitignore` (`.godot/`).

The template is itself openable, so the shell can be sanity-checked in isolation.

### 2. The scaffold step — `foundry/scaffold.py`
`scaffold_project(name, quest_spec, manifest, *, template_dir, out_root="builds", asset_src) -> build_path`:
1. `copytree(template_dir, builds/<name>/)`.
2. `compile_scene(...)` → `builds/<name>/scenes/main.tscn` (+ `scenes/main_quest_data.json`).
   `npc.gd` reads `<scene>.tscn → <scene>_quest_data.json`, so naming the scene `main` keeps that working.
3. Set `run/main_scene="res://scenes/main.tscn"` in the build's `project.godot`.
4. Copy **only the assets the scene references** (each referenced GLB + its `.import` sidecar + any
   sibling baked textures the GLB depends on) into `builds/<name>/assets/`. Source them from the same
   canonical location `publish.py` reads today (the foundry's forged-asset output / library — the CLI
   implementer confirms the exact path from `publish.py`), **not** from `rpg/assets`. Reuse/extend
   `publish.py`'s placement logic so dependency-completeness lives in one place; the pre-import +
   smoke probe (step 5 / §5) catch any missing dependency.
5. `godot --headless --path builds/<name> --import --quit` to pre-build the `.godot` import cache.
6. Return the build path.

### 3. Builds directory
`builds/` at repo root, gitignored, disposable, self-contained (a few MB each).

### 4. Entrypoint changes (retarget off `rpg`)
- `python -m foundry quest --request "<prompt>" --name <name>`: scaffold `builds/<name>/`, print the
  one-line launch command. Remove the `--rpg-dir` default write-into-rpg behavior.
- `quest_compare`: scaffold `builds/compare_<alias>/` **per model** (one isolated project each).
  Fold in, in the same pass:
  - **27B fit:** pre-configure a fitting context via `forge-model set qwen3-6-27b ctx=8192` (drop to
    4096 if it still OOMs; q4 KV cache is already on in `LLAMA_BASE_ARGS`, so context is the remaining
    lever — the 12.6 GB weights are fixed). Verify the new fit estimate reports `fits`/`tight` and
    that it actually loads and serves.
  - **VRAM pre-flight:** before swapping to a model, check its fit; skip (with a clear message) any
    model whose fit status is `spills`, so an unfittable model is never attempted.
  - **Safe restore:** the swap/restore path runs `systemctl --user reset-failed forge-llama.service`
    before restarting, so a prior OOM's start-limit can't block recovery (the failure that took
    llama down during the first comparison run).

### 5. Verification (Godot-in-the-loop — the non-negotiable)
The smoke + playthrough probes run against a **freshly scaffolded build**, asserting a clean project
actually opens, instances meshes, has floor/player collision, raises no missing-resource errors, and
the scripted talk→wrong→right→win loop reaches the win screen. This bakes "does a generated project
open and play" into CI, preventing a repeat of the scene-won't-open class. Structural `.tscn` parsing
is necessary but never sufficient — behavior in real Godot is the gate.

## What moves / what's untouched
- **Moves:** the 6 shell scripts' canonical home → `foundry/godot_template/scripts/`. The probes →
  the template. The `quest` and `quest_compare` write targets → `builds/`.
- **Untouched:** the `rpg` project (stays as the DevForge sandbox; vestigial slice scripts remain).
  The foundry's asset generation, behaviour-gen, grammar, eval harness, and the scene compiler's core
  output format are unchanged — only its write destination and the surrounding scaffold are new.

## Out of scope
Multi-room scaffolds; removing cruft from `rpg`; committing/curating `builds/`; prompt-driven room
contents (the quest manifest stays the fixed default for now); generated characters beyond the
existing P7 humanoid.

## Testing
- Unit: `scaffold_project` produces a directory with `project.godot` (4.7, correct `main_scene`),
  `scenes/main.tscn`, the shell scripts, and only the referenced assets — assertable without Godot.
- Godot-in-the-loop: a scaffolded build passes the smoke + playthrough probes (real `godot --headless`).
- `quest_compare`: VRAM pre-flight skips `spills` models; restore runs `reset-failed`; verified once
  against the real hub that llama returns healthy on the original model.
- Regression: the full foundry suite stays green; `quest`/`quest_compare` no longer reference `rpg`.
