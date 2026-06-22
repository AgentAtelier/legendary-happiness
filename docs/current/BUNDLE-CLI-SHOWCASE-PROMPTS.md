# CLI Bundle — Showcase support workstreams (start now, parallel to orchestrator)

Implements the **CLI-delegable** parts of `docs/superpowers/specs/2026-06-22-generation-reveal-
showcase-design.md`. The orchestrator owns the hard core (Hunyuan asset pipeline + idle server,
`scene_compiler` exterior emit, live-assembly, `behaviour_gen`/`npc.gd`). **You own the three
workstreams below — they don't touch the orchestrator's files.** Read the spec + `AGENTS.md` first.

## 🔴 The three rules that bit us before (non-negotiable)
1. **Dedicated worktree.** `git worktree add ../forge-cli-showcase -b feat/cli-showcase` off HEAD. Do
   NOT edit the main checkout / another branch. (You've broken this 3×.)
2. **Paste the literal `tests/test_godot_smoke.py -q` result line.** "0 failed" on `pytest tests/`
   alone is NOT done; skipped/timeout/parse-error = FAILURE (see AGENTS.md → the hardened gate rule).
3. **Verify-before-build.** Much already exists; grep/read first, skip what's done, don't fabricate.

## 🚧 File ownership — do NOT edit these (orchestrator is live in them)
`scene_compiler.py`, `behaviour_gen.py`, `interpreter.py`, `brief.py`, `npc.gd`, and any new
`hunyuan_*`/asset-pipeline modules. If you need an env/lighting change in `scene_compiler.py`, **flag
it for the orchestrator** — don't edit it.

---

## WS-3 · Procedural-breadth backbone (the massive library) — biggest value
The library's breadth is procedural (instant, free, deterministic); Hunyuan only upgrades *bases*
later. Deepen the procedural side so any in-domain prompt has rich, varied assets.
- **More categories** in `category_registry.py` + a Blender generator each in `blender/build_asset.py`
  (additive to `_BUILDERS`; the orchestrator's flora generators are already committed — don't touch
  those, add new ones). Target the medieval-fantasy gaps: barrel, crate, chest, lantern, candle-stand,
  weapon-rack, anvil, cauldron, bedroll, sack, etc.
- **More materials** in `materials.py` (leather, ceramic, glazed, bronze, painted-wood) + per-instance
  seeded variation (hue/wear jitter) so rooms aren't monochrome.
- **Second-gen geometry**: a composable op layer (bevel/solidify/array/greeble) + parametric variation
  so generators yield richer silhouettes, not boxes. **Kitbash**: combine parts into composite props.
- *Verify:* `gate.py` green on every new asset (watertight/poly/lexicon); full suite + the Godot
  smoke gate; a render via V shows variety. **Flag for orchestrator:** live "room not monochrome".

## WS-4 · Generation-reveal UX shell + atmosphere [Godot runtime only]
- **Prompt-entry screen** (new `godot_template/scripts/prompt_screen.gd` + scene): type a prompt,
  submit → triggers assembly.
- **Player-facing Build-Report panel** (new `build_report_panel.gd`): renders the Brief's
  *understood / built / assumed / couldn't* as a clean in-world card (the legibility flex).
- **"World building…" feedback** during assembly.
- **Atmosphere tuning** in `day_night.gd` + the existing post-proc/SDFGI hooks (the B2 work) — *runtime
  scripts only*. Any `scene_compiler.py` env change → flag the orchestrator.
- *Verify:* headless-load 0 errors; `probe_playthrough.gd` exercises prompt→assemble→walk; paste the
  smoke result.

## WS-5 · Proxies + library QA [easy, feeds the orchestrator's pipeline]
- **Deterministic proxies**: a small module that voxelizes a procedural generator's box mesh to a
  `.ply` (the conditioning input the orchestrator's Hunyuan-Omni pipeline will consume). Pure +
  deterministic + unit-tested.
- **V auto-reroll QA**: wire/extend the V batch (`visual/`) so flagged library assets auto-reroll
  (the V-Task-6 reroll loop) and emit a worklist. You own `foundry/visual/`.
- *Verify:* unit tests for voxel determinism; V batch runs (orchestrator owns the live VLM swap — flag
  it).

---
**Order:** WS-3 first (biggest value, unblocks library richness), then WS-4, then WS-5. Each bundle =
stop-and-verify (full suite + pasted smoke gate). Commit per item with `git log`/`git status` proof.
