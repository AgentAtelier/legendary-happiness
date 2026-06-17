---
reviewer: mimo
date: 2026-06-17
prompts_answered: [1, 2, 3]
---

# Layer-3 Code-Health Review — Mimo

> Reference real code as `path/to/file.py:line`. Be concrete and specific to THIS
> repository, not generic best-practice. Put the substance here, not in chat.

## Prompt 1 — One architecture + god-file splits

### Recommended architecture

The Forge stack is **three layers with MCP bridges**: **(1) Hub** (FastAPI web UI `hub/`) orchestrates everything — model swapping, test runs, chain health — by shelling out to system services and a `stack` CLI. **(2) Engine** (`engine/devforge/`) is the generation pipeline that turns natural-language prompts into Godot scene operations via LLM planning → compilation → execution. **(3) Bridges** — the hub talks to the engine over an MCP/SSE boundary (`hub.py` calls `_devforge_call()` to `mcp_server.py`); the engine talks to the Godot editor over another MCP boundary (`godot_ai_mcp.py`). **A test system** (`forge_testbench/`) runs probes, scenarios, gauntlets, and diagnostics, with a migration in progress from legacy runners (`bench.py`, `scenarios.py`, `gauntlet.py`) to the unified testbench chassis.

A non-programmer can hold this in their head: **"Hub is the control panel. Engine is the builder. They talk over MCP bridges like phone lines. Tests measure both."**

### Where the code follows it vs. muddies it

**Follows it well:**
- `hub/forge_ops.py` — clearly separated transactional operations (swap, reconcile, drift detection, action logging). Good model of the pattern other modules should follow.
- `hub/forge_models.py` — GGUF parsing, VRAM estimation, model registry — single source of truth for model intelligence, shared by hub and CLI. Exactly the right split.
- `hub/forge_env.py` — `stack.env` parser/writer/validator. Clean, focused, one responsibility.
- `engine/devforge/compilation/pipeline/` — the pipeline is decomposed into distinct stages (assembler, planner, compiler, generator, validator, repair) each in its own file. Good layering.
- `engine/devforge/execution/interface.py` — Executor abstract base defines the contract. `godot_ai_mcp.py` and `devforge_plugin.py` implement it. Clean pattern.
- `engine/devforge/spatial/` — Each spatial algorithm (layout, building, scatter, SSP, WFC, Voronoi) gets its own planner + engine file. Consistent, navigable.
- The MCP boundary is real: hub never imports engine, engine never imports hub. They communicate over HTTP. This is an excellent structural guarantee.

**Muddies it:**
- `hub/hub.py` (~1940 lines) mixes HTTP routing, job management, SSE streaming, chain health, persona restoration, embeddings, stability scoring, think-config toggle, mode switching — all in one file. Even though many routes delegate to downstream modules (`bench`, `scenarios`, `shootout`, `gauntlet`), the route definitions, job orchestration, and helpers are all crammed together. `hub.py:50-65` imports `bench`, `scenarios`, `shootout` at module level — these are route-handler modules being imported as if they're libraries, when they're actually extensions of the hub's API surface.
- `engine/devforge/platform/mcp_server.py` (~2150 lines) puts 30+ MCP tool definitions alongside server initialization, lazy-init, pipeline lock management, and shared state in one file. The tools are all `@mcp.tool()` decorators on functions in the same module — structurally, this is one enormous namespace.
- `engine/devforge/compilation/pipeline/engine.py` (~1440 lines) has `run_pipeline()` that routes to 8 different planner paths (arch, ops, layout, building, scatter, SSP, WFC, Voronoi, Room) with long if/elif chains. The `_run_spatial_path()` factory reduced duplication but the file still holds all paths plus governance gates, deterministic passes, and 7 regex constants at module level.
- `engine/devforge/execution/godot_ai_mcp.py` (~1080 lines) combines persistent MCP session management (circuit breaker, reconnect, background event loop), operation translation (DevForge ops → godot-ai commands), batch execution with retry/fallback, scene tree rebuilding, property resolution, and smoke-run primitives all in one class.
- Test system straddles two paradigms: legacy runners (`bench.py`, `scenarios.py`, `shootout.py`, `gauntlet.py`, `diagnostics.py`, `harness.py`, `multi_model_bench.py`, `comprehensive_bench.py`) sit at `hub/` root alongside the new `forge_testbench/` package. The hub routes in `hub.py` directly call these legacy modules' functions.

### God-file split plan

All splits should use `str_replace` edits (not `write_file`) to preserve git blame. Each split is one commit.

#### 1. `engine/devforge/platform/mcp_server.py` (≈2150 lines)

**Current state:** One file with `mcp = FastMCP(...)`, `_init()` lazy initializer, `_pipeline_lock` management, and ~30 `@mcp.tool()` decorated functions.

**Target modules (5 files in `engine/devforge/platform/`):**

| New file | Single responsibility | ~lines |
|----------|----------------------|--------|
| `mcp_server.py` | FastMCP creation, `_init()`, shared state (`_engine`, `_executor`, `_scene_store`, `_artifact_store`, `_journal`, `_sentinel`), pipeline lock management, `if __name__ == "__main__"` | ~250 |
| `mcp_tools_scene.py` | `apply_spec`, `validate_spec`, `get_scene`, `audit_scene`, `batch_preview`, `batch_apply`, `read_artifact` — core scene pipeline tools | ~700 |
| `mcp_tools_content.py` | `lint_content`, `lore_schema_list`, `lore_data_validate`, `lore_integrity_check`, `quest_validate`, `dialogue_validate`, `template_list`, `template_preview`, `template_apply` — content/lore/template tools | ~500 |
| `mcp_tools_analysis.py` | `triage_errors`, `perf_sample`, `perf_history`, `balance_sim`, `signal_map`, `project_search`, `design_companion`, `polish_pass`, `scene_extract`, `scene_list_extractable` — analysis and diagnostic tools | ~450 |
| `mcp_tools_dev.py` | `journal_entries`, `journal_summary`, `test_scaffold`, `smoke_run` — development-support tools | ~250 |

**Safe order (lowest risk first):**
1. **`mcp_tools_dev.py`** — These tools have zero dependency on scene state beyond `_init()` and `_journal`. They're self-contained. Extract them first to prove the pattern works.
2. **`mcp_tools_content.py`** — Content tools depend on `_init()`, `_scene_store` (lore loads from disk, not scene), and `_executor` (for file creation in template_apply). All dependencies are through the shared state already in `mcp_server.py`.
3. **`mcp_tools_analysis.py`** — These tools use `_executor` for godot-ai calls and `_scene_store` for scene reads. Same dependency pattern as content tools.
4. **`mcp_tools_scene.py`** — Extracted last because `apply_spec` is the most critical path and depends on `_pipeline_lock`, `_engine`, `_executor`, `_scene_store`, `_artifact_store`, `_journal`, and `_llm` — all the shared state. Extracting it last means the import pattern is battle-tested.

**How the imports work:** Each new module imports from `mcp_server`:
```python
from devforge.platform.mcp_server import mcp, _init, _engine, _executor, _scene_store, _artifact_store, _journal, _sentinel, _llm, _acquire_pipeline_lock_ctx
```
The `@mcp.tool()` decorators stay in their respective files and register with the same `mcp` instance. This is a standard FastMCP pattern.

#### 2. `hub/hub.py` (≈1940 lines)

**Current state:** FastAPI app creation, middleware, job runner, SSE streaming, and ~40 route handlers covering status, config, models, swap, chain health, bench, probes, scenarios, gauntlet, shootout, runs, stability, thinking toggle, mode switch, persona, embeddings — all in one file.

**Target modules (6 files in `hub/`):**

| New file | Single responsibility | ~lines |
|----------|----------------------|--------|
| `hub.py` | App creation (`app = FastAPI(...)`), `origin_guard` middleware, `_run_capture`, `_job_runner`, `HOME`/`STACK`/`STATIC_DIR` constants, `if __name__ == "__main__"`, imports of route modules | ~350 |
| `hub_routes_config.py` | `/`, `/api/status`, `/api/config` (get/save/restore/backups), `/api/doc`, `/api/version`, `/api/selfcheck` — read-only and config routes | ~250 |
| `hub_routes_ops.py` | `/api/run`, `/api/swap`, `/api/reconcile`, `/api/models`, `/api/models/search`, `/api/logs/{svc}`, `/api/job/active`, `/api/stream/{job_id}` — mutating operations and job management | ~350 |
| `hub_routes_chain.py` | `/api/chain-health`, `/api/logs-read`, `/api/screenshot`, `/api/mode`, `/api/thinking/*`, `/api/odysseus/*`, `/api/persona/*` — chain diagnostics and Odyssesus integration | ~350 |
| `hub_routes_testing.py` | `/api/bench/*`, `/api/scenarios/*`, `/api/scorecards/*`, `/api/shootout/*`, `/api/gauntlet/*`, `/api/tools/*` — test orchestration routes (delegates to `bench.py`, `scenarios.py`, `shootout.py`, `gauntlet.py`) | ~300 |
| `hub_routes_analysis.py` | `/api/actions`, `/api/scorecards/compare`, `/api/runs`, `/api/runs/compare`, `/api/runs/stability` — cross-cutting analysis routes | ~200 |

Plus, migrate the job-running infrastructure into a shared helper:

| `hub_jobs.py` | `_job_lock`, `_jobs` dict, `_job_runner` coroutine, `_run_capture` — job lifecycle management, shared by all route modules | ~150 |

**Safe order (lowest risk first):**
1. **`hub_jobs.py`** — Extract the job lock, `_jobs` dict, `_job_runner`, and `_run_capture` into a shared module. All routes use these. This is the prerequisite.
2. **`hub_routes_config.py`** — Read-only routes with zero side effects. Safest to extract first.
3. **`hub_routes_analysis.py`** — Read-only analysis routes. No mutations.
4. **`hub_routes_chain.py`** — Chain health and Odyssesus integration. Some POST routes but they use the job infrastructure.
5. **`hub_routes_testing.py`** — Test orchestration. Depends on downstream modules (`bench`, `scenarios`, `shootout`, `gauntlet`) which are already imported at module level in `hub.py:50-65`.
6. **`hub_routes_ops.py`** — Extracted last because swap and reconcile are the most critical paths. They use `forge_ops.swap_model` and `forge_ops.reconcile_model`.

**How the imports work:** Each route module imports the `app` object and shared state from `hub`:
```python
from hub import app, _job_lock, _jobs, _run_capture, STACK, ENVFILE, ACTIONS, _RECONNECT_ACTIONS, ...
```
FastAPI's `APIRouter` is an alternative, but given this codebase already uses `@app.get(...)` decorators on a module-level `app`, the simplest transition is to keep `app` as a shared module-level object that route modules import and decorate. This is a well-known FastAPI pattern ("big app, multiple files").

#### 3. `engine/devforge/compilation/pipeline/engine.py` (≈1440 lines)

**Current state:** `PipelineEngine` class with `run_pipeline()`, 9 planner-path methods, governance gates, validation-only method, helpers, and 7 module-level regex constants for deterministic pre-passes.

**Target modules (6 files in `engine/devforge/compilation/pipeline/`):**

| New file | Single responsibility | ~lines |
|----------|----------------------|--------|
| `engine.py` | `PipelineEngine` class: `__init__`, `run_pipeline()` main orchestrator, `update_history()`, `validate_pipeline()`, helpers (`_normalize_scene`, `_dedupe_files`, `_dedupe_operations`), dataclasses (`PipelineResult`, `GateResult`) | ~350 |
| `arch_planner_path.py` | `_run_arch_path()` — the default architecture planner path including deterministic dedup, delete/rename intent injection, entity recovery, system inference, and compilation | ~350 |
| `spatial_paths.py` | `_run_spatial_path()` factory + all 7 spatial paths: `_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_wfc_path`, `_run_voronoi_path`, `_run_room_path` | ~250 |
| `ops_planner_path.py` | `_run_ops_path()` — the ops planner path (shelved but kept behind flag) | ~120 |
| `deterministic_passes.py` | Module-level: `_recover_entities_from_prompt()`, `_clean_rename_target()`, `_DELETE_INTENT_RE`, `_RENAME_TO_RE`, `_ENTITY_FROM_PROMPT_RE`, script extraction imports. Also `_run_governance_gates()` | ~200 |
| `spatial_imports.py` | The lazy spatial import block (lines ~60-100 of current `engine.py`) — `try: from devforge.spatial...` with all 10 spatial imports. Referenced by both `engine.py` and `spatial_paths.py` | ~80 |

**Safe order (lowest risk first):**
1. **`spatial_imports.py`** — Pure imports, no logic. Zero risk. Both `engine.py.__init__` and `spatial_paths.py` will import from here.
2. **`ops_planner_path.py`** — Self-contained path that's already shelved. Lowest risk of the logic extractions.
3. **`deterministic_passes.py`** — Module-level functions and regex constants. No class state dependencies.
4. **`spatial_paths.py`** — Extracts the factory and 7 paths. Depends on `spatial_imports.py` and the `_run_spatial_path` factory pattern.
5. **`arch_planner_path.py`** — Extracted last because it's the default path and the most complex (retries, budget errors, deterministic passes, entity recovery, system inference). Depends on `deterministic_passes.py`.

#### 4. `engine/devforge/execution/godot_ai_mcp.py` (≈1080 lines)

**Current state:** `GodotAIMCPExecutor` class with session management (background event loop, circuit breaker, reconnect), operation execution (batch + individual fallback), scene hierarchy rebuilding, operation translation (`_OP_TO_COMMAND`, `_FIELD_MAP`), property resolution, smoke-run primitives (run_project, stop_project, game_eval, take_screenshot), and result parsing.

**Target modules (4 files in `engine/devforge/execution/`):**

| New file | Single responsibility | ~lines |
|----------|----------------------|--------|
| `godot_ai_mcp.py` | `GodotAIMCPExecutor` class: `__init__`, `execute()`, `get_scene()`, `read_logs()`, `backend_name`, `shutdown()`. The public Executor interface plus initialization. | ~200 |
| `mcp_session.py` | `_ensure_session()`, `_close_session()`, `_run()` (background loop dispatch), `_call_tool_safe()`, `_record_mcp_failure()`, `_loop`/`_thread` management. All session lifecycle and circuit breaker logic. | ~250 |
| `mcp_operations.py` | `_execute_async()`, `_execute_ops_individually()`, `_translate_ops_to_commands()`, `_res_path()`, `_OP_TO_COMMAND`, `_FIELD_MAP`, `_DROP_FIELDS`. Operation execution pipeline. | ~250 |
| `mcp_tools.py` | `resolve_node_properties()`, `get_performance_monitors()`, `find_symbols()`, `search_filesystem()`, `run_project()`, `stop_project()`, `game_eval()`, `take_screenshot()`, `resolve_property_types()` — and all their async internals. Extended tool surface. | ~380 |

**Safe order (lowest risk first):**
1. **`mcp_session.py`** — Session management is self-contained. Extract it first since all other methods depend on `_ensure_session()`.
2. **`mcp_tools.py`** — Extended tools are independent of the operation pipeline. They use `_ensure_session()` and `_call_tool_safe()` from `mcp_session.py`.
3. **`mcp_operations.py`** — Operation execution depends on session management and translation. Extract after session is stable.
4. **`godot_ai_mcp.py`** (trimmed) — The core class stays behind, delegating to the extracted modules.

### What you're not asking that you should be

1. **"What's the test suite situation for these god files?"** — `mcp_server.py` has no direct unit tests (the test files in `engine/devforge/tests/` test individual pipeline components, not the MCP server integration). `hub.py` has test coverage via `hub/tests/` but those test the downstream modules (`forge_ops`, `forge_models`), not the route handlers directly. Splitting god files without adding tests for the new module boundaries is risky — you'd want at least import tests and smoke tests for each new module.

2. **"Should the legacy test runners be deleted BEFORE or AFTER the god-file splits?"** — The answer is: delete them BEFORE. The legacy runners (`bench.py`, `scenarios.py`, `shootout.py`, `gauntlet.py`, `diagnostics.py`, `harness.py`, `multi_model_bench.py`, `comprehensive_bench.py`) are imported by `hub.py` at module level (lines 50-65). If you split `hub.py` first, you'll be splitting code that references modules you plan to delete. Delete the legacy runners (after forge_testbench parity-gates pass) first, then split `hub.py`. This reduces the surface area you're splitting.

3. **"Are there circular dependency landmines?"** — Yes. `hub/hub.py` imports `bench`, `scenarios`, `shootout` at module level, and those modules import from `hub/forge_env.py`, `hub/forge_models.py`, `hub/forge_ops.py`. The `from hub import app` pattern for route modules will work because FastAPI's `app` object is created before routes are imported. But watch out: `bench.py`, `scenarios.py`, etc. also call `read_env(ENVFILE)` at module level, not lazily. If a split module imports `app` from `hub.py` and `hub.py` imports `bench.py`, and `bench.py` needs something from a route module... you have a cycle. The fix: make `bench`/`scenarios`/`shootout` imports in `hub.py` happen lazily (inside route handlers) or use `APIRouter` with dependency injection.

---

## Prompt 2 — Short conventions guide

### File & function length

**Recommended maximums:**
- **Files: 500 lines.** Beyond this, a file likely has multiple responsibilities. The project's current median file is ~150 lines; the 500-line cap targets the tail.
- **Functions: 80 lines.** A function longer than this is doing too many things or has deeply nested control flow. Extract helpers.

**Real offenders (excluding legacy test runners):**

| File | Lines | What's wrong |
|------|-------|-------------|
| `engine/devforge/platform/mcp_server.py` | ~2150 | 30 tool functions + init + lock management |
| `hub/hub.py` | ~1940 | 40 route handlers + job runner + middleware + chain health |
| `engine/devforge/compilation/pipeline/engine.py` | ~1440 | 9 planner paths + governance + deterministic passes |
| `engine/devforge/execution/godot_ai_mcp.py` | ~1080 | Session + execution + tools + scene rebuilding |
| `hub/forge_ops.py` | ~400 | Close to the cap but focused — acceptable |
| `hub/forge_models.py` | ~350 | Under cap and well-scoped |

| Function | File | Lines | What's wrong |
|----------|------|-------|-------------|
| `run_pipeline()` | `engine.py:~260-420` | ~160 | Routes to 9 planner paths, runs 5 post-planning phases |
| `chain_health()` | `hub.py:~930-1150` | ~220 | 10 link checks with nested async helpers |
| `_execute_async()` | `godot_ai_mcp.py:~510-630` | ~120 | File creation + batch ops + retry + fallback + logs + scene + error parsing |
| `_init()` | `mcp_server.py:~130-235` | ~105 | LLM config + executor + scene store + artifact store + journal + sentinel + plan cache + engine creation |
| `run_pipeline()` in `engine.py` | | | 160 lines |

**One-line rationale:** Files over 500 lines and functions over 80 lines resist skimming — a non-coder reviewer can't hold the shape in their head.

### Duplication → functions

**Most valuable repeated logic to collapse:**

1. **MCP call + JSON parse pattern** — `hub/hub.py`, `hub/forge_testbench/runner.py`, `hub/diagnostics.py`, `hub/bench.py`, `hub/scenarios.py`, and `hub/shootout.py` all contain their own copies of `_devforge_call()`, `_godot_ai_call()`, and the MCP client session boilerplate (`streamable_http_client` / `sse_client` + `ClientSession` + `initialize()` + `call_tool()` + `json.loads(content[0].text)`). This pattern appears at least **8 times** across the codebase. Collapse into a shared `hub/mcp_client.py` with `devforge_call(tool, args)` and `godot_ai_call(tool, args)`. Real examples:
   - `hub/bench.py:~35-50` — `_devforge_call` and `_godot_ai_call`
   - `hub/forge_testbench/runner.py:~65-95` — `_devforge_call`, `_godot_ai_call`, `_devforge_raw_call`, `_read_artifact`
   - `hub/diagnostics.py:~40-55` — `_apply_with_full_ops` (wraps `_devforge_call` + `read_artifact`)
   - `hub/scenarios.py` — has its own MCP call helpers
   - `hub/shootout.py` — has its own MCP call helpers

2. **Scene reset logic** — `hub/bench.py` and `hub/forge_testbench/runner.py` each implement `_scene_reset()` independently. Both use the "bounce trick" (open a different scene to force a real disk reload). They are ~80% identical. Real examples:
   - `hub/bench.py:~60-110` — `_probe_scene_reset()`
   - `hub/forge_testbench/runner.py:~130-210` — `_scene_reset()`
   - `hub/diagnostics.py:~30` — imports `_probe_scene_reset` from `bench`

3. **Config hash computation** — `hub/hub.py:~59-67` computes `BUILD_ID` by hashing source files. The same pattern (with different file lists) appears for stale-service detection in chain health. Collapse into `forge_env.config_hash(files)`.

4. **SSE streaming job pattern** — Every POST route in `hub.py` that creates a long-running job (~15 routes) follows the same pattern: acquire lock → create job dict → spawn `_runner()` coroutine → return `{"job": job_id}`. The `async def _runner()` inner functions are ~10-20 lines each and differ only in the work function they call. Extract `async def run_as_job(emit, work_fn, label)` into `hub_jobs.py`.

**One-line rationale:** Eight copies of the same MCP call pattern means eight places where a protocol change must be updated — and eight places where it will be missed.

### Naming convention

**Recommended convention:**
- **Files:** `snake_case.py` for Python modules. Prefix with domain: `mcp_*.py` for MCP tool files, `hub_routes_*.py` for route modules. Suffix with role: `*_planner.py`, `*_compiler.py`, `*_executor.py` for pipeline stages.
- **Functions:** `snake_case`. Public API: descriptive verb phrases (`swap_model`, `plan_apply`, `run_pipeline`). Private helpers: `_` prefix (`_init`, `_ensure_session`, `_normalize_scene`).
- **Classes:** `PascalCase`. Pipeline stages: `*Planner`, `*Compiler`, `*Generator`, `*Validator`, `*Executor` — already well-established in the codebase.
- **"Don't make me guess" rule:** A file named `X.py` should have its primary class/function named `X` or be obvious from context. `engine/devforge/simulator/simulator.py` exports `evaluate_encounter` — the file name doesn't hint at the function name.

**Fossil and misleading names to fix:**

| Current name | Location | Problem | Suggestion |
|-------------|----------|---------|------------|
| `bench.py` | `hub/bench.py` | Name says "benchmark" but it's actually a chain-probe test runner (21 probes of llama→devforge→godot-ai→runtime layers). The real benchmark is the testbench. | Keep name during migration, delete afterward (it's legacy). |
| `scenarios.py` | `hub/scenarios.py` | Name says "scenarios" but it contains `SCENARIOS` (build tests) AND `TOOL_CALL_PROBES` (model-only tool capability tests). Two unrelated test suites in one module. | Delete after migration to forge_testbench. |
| `forge_ops.py` | `hub/forge_ops.py` | "ops" is ambiguous — is it DevOps operations? Forge operations? It contains model swap, drift detection, reconcile, action logging, and failure classification. | Acceptable for now — the module's docstring is clear. Consider renaming to `forge_transactions.py` to emphasize the transactional model swap. |
| `engine.py` | `engine/devforge/compilation/pipeline/engine.py` | Ambiguous in context — there's also `godot_ai_mcp.py` (execution engine), `template_engine.py`, and the whole `engine/` directory. | Rename to `pipeline_engine.py` when splitting. The class is already `PipelineEngine` — the file should match. |
| `interface.py` | `engine/devforge/execution/interface.py` | Contains `Executor` ABC and `ExecutionResult` dataclass. These aren't "an interface" — they're the execution contract. | Rename to `executor.py` or keep as-is since "interface" is an established Python pattern for ABCs. |
| `_run_*_path()` methods | `engine.py` | All 8 planner-path methods are named `_run_<name>_path()` — good convention, but they're all in one file. | After split, each file gets one path. The `_run_` prefix is fine as a private-method convention. |
| `_init()` | `mcp_server.py:~130` | Double-underscore private by convention, but it's a module-level function imported by other modules. Single-underscore `_init` is correct (it IS module-private). However, being imported by other modules makes it effectively public. | After split, rename to `init_mcp_server()` or keep as `_init` with a clear docstring. |

**One-line rationale:** A non-coder reviewing a diff should be able to tell what a file does from its name without opening it.

### The minimal "loose rules" worth standardizing

| # | Rule | Rationale |
|---|------|-----------|
| 1 | **500-line file cap, 80-line function cap** (soft, not enforced by CI) | A non-coder reviewer can skim a 500-line file; they drown in a 2000-line file. |
| 2 | **One class/concern per file** — if a file has two classes that could live separately, split them | `godot_ai_mcp.py` has session management AND operation translation AND tool surface. Split by concern. |
| 3 | **`_` prefix for module-private, `__` for class-private** — already well-followed | Consistency reduces "is this meant to be called from outside?" guesswork. |
| 4 | **Every module gets a one-sentence docstring** saying what it IS (not what it contains) | `mcp_server.py`'s docstring says "exposes the pipeline as MCP tools" — perfect. `forge_ops.py` says "transactional operations for the forge stack" — perfect. About 40% of `engine/devforge/` modules lack docstrings. |
| 5 | **Shared MCP call helpers live in one place** — no copy-pasting `ClientSession(...)` + `initialize()` + `call_tool()` + `json.loads(...)` | Eight copies today. |
| 6 | **Imports at top of file, no mid-file imports** — `hub.py` already follows this (the `noqa: E402` comments document the deliberate deviation where downstream modules must import after `app`). Engine files sometimes violate this (e.g., spatial imports inside `try:` in `engine.py:~60`). | Mid-file imports hide dependency surprises. The spatial `try/except ImportError` block is justified (optional dependency) but should be in its own module. |

**One-line rationale for the set:** These six rules require zero tooling and zero ongoing maintenance — they're habits an AI can follow when prompted.

### What you're not asking that you should be

1. **"Should there be a type annotation convention?"** — The codebase uses `from __future__ import annotations` consistently and has good type hints on public APIs. But internal helpers (especially in `mcp_server.py`'s tool functions) often use `Dict[str, Any]` as a catch-all. For a non-coder reviewer, typed dicts or dataclasses with docstrings are vastly more readable than generic dicts. Consider: `@dataclass class ApplySpecResult: artifact_id: str; applied: int; ...` with a `to_dict()` method that `apply_spec` returns. The tool functions already document their return shapes in docstrings — make those shapes real types.

2. **"Should there be a docstring convention for MCP tools?"** — `mcp_server.py`'s tools have excellent docstrings that serve as the AI agent's only documentation for how to call them. But the quality is inconsistent: `apply_spec` has a 40-line docstring with examples; `template_preview` has 15 lines; `journal_summary` has 10. A minimum: every `@mcp.tool()` docstring must include **(a)** what the tool does in one sentence, **(b)** the arguments dict as literal JSON, **(c)** the return dict shape. This is already done for most tools — make it universal.

3. **"Should error messages follow a convention?"** — Throughout the codebase, errors are returned as `{"error": "message"}` dicts rather than raised as exceptions. This is correct for MCP tools (the AI agent sees the error inline). But the format varies: sometimes `{"error": "msg"}`, sometimes `{"error": "msg", "hint": "..."}`, sometimes raw strings. Standardize: all tool errors return `{"error": str, "hint": str | None}`.

---

## Prompt 3 — Review & navigation environment

### Structural signals that make a file's purpose obvious

**What's already working well:**

1. **Module docstrings as purpose statements.** The best examples:
   - `hub/hub.py:1-15` — "forge-hub — local ops panel for the AI ⇄ Godot chain." Then design rules. A non-coder knows what this file IS.
   - `hub/forge_ops.py:1-15` — "forge_ops — transactional operations for the forge stack." Then public API listing. You know what you'll find.
   - `engine/devforge/compilation/pipeline/engine.py:1-13` — "Pipeline Engine — shared pipeline orchestration." Clear, with usage example.
   - `engine/devforge/execution/godot_ai_mcp.py:1-16` — "GodotAIMCPExecutor — MCP client backend for godot-ai." Explains the persistent session design.

2. **Consistent entry points.** The pipeline follows a clear stage pattern: `*Planner` → `*Compiler` → `*Generator` → `*Validator` → `*Repair`. Each stage is one file with one primary class. A non-coder can trace the pipeline: "the planner plans, the compiler compiles, the validator validates."

3. **Directory-as-namespace.** `engine/devforge/spatial/` contains everything spatial. `engine/devforge/compilation/pipeline/` contains everything pipeline. The directory names are self-documenting.

**What needs improvement:**

1. **Top-level architecture map is missing.** There's no single file a non-coder can open that says "Here's what every directory does." The closest is `docs/current/FORGE-STACK.md`, but it describes the *runtime* stack (ports, services, model management), not the *code* architecture. Create `docs/current/ARCHITECTURE.md` with:
   ```
   hub/          → Web UI and ops panel (FastAPI)
     forge_*.py  → Shared libraries for model management
     forge_testbench/ → New unified test system
   engine/devforge/ → Generation pipeline
     platform/   → MCP server (entry point for AI agents)
     compilation/pipeline/ → Plan → compile → validate → repair
     execution/  → Applies operations to Godot
     spatial/    → Room/building/terrain generation
     knowledge/  → Scene graphs, patterns, artifacts
     reasoning/  → LLM planning, repair, design
     ...
   ```

2. **~40% of `engine/devforge/` modules lack module docstrings.** Run: `find engine/devforge -name '*.py' -exec grep -L '^""".*"""' {} \;` to find them. Every `__init__.py` should state what its package contains. Every `.py` file should have a one-line purpose statement.

3. **Predictable file placement is violated in one place:** Test infrastructure. Legacy test runners live at `hub/*.py` (root level) while the new testbench lives at `hub/forge_testbench/`. A newcomer sees `bench.py`, `scenarios.py`, `shootout.py`, `gauntlet.py`, `diagnostics.py`, `harness.py`, `multi_model_bench.py`, `comprehensive_bench.py` — all test runners — mixed with `forge_ops.py`, `forge_models.py` — shared libraries. The signal is: "some of these are tests, some are libraries, good luck." The migration to `forge_testbench/` will fix this.

### What makes a diff reviewable by a non-coder

A non-coder reviewing an AI's git diff needs three things:

1. **Small commits with single intent.** The god-file splits above are designed for this: each split is one commit that moves code without changing behavior. The owner can review "extract `mcp_tools_dev.py` from `mcp_server.py`" by checking: (a) line count of the new file, (b) no new imports, (c) tests still pass. No need to read the moved code.

2. **Commit messages that say WHAT and WHY, not HOW.** Current commit messages in this project (empty — the repo has no commits tracked in this session) should follow:
   ```
   split: extract mcp_tools_dev from mcp_server.py

   Moves journal_entries, journal_summary, test_scaffold, smoke_run
   into a new file. No behavior changes. 250 lines moved.

   Why: mcp_server.py was 2150 lines — too large to skim.
   The dev-support tools are self-contained and safest to extract first.
   ```

3. **A "what to check" checklist in the PR/commit.** Every AI-written change should come with a 3-line checklist:
   ```
   Review:
   - [ ] Are the imports correct? (check new file's import block)
   - [ ] Is anything deleted that shouldn't be? (diff --stat shows only moves)
   - [ ] Do tests pass? (run: cd hub && .venv/bin/python -m pytest tests/ -v)
   ```

4. **`CHANGES.md` or similar keeps the owner oriented.** The project already has `engine/CHANGES.md` and `hub/docs/SESSION-CHANGES-*.md` files. These are good but scattered. Consolidate into one `CHANGES.md` at the repo root with the most recent 5-10 changes, each with: date, what changed, why, what to verify.

### Automated guardrails (most relief per unit of setup)

For a non-coder directing AI, the goal is **zero-config, zero-ongoing-burden automation**:

1. **`ruff` (Python linter + formatter) — highest relief, lowest burden.**
   - Install: `pip install ruff` (one command)
   - Config: one `pyproject.toml` section or `ruff.toml`:
     ```toml
     [tool.ruff]
     line-length = 100
     [tool.ruff.lint]
     select = ["E", "F", "I", "N", "W"]  # pyflakes + isort + naming + warnings
     [tool.ruff.format]
     quote-style = "double"
     ```
   - CI: `ruff check . && ruff format --check .` in `.github/workflows/`
   - What it buys: catches unused imports, undefined names, syntax errors, import ordering — the things AIs most commonly get wrong. Zero ongoing maintenance. The owner never has to say "you forgot to remove that import" again.
   - **Do NOT** add a strict line-length rule or naming convention rule — those generate noise for a non-coder. Keep it to "does this code actually work?" level checks.

2. **`pyright` or `mypy` (type checker) — medium relief, medium burden.**
   - The codebase already uses type hints extensively. A type checker catches: wrong argument types, missing return values, attribute errors — before runtime.
   - Config: one `pyproject.toml` section. Start with `typeCheckingMode = "basic"` (not strict) to avoid drowning in false positives.
   - **Decision gate:** Before adopting, run `pyright .` once and count the errors. If >100, fix them in one dedicated pass first. A non-coder won't know which type errors are real vs. noise.

3. **Pre-commit hook for the two rules above — zero ongoing burden.**
   - `.pre-commit-config.yaml`:
     ```yaml
     repos:
       - repo: https://github.com/astral-sh/ruff-pre-commit
         rev: v0.4.0
         hooks:
           - id: ruff
           - id: ruff-format
     ```
   - One `pre-commit install` and it runs on every commit. The AI can't forget.
   - **Important:** Do NOT add pytest as a pre-commit hook — tests that talk to llama.cpp will hang or fail on a cold machine. Only add fast, deterministic checks.

4. **`.github/workflows/ci.yml` — already exists (`claude.yml`, `claude-code-review.yml`).**
   - Add `ruff check .` as the first step. Fastest feedback, zero false positives on syntax errors.
   - Add `python -m pytest hub/tests/ -v` for unit tests (fast, safe).
   - Do NOT add integration tests to CI — they need a running llama.cpp server.

5. **Module docstring check — one shell command, zero tooling.**
   - Add to CI or pre-commit: `find engine/devforge hub -name '*.py' ! -name '__init__.py' -exec sh -c 'head -1 "$1" | grep -q "^\"\"\"" || echo "MISSING DOCSTRING: $1"' _ {} \;`
   - This catches the ~40% of modules without docstrings without requiring a new tool.
   - Make it a warning, not an error — docstrings are aspirational quality-of-life, not correctness.

**What to NOT add:**
- ❌ `pylint` — too many rules, too much noise. A non-coder will ignore it.
- ❌ `black` (formatter) — `ruff format` does the same thing with one tool instead of two.
- ❌ Coverage thresholds — they'll fail when the AI writes new code without tests, frustrating everyone.
- ❌ Spell-check on comments — noise for a solo project.
- ❌ Commit message linting — the owner is a non-coder; they shouldn't have to learn conventional commits.

### What you're not asking that you should be

1. **"What's the single most impactful thing to do first?"** — Delete the legacy test runners. They're 8 files (`bench.py`, `scenarios.py`, `shootout.py`, `gauntlet.py`, `diagnostics.py`, `harness.py`, `multi_model_bench.py`, `comprehensive_bench.py`) that are imported by `hub.py`, duplicated in `forge_testbench/`, and scheduled for deletion. Every day they exist, they add ~3000 lines of code that every reviewer (human or AI) has to mentally filter out as "ignore this, it's legacy." Deleting them (after parity-gates pass per `TESTBENCH-MIGRATION-HANDOFF.md`) reduces the codebase's surface area by ~30% in one step. Do this BEFORE the god-file splits.

2. **"Should there be an AI prompt template for code changes?"** — The `LAYER3-CODE-SURVEY-PROMPTS.md` file this review responds to is itself a prompt template. The project should have a similar template for code changes: "Here's what to change, here's the convention, here's what not to touch, here's how to verify." Include the line-length cap and naming convention from Prompt 2. This way, the owner can paste the same prompt to any AI assistant and get consistent results.

3. **"How should the owner verify an AI's changes?"** — The current process relies on the owner running tests (`run_all_tests.sh`). But the owner is a non-coder. The verification story should be:
   - **Step 1:** Did `ruff check .` pass? (automated — CI or pre-commit)
   - **Step 2:** Did tests pass? (`hub/tests/` — fast unit tests)
   - **Step 3:** Did the hub still start? (`systemctl --user status forge-hub`)
   - **Step 4:** Can I still build a cube? (one manual `apply_spec` test)
   
   Write this as `docs/current/VERIFYING-CHANGES.md` — a one-page checklist the owner follows after every AI change batch.

---

## Cross-cutting / anything else

### The "one thing" summary for the owner

If you only do one thing from this review: **delete the 8 legacy test runners after forge_testbench reaches parity.** This removes ~3000 lines of dead code, simplifies `hub.py` (which imports all of them), and makes the remaining god-file splits safer and smaller. Everything else — conventions, guardrails, architecture maps — builds on a cleaner foundation.

### Risk assessment of the god-file splits

All four splits involve moving code between files without changing behavior. The risk is import breakage. Mitigations:
- Run `python -c "import hub.hub"` and `python -c "from devforge.platform.mcp_server import mcp"` after each split commit.
- Run `hub/tests/test_imports.py` if it exists, or add one.
- Each split is one commit — easy to revert.

### What this review deliberately avoids

- **Over-engineering:** No microservices, no dependency injection frameworks, no "clean architecture" with 7 layers. This is a solo project with one non-coder owner. The three-layer architecture (hub → engine → godot-ai over MCP bridges) already exists and works. The splits just make the existing layers visible in the file structure.
- **Rigid style rules:** No line-length enforcement, no naming convention police, no mandatory docstring formats. The six rules in Prompt 2 are habits, not gates.
- **Rewriting anything:** All splits are mechanical moves. No logic changes. No "while we're at it" refactoring. The splits create space for future improvements without risking breakage now.
- **New dependencies:** No new packages required for any recommendation. The guardrails use `ruff` which is one `pip install`.
