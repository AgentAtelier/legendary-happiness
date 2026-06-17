# Tool-Surface Inventory — godot-ai & DevForge MCP Tools

Generated 2026-06-15 from live registries. This is the map that Workstream A draws from:
what data can we get, from where, how fresh.

---

## godot-ai MCP Tools (port 8000, WS 9500 → Godot editor)

Source: `godot_ai/server.py` (`mcp.instructions`), per-domain `register_*_tools()` in
`src/godot_ai/tools/`.  Domain rollups (`<domain>_manage`) collapse multiple ops into
one tool; core named verbs are always loaded.

### Core named verbs (always loaded)

| Tool | Returns | Freshness | Notes |
|------|---------|-----------|-------|
| `editor_state` | `{version, readiness, current_scene, play_state, game_capture_ready}` | Live poll | Also reachable as `editor_manage(op="state")`. Refreshes session readiness cache (Issue #262). |
| `scene_get_hierarchy` | `{nodes: [{path, name, type, parent, children?}], has_more}` | Live snapshot | Paginated; pass `depth` to control tree depth. The primary scene read. |
| `node_get_properties` | `{data: {properties: [{name, value, type}]}}` | Live read | Full property snapshot for one node path. |
| `session_activate` | `{session_id, ...}` | — | Pin commands to one editor session. |
| `node_create` | — (side effect) | — | `parent_path`, `type`, `name` |
| `node_set_property` | — (side effect) | — | Single property write |
| `node_find` | `{matches: [{path, name, type}]}` | Live scan | Wildcard/regex search over scene tree |
| `scene_open` | — (side effect) | — | Open a scene file. No-op if already active → stale-tab bug. |
| `scene_save` | — (side effect) | — | |
| `script_create` | `{path, ...}` | — | Create a GDScript file |
| `script_attach` | — (side effect) | — | Attach a script to a node |
| `script_patch` | `{result, ...}` | — | Diff-style patch to a GDScript file |
| `project_run` | `{run_id, ...}` | — | Launch game; `mode="custom"` + `scene=` for disposable. |
| `test_run` | `{results, ...}` | — | Run GUT tests |
| `batch_execute` | `{results: [{command, status, error?}]}` | Atomic execution | Batch multiple commands with undo support. **Per-op errors available here.** |
| `logs_read` | `{lines: [{source, level, text, path?, line?, function?}], run_id, is_running, dropped_count, stale_run_id?}` | Buffer (500 plugin / 2000 game / 500 editor) | Sources: `plugin`, `game`, `editor`, `all`. Tail with `offset` + `since_run_id`. **Highest-priority unused data source — explains session deaths and bridge-side traces.** |
| `editor_screenshot` | ImageContent + `{aabb, ...}` | Live render | Source: `viewport`, `cinematic`, `game`. |
| `editor_reload_plugin` | `{status, ...}` | — | Reloads the editor plugin; may kill server if plugin-managed. |
| `animation_create` | — (side effect) | — | |

### Domain rollups (one tool per domain, pass `op=` + `params` dict)

| Domain | Tool | Ops | Key return fields |
|--------|------|-----|-------------------|
| Scene | `scene_manage` | `create`, `save_as`, `get_roots` | |
| Node | `node_manage` | `get_children`, `get_groups`, `delete`, `duplicate`, `rename`, `move`, `reparent`, `add_to_group`, `remove_from_group` | `{children: [{path, name, type}]}` for get_children |
| Script | `script_manage` | `read`, `detach`, `find_symbols` | `{content}` for read |
| Project | `project_manage` | `stop`, `settings_get`, `settings_set` | `{settings: {}}` |
| Editor | `editor_manage` | `state`, `selection_get`, `selection_set`, `monitors_get`, `quit`, `logs_clear`, `game_eval` | `monitors_get` → `{data: {"time/fps": N, ...}}`. `game_eval` → eval return + errors. |
| Session | `session_manage` | `list` | `{sessions: [{id, readiness, ...}]}` |
| Test | `test_manage` | `results_get` | |
| Animation | `animation_manage` | `player_create`, `delete`, `validate`, `add_property_track`, `add_method_track`, `set_autoplay`, `play`, `stop`, `list`, `get`, `create_simple`, `preset_fade/slide/shake/pulse` | |
| Material | `material_manage` | `create`, `set_param`, `set_shader_param`, `get`, `list`, `assign`, `apply_to_node`, `apply_preset` | |
| Audio | `audio_manage` | `player_create`, `player_set_stream`, `player_set_playback`, `play`, `stop`, `list` | |
| Particle | `particle_manage` | `create`, `set_main`, `set_process`, `set_draw_pass`, `restart`, `get`, `apply_preset` | |
| Camera | `camera_manage` | `create`, `configure`, `set_limits_2d`, `set_damping_2d`, `follow_2d`, `get`, `list`, `apply_preset` | |
| Signal | `signal_manage` | `list`, `connect`, `disconnect` | |
| Input Map | `input_map_manage` | `list`, `add_action`, `remove_action`, `bind_event` | |
| Game | `game_manage` | `get_scene_tree`, `get_node_info`, `get_ui_elements`, `input_key`, `input_mouse`, `input_gamepad`, `input_state` | Runtime data (only when playing) |
| Autoload | `autoload_manage` | `list`, `add`, `remove` | |
| Filesystem | `filesystem_manage` | `read_text`, `write_text`, `reimport`, `search` | Read/write project files |
| Theme | `theme_manage` | `create`, `set_color`, `set_constant`, `set_font_size`, `set_stylebox_flat`, `apply` | |
| UI | `ui_manage` | `set_anchor_preset`, `set_text`, `build_layout`, `draw_recipe` | |
| Resource | `resource_manage` | `search`, `load`, `assign`, `get_info`, `create`, `curve_set_points`, `environment_create`, `physics_shape_autofit`, `gradient_texture_create`, `noise_texture_create` | |
| Client | `client_manage` | `status`, `configure`, `remove` | |

### Resources (read-only URIs — no tool-count cost)

| URI | Maps to |
|-----|---------|
| `godot://sessions` | Session list |
| `godot://editor/state` | `editor_state` |
| `godot://selection/current` | Editor selection |
| `godot://logs/recent` | `logs_read` (prefer for active-session reads) |
| `godot://scene/current` | Current scene path |
| `godot://scene/hierarchy` | `scene_get_hierarchy` |
| `godot://node/{path}/properties` | `node_get_properties` |
| `godot://node/{path}/children` | `node_manage(get_children)` |
| `godot://node/{path}/groups` | `node_manage(get_groups)` |
| `godot://script/{path}` | `script_manage(read)` |
| `godot://project/info` | Project metadata |
| `godot://project/settings` | `project_manage(settings_get)` |
| `godot://materials` | Material list |
| `godot://input_map` | Input actions |
| `godot://performance` | `editor_manage(monitors_get)` |
| `godot://test/results` | Last test run results |

---

## DevForge MCP Tools (port 8001, SSE)

### Tools

| Tool | Returns | Freshness | Notes |
|------|---------|-----------|-------|
| `apply_spec` | `{artifact_id, applied, operations_total, errors: [], error_count}` | Per-run | The single primary tool. Plans + compiles + validates + executes. **Stage latencies and per-op errors are in the artifact.** |
| `read_artifact` | `{arch_delta, operations: [], files: [], errors: [], stage_latencies: {}, plan_retries, repair_count, completeness_added, token_used}` | From last `apply_spec` | **Full pipeline data: planner delta, compiled ops, execution errors, timing breakdown.** |
| `get_scene` | `{scene: {name, type, children: []}}` | Live snapshot | DevForge's view of the scene tree. |
| `validate_spec` | `{valid_count, error_count, errors: []}` | Deterministic | No-LLM validator: checks ops against a scene tree. |
| `audit_scene` | `{...}` | Live snapshot | Scene audit / completeness report. |

### `read_artifact` return shape (the full pipeline trace)

```
{
  arch_delta: {entities: [], systems: [], connections: {}, parents: {}, _rename?, _remove?},
  operations: [{type, name, node_type, parent, props?, ...}],
  files: [{path, content}],
  errors: ["error strings"],
  stage_latencies: {
    script_extraction,    // ms — deterministic, no LLM
    context_assembly,     // ms — deterministic
    architecture_planning,// ms — LLM call (the expensive one)
    compilation,          // ms — deterministic
    operation_generation, // ms — deterministic
    completeness,         // ms — deterministic
    validation,           // ms — deterministic
    repair,               // ms — deterministic (only if errors)
    governance            // ms — deterministic (optional)
  },
  plan_retries: 0,        // 0 = first attempt succeeded
  repair_count: 0,        // operations fixed by repair engine
  completeness_added: 0,  // nodes auto-injected
  token_used: 0,          // tokens consumed (0 if unavailable from LLM gateway)
  cache_stats: {},         // planner cache hit/miss
  scene_tree: {},
  scene_version: 0
}
```

---

## Data freshness taxonomy

| Freshness | Meaning | Examples |
|-----------|---------|----------|
| **Live poll** | Fetches from the running editor/game on each call | `editor_state`, `scene_get_hierarchy`, `logs_read` |
| **Live snapshot** | Snapshot taken at call time; may be cached briefly | `get_scene`, `audit_scene` |
| **Per-run** | Generated once per `apply_spec` call; persists in artifact | `read_artifact`, all `stage_latencies` |
| **Buffer** | Ring buffer, rotates under load | `logs_read` (500 plugin / 2000 game / 500 editor) |
| **Deterministic** | No LLM, no side effects, pure computation | `validate_spec`, all compilation stages |

---

## Key data gaps (Workstream A targets)

1. **`logs_read` — not wired.** The highest-priority unused source. Would surface session-death causes (B4) and bridge-side traces from failed builds (B1). Wire as `/api/logs-read` → Testing tab panel.
2. **Raw LLM output — not captured.** `read_artifact` has `token_used: 0` (LLM gateway doesn't expose it). The planner's raw JSON output, token-vs-JSON ratio, and thinking tokens are invisible. Needs A2 instrumentation.
3. **Per-op execution errors — captured but not surfaced.** `batch_execute` returns per-op `{command, status, error?}` but the Testing tab only shows the headline count. The per-op detail that diagnosed Bug 1/2/3 lives in the artifact but isn't shown.
4. **`stage_latencies` — captured but not shown.** The full timing breakdown is in `read_artifact` but the UI never displays it.
5. **Runtime/play-mode data — not wired.** `game_manage` (FPS, scene tree at runtime), `project_run` outputs, script parse errors at play time — all reachable but not hooked up. A3 target.
6. **`editor_screenshot` — not wired.** Low-cost visual ground truth. A6 target.
