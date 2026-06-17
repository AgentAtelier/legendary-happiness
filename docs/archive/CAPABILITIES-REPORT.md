# Forge Project — Capabilities Report

**Date:** June 14, 2026  
**Target:** Open-world RPG with weather system, day/night cycle, terrain, quests, NPCs  
**Scope:** What the AI→Godot pipeline can build today, what it cannot yet, and what's needed to bridge the gap

---

## Architecture Summary

The Forge stack has two communication paths into the Godot editor:

```
User prompt → Odysseus (agent) → DevForge (pipeline) → llama.cpp (LLM) → Godot editor
                                   └─ arch planner: entities → systems → compiler → ops
                                   └─ ops planner:  direct operation generation (behind flag)
```

DevForge calls godot-ai's MCP tools to execute operations in the editor. The pipeline does **not** directly access every godot-ai tool — it generates a fixed set of operation types that map to a subset of godot-ai's surface (currently 7 op types: `add_node`, `set_property`, `create_script`, `attach_script`, `connect_signal`, `rename_node`, `delete_node`).

The godot-ai MCP server wrapping the editor exposes **41+ tools** covering nearly every Godot subsystem — but most are not yet reachable through the pipeline.

---

## Part 1: What the Pipeline CAN Build Today

### Tier 1 — Scene Structure (solid)

| Capability | How | Quality |
|-----------|-----|---------|
| **Node trees** | Any Godot type, nested to arbitrary depth (Arena→Player→PlayerCamera, Collectibles→Coin_Red→CollisionShape3D) | ✅ Fully working. Parent paths resolve correctly under `/Main`. |
| **Scene root awareness** | Nodes parent under the edited scene root, not phantom `/root/` paths | ✅ Verified by shootout assertions (arena_exists, player_type, etc.) |
| **Node types** | 50+ Godot 3D types available in the grammar (CharacterBody3D, Area3D, Camera3D, MeshInstance3D, CollisionShape3D, Label, CanvasLayer, etc.) | ✅ Full Godot 3D vocabulary. 2D types also available (Button, Label, Sprite2D, etc.) |
| **Naming** | Arbitrary node names | ✅ No naming restrictions |

### Tier 2 — Visual Properties (solid)

| Capability | How | Quality |
|-----------|-----|---------|
| **Primitive meshes** | BoxMesh, SphereMesh, CapsuleMesh, CylinderMesh, PlaneMesh — assigned via `node_set_property` with `__class__` resource dicts | ✅ Verified. Player mesh + coin meshes pass shootout assertions. |
| **Collision shapes** | BoxShape3D, SphereShape3D, CapsuleShape3D, CylinderShape3D — assigned as shape resources on CollisionShape3D children | ✅ Verified. Coin colliders pass shootout. |
| **Materials & colors** | StandardMaterial3D with albedo_color (r,g,b,a) | ✅ Verified. All 5 coin colors pass shootout assertions. |
| **Transforms** | Position (Vector3), rotation (Vector3), scale (Vector3) | ✅ Placed objects at exact coordinates. |
| **Text** | Label text property | ✅ ScoreLabel with "Score: 0" verified in shootout. |
| **Camera** | Camera3D creation, positioning, current flag | ✅ PlayerCamera passes assertion. |
| **Light** | DirectionalLight3D with light_energy | ✅ Verified. |

### Tier 3 — Script Behavior (working)

| Capability | How | Quality |
|-----------|-----|---------|
| **GDScript creation** | Full `.gd` files written to `res://scripts/` with `extends`, `_process`, variables | ✅ Verified. Scripts compile and run. |
| **WASD movement** | `_process(delta)` with `Input.get_vector()` or `Input.is_key_pressed()` | ✅ Verified. movement_input passes shootout. |
| **Signal connections** | `body_entered` connected to `_on_body_entered()` handler | ✅ Verified. collect_handler passes shootout. |
| **Node cleanup** | `queue_free()` called on self after collection | ✅ Verified. collect_qfree passes shootout. |
| **Score tracking** | Reference to ScoreLabel, increment variable | ✅ Verified. collect_score passes shootout. |
| **Script attachment** | Scripts attached to correct nodes (Player, coins) | ✅ Verified. player_script passes shootout. |

### Tier 4 — UI (working)

| Capability | How | Quality |
|-----------|-----|---------|
| **CanvasLayer** | UI root separate from 3D world | ✅ Verified. ui_canvas passes shootout. |
| **Labels** | ScoreLabel with text, anchors, offsets | ✅ Verified. ui_label passes shootout. |

### Tier 5 — Scene Verification (working)

| Capability | How | Quality |
|-----------|-----|---------|
| **Scene completeness** | Auto-injects missing Camera3D + DirectionalLight3D if scene has neither | ✅ Prevents invisible/black renders. |
| **No pollution** | Avoids duplicating cameras/lights on re-runs | ✅ Verified. no_dup_cameras passes. |
| **Error-free execution** | All generated operations validated before execution | ✅ Zero pipeline errors on successful builds. |

### Tier 6 — Pipeline Diagnostics (working)

| Capability | How | Quality |
|-----------|-----|---------|
| **Per-stage latency** | Planning, compilation, execution time tracked in ms | ✅ Visible in probes and shootout scorecards. |
| **Retry tracking** | `plan_retries` counts retries before first success | ✅ Visible in shootout. |
| **Repair tracking** | `repair_count` counts post-completeness repair passes | ✅ Visible in shootout. |
| **Failure attribution** | Every failed shootout assertion cross-referenced to pipeline stage (plan/compile/execute/completeness/runtime) | ✅ Answers "why did this fail?" |
| **A/B planner comparison** | `--all-planners` runs each model through both `arch` and `ops` planner modes, produces side-by-side scorecard | ✅ Ready for rollout decision. |
| **Regression detection** | Compares current score against best previous; flags >10-point drops | ✅ Catches silent model degradation. |

---

## Part 2: What the Pipeline CANNOT Do Yet

### Gap Category A — godot-ai tools exist but pipeline doesn't generate ops for them

These capabilities have working MCP tools in godot-ai but no path through DevForge's planner→compiler→executor chain. Adding them requires extending the operation schema, GBNF grammar, and compiler in DevForge — not touching godot-ai or Odysseus.

| Gap | godot-ai Tool | What's Missing | Priority for RPG |
|-----|--------------|----------------|------------------|
| **Particle effects** | `particle_manage` (create, set_main, set_process, set_draw_pass, apply_preset, restart) | No op types for GPUParticles3D creation or configuration. Rain, snow, fire, dust, magic effects are impossible. | 🔴 Critical — weather system |
| **Audio** | `audio_manage` (player_create, set_stream, play, stop) | No op types for AudioStreamPlayer3D creation, stream assignment, or playback. Ambient wind, footsteps, thunder impossible. | 🔴 Critical — weather + immersion |
| **Environment / Sky** | `resource_manage.environment_create`, `material_manage` | No op types for WorldEnvironment, Sky, fog, or procedural sky materials. Day/night cycle impossible. | 🔴 Critical — weather + time |
| **Input map** | `input_map_manage` (add_action, bind_event) | No op types for creating custom input actions. Sprint, jump, interact, inventory keys must be manually set in Project Settings. | 🟠 High — player controls |
| **Animations** | `animation_manage` (player_create, add_property_track, add_method_track, create_simple, presets) | No op types for AnimationPlayer or animation tracks. Door opening, character idle, chest opening impossible. | 🟠 High — world interactivity |
| **Complex resources** | `resource_manage` (noise_texture_create, gradient_texture_create, curve_set_points) | No op types for NoiseTexture2D (terrain heightmaps), GradientTexture2D, or Curve resources. | 🟡 Medium — terrain/weather |
| **Advanced materials** | `material_manage` (set_shader_param, apply_preset, create with shader) | Only StandardMaterial3D albedo_color is supported. Shaders, metallic/roughness, emission, normal maps impossible. | 🟡 Medium — visual quality |
| **Autoloads** | `autoload_manage` (add, list) | No op types for creating game singletons. Inventory manager, quest log, save system, event bus all impossible. | 🔴 Critical — RPG systems |
| **Multi-scene** | `scene_manage` (create, open), `scene_open` | Pipeline always targets the current scene. Open-world chunking or interior/exterior scenes impossible. | 🟡 Medium — open world |
| **Runtime eval** | `editor_manage.game_eval` | No way to execute GDScript in the running game from DevForge. Runtime debugging or dynamic content generation impossible. | 🟢 Low — debugging |
| **UI beyond labels** | `ui_manage` (set_anchor_preset, build_layout, draw_recipe) | Only Label text is settable. Buttons, panels, containers, theme application impossible. | 🟡 Medium — RPG UI |

### Gap Category B — Capabilities that need both godot-ai AND pipeline work

These require changes on both sides — either new godot-ai MCP tools or deeper editor integration.

| Gap | What's Missing | Priority for RPG |
|-----|---------------|------------------|
| **Terrain** | Godot has no built-in terrain API accessible via MCP. Would need a HeightMapShape3D + MeshInstance3D + noise-based mesh generation approach, or a custom terrain tool. | 🔴 Critical — open world |
| **NavMesh / Pathfinding** | NavigationRegion3D + NavigationAgent3D types exist in the grammar, but no op types for baking navmeshes, setting navigation layers, or pathfinding queries. | 🟠 High — NPC movement |
| **Save/Load system** | No serialization of game state. Would need a custom autoload + resource-based save format + scene state capture/restore. | 🔴 Critical — RPG persistence |
| **Inventory system** | No data model, no UI for item grids, no drag/drop. Would need custom autoload + resource definitions + UI. | 🔴 Critical — RPG core |
| **Quest system** | No quest state machine, no objective tracking, no dialogue integration. Would need custom autoload + data-driven quest definitions. | 🔴 Critical — RPG core |
| **Dialogue system** | No dialogue tree, no NPC interaction pattern, no text display system. Would need UI + data format + interaction pattern. | 🔴 Critical — RPG narrative |
| **NPC AI** | No behavior tree, state machine, or scheduling system. NavMesh is the first prerequisite. | 🟠 High — world life |
| **LOD / streaming** | No level-of-detail or scene chunk loading. Multi-scene support is prerequisite. | 🟡 Medium — open world performance |
| **Combat system** | No damage model, health, hitboxes, projectile spawning. Could be scripted but needs patterns. | 🟡 Medium — RPG action |
| **Crafting system** | No recipe system, no inventory integration. Data model problem. | 🟢 Low — post-MVP |

### Gap Category C — LLM capability ceilings

These are limits of the current models, not the pipeline.

| Gap | Description | Mitigation |
|-----|-------------|------------|
| **Long scripts** | LLMs generate syntactically correct but logically limited GDScript (~20-50 lines). Complex systems (inventory, AI) require hundreds of lines across multiple files. | Template library + multi-turn script generation + code review pass |
| **Planning depth** | The current shootout prompt (collectible arena) is ~40 lines. An open-world terrain + weather + NPCs + quests prompt would be >200 lines and likely exceed the planner's effective reasoning depth. | Decompose into sequential `apply_spec` calls per subsystem |
| **Consistency across calls** | Each `apply_spec` call is independent. No shared memory of what was built previously. | Artifact ID chaining + scene snapshot diff for context |
| **Model quality variance** | qwen3 (14B) scores highest on the shootout. Smaller models produce incomplete or broken scenes. | Model selection guidance + per-model capability profiles |
| **Generation speed** | Planning takes 20-60 seconds. Execution takes 5-15 seconds. A full scene with 10+ `apply_spec` calls would take 10+ minutes. | Batch operations + async planning + model swap to qwen3 for building |

---

## Part 3: Path Toward Open-World RPG + Weather

### What we have that maps directly

| RPG Need | Status | What Exists |
|----------|--------|-------------|
| Player character | ✅ Done | CapsuleMesh CharacterBody3D with WASD movement script + follow camera |
| Collectible items | ✅ Done | Area3D coins with collision, mesh, color, body_entered→queue_free, score tracking |
| HUD / UI | ✅ Done | CanvasLayer + Label with text property |
| Scene lighting | ✅ Done | DirectionalLight3D placement + light_energy |
| Scene structure | ✅ Done | Arbitrary node nesting, parent/child relationships |
| Camera system | ✅ Done | Camera3D creation, positioning, current flag |
| Basic scripting | ✅ Done | _process(delta), signal connections, Input handling |

### What we need to build next (in order)

#### Phase A — Weather System (first vertical slice)

The weather system is a good first target because it exercises the biggest untapped godot-ai tools and is visually impressive without needing complex game logic.

| Step | What to Build | Tools to Wire | Est. Difficulty |
|------|--------------|---------------|-----------------|
| A1 | `set_environment` op type — create/configure WorldEnvironment with Sky, fog, ambient light | `resource_manage.environment_create`, `node_set_property` on WorldEnvironment | Day |
| A2 | `set_particles` op type — create GPUParticles3D with rain/snow presets | `particle_manage.create`, `particle_manage.set_main`, `particle_manage.apply_preset` | Day |
| A3 | `play_audio` op type — create AudioStreamPlayer3D with stream assignment | `audio_manage.player_create`, `audio_manage.set_stream` | Day |
| A4 | Day/night cycle — rotate DirectionalLight3D over time, lerp sky colors | Script template + existing `set_property` | Hour |
| A5 | Weather state machine — clear → cloudy → rain → storm → clear with transitions | Script template + op types from A1-A3 | Day |
| A6 | Weather zone volumes — Area3D triggers that change weather on enter | Script template + existing `add_node` | Hour |

**After Phase A:** The pipeline can build a scene with dynamic weather — rain particles, ambient wind/thunder audio, sky changes, day/night cycle. This proves the "system generation" pattern.

#### Phase B — RPG Foundations

| Step | What to Build | Tools to Wire | Est. Difficulty |
|------|--------------|---------------|-----------------|
| B1 | `create_autoload` op type — register game singletons | `autoload_manage.add` | Hour |
| B2 | Inventory autoload + data model — item definitions, stack counts, equipped slots | Script template + autoload from B1 | Day |
| B3 | Inventory UI — grid container with item slots, drag/drop | `ui_manage.build_layout`, `ui_manage.draw_recipe` | Day |
| B4 | `set_input_map` op type — create custom input actions | `input_map_manage.add_action`, `input_map_manage.bind_event` | Hour |
| B5 | Quest system autoload — quest definitions, objectives, completion tracking | Script template + autoload from B1 | Day |
| B6 | Dialogue system — dialogue trees, NPC interaction, text display | Script template + UI from B3 | Day |

#### Phase C — Open World

| Step | What to Build | Tools to Wire | Est. Difficulty |
|------|--------------|---------------|-----------------|
| C1 | Terrain mesh generation — heightmap from NoiseTexture2D applied to a subdivided PlaneMesh | `resource_manage.noise_texture_create`, `node_set_property` | Day |
| C2 | `open_scene` / `create_scene` op types — multi-scene management | `scene_manage.create`, `scene_manage.save_as`, `scene_open` | Hour |
| C3 | Chunk-based world streaming — load/unload terrain chunks based on player position | Script template + scene ops from C2 | Day |
| C4 | NavMesh baking + `set_navigation` op type — pathfinding regions | `NavigationRegion3D` creation + `NavigationAgent3D` setup | Day |
| C5 | NPC spawning + basic AI — wander, idle, flee behaviors | Script templates + nav from C4 | Day |

### What stays manual (or needs different tools)

Some RPG subsystems are better built outside the AI pipeline:

| System | Why Manual | Alternative |
|--------|-----------|-------------|
| **3D assets** (character models, animations, textures) | AI can't create `.blend`/`.fbx` files or texture atlases. | Blender, asset store, or proc-gen mesh scripts |
| **Terrain sculpting** | Godot's terrain system requires manual heightmap painting or external tools. | WorldMachine, Houdini, or custom proc-gen |
| **Animation rigging** | Skeleton + animation tree setup is editor-UI-heavy. | Manual in Godot editor, then AI scripts for playback |
| **Shader authoring** | Visual shader graphs and GLSL are beyond current LLM capability. | Manual + material presets |
| **Sound design** | AI can't create `.wav`/`.ogg` files. | Asset library or proc-gen audio |

---

## Part 4: Operational Summary

### The pipeline today is a **scene builder**

It takes a natural-language prompt and produces a complete, working Godot scene with nested nodes, meshes, collision shapes, materials, scripts, and UI — all in one `apply_spec` call. The result is verified against static + runtime assertions and the game actually runs.

**Current ceiling:** ~77-85/100 on the collectible arena shootout. The remaining failures are edge cases in script content quality, not structural gaps.

### The pipeline tomorrow needs to become a **game builder**

To reach the open-world RPG target, the pipeline must grow from 7 operation types to ~15, gaining the ability to orchestrate particles, audio, animation, environments, input maps, autoloads, and multi-scene projects. Each new op type requires:
1. GBNF grammar extension (planner must be *allowed* to emit it)
2. Compiler mapping (LLM output → DevForge op → godot-ai command)
3. Verification (can we assert the result?)
4. Shootout assertion (does the benchmark catch regressions?)

### The godot-ai surface is ready

The MCP server already has mature, tested tools for particles, audio, animation, environments, input maps, autoloads, UI, and scene management. The gap is entirely in DevForge's planner→compiler chain. No changes needed to Odysseus or godot-ai.

---

## Appendix: godot-ai Tool → DevForge Op Gap Map

| godot-ai Domain | Tools Available | Used by DevForge? | Op Type Needed |
|-----------------|-----------------|-------------------|----------------|
| Node creation | `node_create`, `node_find`, `node_manage.*` | ✅ (add_node, rename_node, delete_node) | — |
| Properties | `node_set_property`, `node_get_properties` | ✅ (set_property) | — |
| Scripts | `script_create`, `script_attach`, `script_patch`, `script_manage` | ✅ (create_script, attach_script) | — |
| Signals | `signal_manage.connect`, `signal_manage.disconnect` | ✅ (connect_signal) | — |
| Particles | `particle_manage.*` (7 ops) | ❌ | `set_particles`, `configure_particles` |
| Audio | `audio_manage.*` (5 ops) | ❌ | `create_audio_player`, `play_audio` |
| Animation | `animation_manage.*` (12 ops) | ❌ | `create_animation`, `add_anim_track` |
| Environment | `resource_manage.environment_create` | ❌ | `set_environment` |
| Materials | `material_manage.*` (7 ops) | Partial (only albedo_color) | `set_material_params`, `apply_material_preset` |
| Resources | `resource_manage.noise_texture_create`, `resource_manage.gradient_texture_create` | ❌ | `create_noise_texture`, `create_gradient` |
| Input map | `input_map_manage.*` (5 ops) | ❌ | `add_input_action`, `bind_input_key` |
| Autoloads | `autoload_manage.add` | ❌ | `create_autoload` |
| Scene management | `scene_manage.create`, `scene_open`, `scene_save` | ❌ | `create_scene`, `open_scene` |
| UI | `ui_manage.*` (4 ops) | Partial (only Label text) | `build_ui_layout`, `set_anchor` |
| Camera | `camera_manage.*` (8 ops) | Partial (only position) | `configure_camera` |
| Filesystem | `filesystem_manage.*` | ❌ | `write_file`, `read_file` |
| Game runtime | `game_manage.*`, `editor_manage.game_eval` | ❌ | `game_eval` |

**11 tool domains with 50+ operations are ready but unreachable through the pipeline.**
