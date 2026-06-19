# Forge — Actual Capabilities

**Date:** June 19, 2026
**Branch:** `feat/slice1-rpg-fetch-quest`
**Test baseline:** 473 foundry tests passing + ~125 engine/devforge tests

This document describes what the project **actually does today** — built, tested,
committed. No roadmap items, no aspirational features. Just the working code.

---

## Two halves, one seam

The project has two independent halves that communicate only through flat
dicts/JSON over HTTP (MCP). They **never import each other**.

| Half | Location | Role |
|------|----------|------|
| **Foundry** | `foundry/` | Offline Python pipeline: asset generation, quest generation, scene compilation, evaluation |
| **Engine** | `engine/devforge/` | Online MCP server + AI pipeline: LLM-driven Godot scene building, spatial generation, tooling |

The **rpg** project at `/home/mrg/dev/games/rpg` is a separate Godot 4.6 repo
that receives compiled output from the foundry.

---

## Foundry (`foundry/`) — The Offline Pipeline

A standalone Python package with its own venv. Deterministic, testable, no
network requirement for unit tests.

### Asset Generation

- **`forge` command:** `python -m foundry <spec.json> <lexicon.json> <lib_dir>`
  generates a `.glb` 3D asset from a JSON spec through Blender headless.
- **`forge --request` command:** `python -m foundry --request "a low wooden
  coffee table" <lexicon.json> <lib_dir>` — natural language → asset spec via
  LLM (`AssetPlanner`), then Blender builds the mesh.
- **Generators:** `table`, `chair`, `shelf`, `cabinet`, `humanoid` — each with
  parameterised geometry, procedural materials (wood/stone/metal families with
  baked baseColorTexture, normalTexture, metallicRoughnessTexture), age-based
  entropy deformations, and edge bevelling.
- **GBNF grammar-constrained LLM calls:** the asset planner uses a single-line
  GBNF grammar to constrain the LLM output to valid JSON specs. Material and age
  are resolved deterministically *before* the LLM call (lexical matching), so
  the model never picks them.
- **Gate:** `GateResult` checks watertight topology, poly budget, and footprint
  bounds. Assets that pass are registered in the asset lexicon.
- **Publish:** `python -m foundry publish <lib_dir> <rpg_dir> <lexicon>`
  copies `.glb` files into the rpg Godot project and updates the lexicon paths.

### Quest Generation

- **Quest spec grammar:** `foundry/grammar/quest_spec.gbnf` constrains the LLM
  to emit structured JSON with `npc_role`, `target_entity`, `dialogue` (4 lines:
  greet/ask/wrong/thank), and `objective`.
- **`QuestBehaviourPlanner`:** takes a room theme + placed-entity manifest,
  calls the LLM with the grammar, and validates the output: target entity must
  exist in the manifest, dialogue is validated with canned fallbacks on failure,
  NPC role is cleaned (empty → default, too long → truncated, duplicates →
  collapsed).
- **Decision Points:** every validation failure emits a non-blocking
  `DecisionPoint` with a machine-readable `code`, plain-English explanation, and
  actionable choices. The planner never crashes on bad LLM output.
- **`quest` command (FIX-3):** `python -m foundry quest --request "a hermit's
  shack" --scene slice1_fetch` runs the full prompt→scene path:
  `QuestBehaviourPlanner.plan()` → `compile_scene()` → writes `.tscn` +
  `_quest_data.json` to `rpg/scenes/`. Supports `--model` and `--port` for
  targeting different LLM endpoints.

### Scene Compilation

- **`compile_scene()`:** deterministic Python that turns a quest spec +
  placed-entity manifest into a runnable Godot `.tscn` file. No LLM involved.
- **GLB instancing:** each prop and the NPC body are instanced via Godot 4
  header-line `[node name="X_model" parent="X" instance=ExtResource("id")]`
  format — GLBs render as `MeshInstance3D` children in Godot.
- **Physics:** emits a floor `StaticBody3D` + `CollisionShape3D` (BoxShape
  20×1×20), player `CollisionShape3D` (CapsuleShape), and collision shapes on
  the target prop and NPC so camera raycasts hit them.
- **Tag→script wiring:** target prop gets `pickup` tag + `pickup.gd`; NPC gets
  `talk`/`give` tags + `npc.gd`; inert props get no script. Shell scripts
  (`player.gd`, `interaction.gd`, `hud.gd`, `win_screen.gd`) are always
  attached.
- **Quest data:** writes a `_quest_data.json` sidecar with dialogue, objective,
  and NPC role so the scene loader reads it without parsing `.tscn` metadata.
- **Position guard:** props within 1m of the player spawn `(0,0,0)` are pushed
  away to avoid overlap.
- **46 unit tests** verify node names, types, tags, scripts, transforms,
  collision shapes, floor, sub-resources, GLB instancing, and quest data
  round-trips — all without launching Godot.

### Evaluation Harness

- **`foundry.eval` CLI** with subcommands: `run`, `stability`, `regression`,
  `augment`, `augment-quest`.
- **`run`:** drives a corpus of NL requests through the full forge pipeline
  (plan → compile → build → gate), captures `RunRecord` per request. Supports
  `--no-build` for planner-only runs.
- **Signals:** `compute_signals(record)` returns objective tags: `build_error`,
  `gate_rejected`, `decision_fired`, `size_mismatch`, `material_mismatch`,
  `material_conflict`, `age_mismatch`, `clean`. Feeds the sampler.
- **Quest signals (P8):** `compute_quest_signals(record)` returns:
  `quest_build_error`, `quest_dialogue_fallback`, `quest_no_target`,
  `quest_no_npc`, `quest_unwinnable`, `quest_decision_fired`, `clean`.
- **Sampler:** severity-weighted stratified sampling — high-severity records
  go in unconditionally, low-severity are sampled to a cap, clean records form
  a baseline.
- **Corpus augmentation:** slot-filling from real lexicons (generator nouns,
  material keywords, wear words) with dedup and validity filtering. Quest
  corpus variant generates room-themed prompts from NPC role + room type +
  mood + furniture lexicons.
- **Stability:** measures run-to-run planner variance by calling the LLM N
  times per request and comparing outputs.
- **Regression:** golden-master comparison against saved expectations with
  `--update` to re-bless.

### Godot-in-the-Loop Smoke Tests

- **`test_godot_smoke.py`:** compiles a scene, runs `godot --headless` with
  `probe_smoke.gd`, and asserts: `MeshInstance3D_count > 0`, floor collision
  exists, player collision exists, no resource errors in stderr, target prop
  reachable by physics raycast.
- **5/5 smoke assertions pass** (FIX-0 through FIX-2).
- **Scripted playthrough probe (FIX-4):** `probe_playthrough.gd` simulates
  the quest interaction flow (talk → pickup → deliver) in headless Godot and
  checks WinScreen visibility. Probe infrastructure runs but NPC `await`-based
  state machine doesn't fully resolve in headless `SceneTree._process()` —
  needs deeper investigation.

### Blender Integration

- **`build_asset.py`:** runs inside Blender (`blender --background --python
  build_asset.py -- <spec.json> <out.glb>`). Builds geometry from box
  primitives via BMesh, applies UV unwrapping, procedural material shader
  trees (wood/stone/metal), Cycles-CPU baking of baseColor, normal, and
  metallicRoughness textures, entropy deformations, and glTF export.
- **`render_asset.py`:** renders a Cycles thumbnail of a GLB for visual
  inspection.
- **Blender 5.1 compatible** (FIX-2: `_add_idle_bob` handles both 4.x
  `action.fcurves` and 5.x `action.fcurve_ensure_for_datablock` APIs).

### RL Integration

- **`llm.py` / `FoundryLLM`:** injectable LLM callable that connects to a
  local llama.cpp server. Tests inject FAKE callables for determinism.
- **`planner.py` / `AssetPlanner`:** prompt → grammar-constrained LLM call →
  parameter clamping → material/age resolution. Returns `(spec, decisions)`.
- **`behaviour_gen.py` / `QuestBehaviourPlanner`:** room theme + manifest →
  grammar-constrained LLM call → dialogue validation → NPC role cleaning →
  target entity validation. Returns `(quest_spec, decisions)`.
- **`material_resolver.py` / `age_resolver.py`:** deterministic lexical
  matching for material and age — run BEFORE the LLM call, so the model
  never chooses them.

### World Model

- **`world/model.py`:** `World` dataclass + `propose()` function for managing
  world state with validated changes.
- **`world/invariants.py`:** referential integrity checks and zone budget
  enforcement for generated scenes and entities.

---

## Engine (`engine/devforge/`) — The Online Pipeline

An MCP server + AI pipeline that builds Godot scenes through LLM-driven
planning. Communicates with the Godot editor via the godot-ai plugin.

### Core Pipeline

- **`mcp_server.py`:** MCP tool registration (`apply_spec`, `get_scene`,
  `run_project`, etc.) with thread-safe execution.
- **`engine.py`:** shared pipeline orchestrator — prompt → LLM plan → compile
  to ops → execute in Godot via MCP.
- **`architecture_planner.py`:** LLM-driven architecture planner with
  grammar-constrained output. Includes `DeterministicPlanner` for pattern
  pre-routing (rename/delete/known entities skip the LLM).
- **`architecture_compiler.py`:** plan → DevForge IR compiler.
- **`operation_generator.py`:** IR → Godot operations (node creation, property
  setting, script attachment, signal connection).
- **`repair_engine.py`:** auto-repair of failed operations (Godot 3→4 type
  renames, missing script path prefixes, 3-retry escalation).
- **`context_assembler.py`:** builds planner context from scene graph, system
  graph, and conversation history — with a 24K token budget allocated across
  sections.

### LLM Infrastructure

- **`llm/llama_client.py`:** connection to local llama.cpp with Gemma chat
  template, sampling params (`top_p=0.9`, `top_k=40`, `seed=0`), grammar
  self-test, truncation detection, connection retry with backoff.
- **`llm/claude_client.py`:** optional Claude backend (`DEVFORGE_LLM_BACKEND=
  claude`).
- **`llm/router.py`:** grammar dispatch via `inspect.signature()`, circuit
  breaker (3 consecutive failures → 30s cooldown), `last_truncated` detection.
- **`llm/gateway.py`:** rate-limiting gateway with budget enforcement.

### Spatial Generation

- **`spatial/scatter.py`:** deterministic object placement with minimum
  spacing constraints.
- **`spatial/voronoi.py`:** Voronoi-based town/city layout generation.
- **BSP, WFC, SSP planners:** binary space partition, wave function collapse,
  and semantic space planners for room and building layouts.
- **`spatial/asset_lexicon.json`:** 13 asset types (table, shelf, chair,
  cabinet, humanoid, fridge, stove, counter, sink, tree, bush, flower, rock)
  with footprints, heights, and material variants.

### Tooling Suite (engine tests exist for all of these)

- **Scene Doctor:** deterministic audit rules walking the scene tree (collision
  shape parentage, zero mass, dangling script refs, null meshes, etc.).
- **Batch Operator:** `filter(type/name/subtree) → preview → confirm →
  batch_execute`. Regex-parse common queries; LLM-parse exotic ones.
- **Error Triage:** `get_logs` → deterministic parse → classify against ~30
  most common Godot runtime errors → explain + point at file/line.
- **Polish Pass:** game-feel audit (missing screen shake, unsmoothed cameras,
  zero-energy lights, missing pickup particles).
- **Project Navigator:** `find_symbols` + `search_filesystem` → ranked
  answer with paths.
- **Template Forge:** human-written system templates; LLM selects and
  parameterises (fps_controller, interaction_system, inventory, save,
  quest_system, dialogue_ui, etc.).
- **Lorekeeper:** content DB with referential integrity checks, schema
  validation, GBNF-constrained content generation.
- **Quest Graph Validator:** reachability analysis on quest-as-data directed
  graphs — detects soft-locks and unreachable content.
- **Performance Sentinel:** `get_performance_monitors` + per-area budgets
  with regression tracking.
- **Signal/Dependency Mapper:** parses GDScript for signal declarations,
  `emit_signal()` calls, and `.connect()` calls.
- **Test Harness:** deterministic test scaffolds from parsed function
  signatures; LLM explains failures but never invents test logic.
- **Balance Simulator:** Monte Carlo over content DB for economy/combat
  balance queries.
- **Design Companion:** genre pattern database with coverage analysis.
- **Dialogue Engine:** schema-constrained dialogue tree validation; LLM
  generates prose INTO the tree structure.
- **Smoke Runner / Dailies:** scripted auto-playtest — launch game, teleport
  through POIs, capture screenshots + logs + perf samples.
- **Progress Journal:** time-series datapoint store — every audit score,
  perf sample, and batch op is recorded.
- **Scene Refactorer:** extract subtree → create `.tscn` → replace with
  instance → update script references.

---

## Hub (`hub/`) — Operations Panel

A FastAPI server for managing the forge stack.

- **Model management:** swap LLM models, estimate VRAM, detect drift.
- **Test bench:** extensible gauntlet system (`forge_testbench/`) for
  benchmarking pipeline capabilities — garden gauntlet, SSP gauntlet,
  Voronoi gauntlet, diagnostics.
- **Stack orchestration:** start/stop/restart llama.cpp, DevForge, and
  godot-ai processes.
- **Chain health:** monitor all services, detect failures.
- **Scoring:** `forge_score.py` for pipeline output evaluation.

---

## RPG Project (`/home/mrg/dev/games/rpg`) — Godot 4.6 Game

A separate Godot 4.6 project (Jolt physics) that receives compiled output
from the foundry.

- **Game shell scripts:** `player.gd` (first-person CharacterBody3D with
  WASD + mouse-look, carried_item state), `interaction.gd` (camera raycast,
  E-to-interact, `_forge_tag` metadata reading), `hud.gd` (objective +
  interact prompt display), `win_screen.gd` (quest completion overlay).
- **Component scripts:** `pickup.gd` (sets `Player.carried_item`, hides
  object, emits `picked_up` signal), `npc.gd` (state machine: IDLE →
  QUEST_GIVEN → DONE, quest data loading from JSON sidecar, dialogue
  display with 2-second timers, win emission).
- **Smoke test probes:** `probe_smoke.gd` (headless scene inspection:
  MeshInstance3D count, floor/player collision, raycast reachability),
  `probe_playthrough.gd` (scripted quest interaction flow simulation).
- **Assets:** GLB files published by the foundry (`humanoid_rough_granite.glb`,
  `table_worn_oak.glb`, `shelf_rough_granite.glb`, `cabinet_wrought_iron.glb`).
- **Scenes:** `main.tscn` (empty shell), `slice1_fetch.tscn` (generated
  fetch-quest scene).
- **100+ GDScript files** in `scripts/` covering arena management, camera,
  collectibles, entity spawning, combat, guard AI, and game interaction
  systems (reference code from earlier DevForge generations).

---

## What doesn't exist yet (honest gaps)

- **Scripted playthrough doesn't complete in headless Godot** (FIX-4) — NPC
  `await`-based state machine timers don't fully resolve in `SceneTree.
  _process()`. The probe infrastructure runs but the quest doesn't complete.
- **Quest command doesn't do asset-gen** — `python -m foundry quest` uses a
  hardcoded manifest. Individual assets must be forged separately via
  `python -m foundry --request`.
- **No headless Godot player simulation** — the interaction tests can call
  `on_interact()` directly but can't simulate WASD movement or camera
  raycasting in headless mode.
- **Engine pipeline needs live LLM** — the engine/devforge side requires a
  running llama.cpp server. Foundry unit tests use FAKE LLMs.

---

## Test Summary

| Suite | Count | Status |
|-------|-------|--------|
| Foundry tests (all except Blender + Godot smoke) | 473 | ✅ All pass |
| Scene compiler unit tests | 46 | ✅ All pass |
| Godot-in-the-loop smoke tests | 5 | ✅ All pass |
| Godot scripted playthrough | 1 | ⚠️ Probe runs but quest doesn't complete |
| Engine/devforge tests | ~125 | ✅ All pass (requires llama.cpp) |
