# Layer-3 Code-Health Review — DeepSeek V4 Pro (via Codebuff)
June 17, 2026 — All three tasks answered

## Task 1 — Architecture + god-file splits

### Recommended architecture

The project has ONE clean architecture already: **hub orchestrator → MCP boundary → engine pipeline**. This is the spine. Everything else organizes around it.

In one sentence a non-programmer can hold in their head: *"The hub is the control panel that talks to the engine; the engine plans and builds Godot scenes; they talk over a network boundary and can't import each other's code."*

Layering within that:
1. **`hub/` — Ops & admin layer.** FastAPI web server. Routes → shell commands → back. Support modules (`forge_env.py`, `forge_ops.py`, `forge_models.py`) are thin, shared libraries. Testing lives here too (`forge_testbench/`).
2. **`engine/devforge/` — Pipeline layer.** Plan → compile → validate → execute. Crosses an MCP boundary to talk to `godot-ai` and the Godot editor.
3. **Support scripts** (`hub/` legacy runners, `engine/scripts/`, `engine/experiments/`) — scheduled for migration or already archived.

The MCP boundary is the ONE enforced seam. Nothing in `hub/` imports from `engine/`. Nothing in `engine/` imports from `hub/`. Both import from `mcp` (the Python package). This is correct and should stay.

### Where the code follows it vs. muddies it

**Follows it:**
- `hub/hub.py` calls `forge_ops.py` and `forge_models.py` as thin shared libraries — no engine imports (`hub/hub.py:1-20`).
- `engine/devforge/platform/mcp_server.py` imports from `devforge.*` only — no hub imports (`engine/devforge/platform/mcp_server.py:14-31`).
- `engine/devforge/compilation/pipeline/engine.py` orchestrates the full pipeline cleanly: assembler → planner → compiler → generator → validator → repair (`engine/devforge/compilation/pipeline/engine.py:283-465`).
- `hub/forge_testbench/` is a clean testing chassis with one runner, one result shape, self-describing metrics. Every test registers itself via decorator (`hub/forge_testbench/catalog.py:31-40`).
- The spatial generation subsystem (`engine/devforge/spatial/`) has clean sub-planners and compile engines, each in its own file — good layering.

**Muddies it:**
- `hub/hub.py` is ONE file with ~1940 lines containing: security middleware, helper functions, ~45 route handlers, chain health, mode toggles, persona restore, bench routes, gauntlet routes, shootout routes, scenario routes, probe routes, stability analysis, tool-call probes, thinking toggle, embedding status, screenshot capture — ALL in one file. The architecture says "routes hit support modules," but the routes ARE the file.
- `engine/devforge/platform/mcp_server.py` (~2143 lines) has 30+ `@mcp.tool()` functions, server init, pipeline lock management, lazy init, and artifact logic — again all in one file. The architecture says "thin MCP server calls pipeline engine," but the server file IS thick.
- `engine/devforge/compilation/pipeline/engine.py` (~1444 lines) has the main pipeline PLUS 8 separate spatial planner paths (`_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_wfc_path`, `_run_voronoi_path`, `_run_room_path`, `_run_ops_path`, `_run_arch_path`) all in the same class. The `_run_spatial_path` factory at line 1078 was the right instinct, but the individual routing methods still bloat the file.
- `engine/devforge/execution/godot_ai_mcp.py` (~1076 lines) mixes: session management, circuit breaker, operation translation, tool result parsing, async internals for 12 different MCP tool calls, serialization round-trips, and a background event loop thread — all in one class. The executor interface says "one implementation," but this one class does too much.

### God-file split plan

#### 1. `engine/devforge/platform/mcp_server.py` (~2143 lines) — LOWEST RISK, SPLIT FIRST

The MCP server has a natural seam: each `@mcp.tool()` function is self-contained. The init logic is already factored into `_init()`.

**Target modules:**

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `platform/mcp_server.py` | Server bootstrap, `mcp` global, `_init()`, `__main__` block, pipeline lock helpers | ~250 |
| `platform/tools/scene_tools.py` | `apply_spec`, `get_scene`, `audit_scene`, `validate_spec`, `read_artifact` | ~400 |
| `platform/tools/batch_tools.py` | `batch_preview`, `batch_apply` | ~200 |
| `platform/tools/lore_tools.py` | `lore_schema_list`, `lore_data_validate`, `lore_integrity_check` | ~150 |
| `platform/tools/quality_tools.py` | `triage_errors`, `lint_content`, `polish_pass`, `quest_validate` | ~250 |
| `platform/tools/perf_tools.py` | `perf_sample`, `perf_history`, `smoke_run` | ~150 |
| `platform/tools/dev_tools.py` | `project_search`, `test_scaffold`, `balance_sim`, `signal_map`, `design_companion`, `dialogue_validate`, `scene_extract`, `scene_list_extractable` | ~350 |
| `platform/tools/template_tools.py` | `template_list`, `template_preview`, `template_apply` | ~150 |
| `platform/tools/journal_tools.py` | `journal_entries`, `journal_summary` | ~50 |

**How:** Each tool module defines a `register_tools(mcp)` function that attaches its `@mcp.tool()` functions. The server calls one `register_tools(mcp)` per module. This is ZERO-risk — tool functions don't call each other; they only call `_init()` and then module-level helpers.

**Safe order:** (1) `dev_tools.py` (largest, most independent), (2) `quality_tools.py`, (3) `template_tools.py`, (4) `lore_tools.py`, (5) `perf_tools.py`, (6) `batch_tools.py`, (7) `journal_tools.py`, (8) `scene_tools.py` (touches shared state). Each step: move one tool, restart, verify.

#### 2. `hub/hub.py` (~1940 lines) — SPLIT SECOND

The hub's routes group naturally by the tabs they serve in the UI.

**Target modules:**

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `hub/core.py` | App creation, middleware, job lock, helpers (`_run_capture`, `_job_runner`), `BUILD_ID` | ~200 |
| `hub/routes/status_routes.py` | `/`, `/api/status`, `/api/chain-health`, `/api/job/active`, `/api/selfcheck`, `/api/version` | ~350 |
| `hub/routes/model_routes.py` | `/api/models`, `/api/models/search`, `/api/swap`, `/api/config`, `/api/config/restore`, `/api/config/backups`, `/api/reconcile`, `/api/logs/{svc}`, `/api/doc` | ~300 |
| `hub/routes/bench_routes.py` | `/api/bench/*`, `/api/bench/probe/*` | ~100 |
| `hub/routes/scenario_routes.py` | `/api/scenarios`, `/api/scenarios/run`, `/api/scorecards`, `/api/scorecards/compare` | ~80 |
| `hub/routes/shootout_routes.py` | `/api/shootout`, `/api/shootout/preflight`, `/api/shootout/history`, `/api/shootout/{ts}` | ~80 |
| `hub/routes/gauntlet_routes.py` | `/api/gauntlet/*` | ~60 |
| `hub/routes/run_routes.py` | `/api/runs`, `/api/runs/compare`, `/api/runs/stability` | ~150 |
| `hub/routes/mode_routes.py` | `/api/mode`, `/api/odysseus/embedding-status`, `/api/odysseus/warmup`, `/api/persona/check`, `/api/persona/restore`, `/api/thinking/status`, `/api/thinking/toggle` | ~200 |
| `hub/routes/tool_routes.py` | `/api/tools/run`, `/api/tools/history`, `/api/logs-read`, `/api/screenshot`, `/api/actions` | ~100 |

**How:** FastAPI's `APIRouter` pattern. Each route file creates a `router = APIRouter()`, defines routes on it, exports it. `hub/core.py` imports and mounts all routers. This is the standard FastAPI pattern and is well-tested.

**Safe order:** (1) `run_routes.py` (self-contained, uses `_scan_runs` helper), (2) `gauntlet_routes.py`, (3) `shootout_routes.py`, (4) `bench_routes.py`, (5) `scenario_routes.py`, (6) `tool_routes.py`, (7) `mode_routes.py`, (8) `model_routes.py` (touches `_run_capture`, `_jobs`), (9) `status_routes.py` (touches `_job_lock`, `bench`, `scenarios` modules).

#### 3. `engine/devforge/compilation/pipeline/engine.py` (~1444 lines) — SPLIT THIRD (MODERATE RISK)

The engine has already factored out individual planner, compiler, validator, and repair modules. The remaining bloat is the 9 planner paths in one class plus the governance gates.

**Target modules:**

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `pipeline/engine.py` | `PipelineEngine.__init__`, `run_pipeline`, `update_history`, `validate_pipeline`, helper methods (`_normalize_scene`, `_dedupe_files`, `_dedupe_operations`) | ~350 |
| `pipeline/routing.py` | `_run_arch_path`, `_run_ops_path`, `_run_spatial_path` (the shared factory) | ~350 |
| `pipeline/spatial_routing.py` | `_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_wfc_path`, `_run_voronoi_path`, `_run_room_path` — each is a 1-liner delegation to `_run_spatial_path` | ~130 |
| `pipeline/governance.py` | `_run_governance_gates`, `GateResult`, delete/rename intent regex, entity recovery | ~250 |
| `pipeline/result.py` | `PipelineResult` dataclass, `GateResult` dataclass — move to own file | ~60 |

**How:** The `_run_spatial_path` factory at line 1078 already abstracts the common pattern. The individual `_run_*_path` methods are each ~15-line delegation to it. Moving them out is just extraction. The governance gates are self-contained and optional. The regex helpers (`_DELETE_INTENT_RE`, `_RENAME_TO_RE`, `_recover_entities_from_prompt`) should move with the governance module.

**Safe order:** (1) `result.py` (pure dataclasses, no imports out), (2) `spatial_routing.py` (thin delegation, clearly separable), (3) `routing.py` (the core `_run_arch_path` and `_run_ops_path` plus the shared factory), (4) `governance.py` (has try/except guards already, optional module).

#### 4. `engine/devforge/execution/godot_ai_mcp.py` (~1076 lines) — SPLIT FOURTH

The MCP executor has distinct concerns: session management, operation translation, tool-specific async methods, and result parsing.

**Target modules:**

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `execution/godot_ai_mcp.py` | `GodotAIMCPExecutor` class with `execute()`, `get_scene()`, `read_logs()`, `backend_name`, `_run()` dispatch helper, `shutdown()`, `__init__` | ~300 |
| `execution/mcp_session.py` | `_ensure_session`, `_close_session`, `_call_tool_safe`, `_record_mcp_failure`, circuit breaker state | ~200 |
| `execution/mcp_translate.py` | `_translate_ops_to_commands`, `_OP_TO_COMMAND`, `_FIELD_MAP`, `_DROP_FIELDS`, `_res_path` | ~100 |
| `execution/mcp_parse.py` | `_parse_tool_result`, `_parse_tool_result_text`, `_normalize_op_result`, `_unwrap_scene_hierarchy`, `_tree_from_flat` | ~100 |
| `execution/mcp_tool_calls.py` | All `_*_async` methods for specific MCP tools: `_execute_async`, `_get_scene_async`, `_read_logs_async`, `_resolve_node_properties_async`, `_find_symbols_async`, `_search_filesystem_async`, `_get_performance_monitors_async`, `_run_project_async`, `_stop_project_async`, `_game_eval_async`, `_take_screenshot_async`, `_execute_ops_individually` | ~400 |

**How:** Move the helper modules out, import them back into `GodotAIMCPExecutor`. The class keeps the public interface methods; the detail modules are called from them. This is low risk because the helper methods are mostly static or `self`-referencing only `_ensure_session()` and `_call_tool_safe()`.

**Safe order:** (1) `mcp_parse.py` (static methods, no internal deps), (2) `mcp_translate.py` (static/classmethods, no internal deps), (3) `mcp_session.py` (depends on `_mcp_url`, `_mcp_lock`, circuit breaker state — needs to be passed in or kept as instance state), (4) `mcp_tool_calls.py` (depends on session + translate + parse modules).

### What you're not asking that you should be

1. **What's the ONE test that proves each split didn't break anything?** For each god-file, name the single test or manual check that validates the split. Without this, splitting is scary. For `mcp_server.py`: run `apply_spec` with a simple prompt. For `hub.py`: hit `/api/status` and verify all fields. For `engine.py`: run the gauntlet against one model. For `godot_ai_mcp.py`: run `get_scene()`.

2. **Should the legacy runners be deleted BEFORE splitting to reduce the number of files that need updating?** Yes. The legacy test runners (`bench.py`, `shootout.py`, `scenarios.py`, `gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py`) are imported in `hub.py` (line 35-37: `import bench`, `import scenarios`, `import shootout`). Deleting them first simplifies the hub split.

3. **What's the actual MCP transport between hub and engine?** The docs say "MCP / subprocess boundary" but `hub/forge_testbench/runner.py` connects to DevForge at `http://127.0.0.1:8001/sse` (SSE transport) and godot-ai at `http://127.0.0.1:8000/mcp` (Streamable HTTP). The engine's MCP server runs SSE (`mcp.run(transport="sse")`). This is important because splitting files in the engine doesn't change the transport, but if you ever add a second engine process, you need to know both sides of the boundary.

---

## Task 2 — Conventions guide

### File & function length (+ offenders with line counts)

**Proposed limits:**
- **Files: ≤ 500 lines where possible; 800 absolute max.** Beyond 500, a single file can't fit on one screen for a reviewer scanning it with an AI assistant. Beyond 800, it almost always has multiple responsibilities.
- **Functions: ≤ 60 lines; 120 absolute max.** Most well-factored functions in this codebase are 20-40 lines. Longer functions signal "extract a helper."

**Offenders (files):**
| File | Lines | Primary reason |
|------|-------|---------------|
| `engine/devforge/platform/mcp_server.py` | 2,143 | 30+ MCP tool functions in one file |
| `hub/hub.py` | 1,940 | 45+ FastAPI routes in one file |
| `engine/devforge/compilation/pipeline/engine.py` | 1,444 | 9 planner paths + governance + pipeline core |
| `engine/devforge/execution/godot_ai_mcp.py` | 1,076 | Session, translation, parsing, 12 tool calls |
| `hub/scenarios.py` | ~1,000+ | Legacy, scheduled for migration |
| `hub/shootout.py` | ~950+ | Legacy, scheduled for migration |
| `hub/bench.py` | ~1,400+ | Legacy, scheduled for migration |
| `hub/gauntlet.py` | ~830+ | Legacy, scheduled for migration |

The legacy test runners (last 4) are scheduled for deletion — don't invest in splitting them.

**Offenders (functions):**
| Function | File | Lines | Why |
|----------|------|-------|-----|
| `run_pipeline()` | `engine/.../pipeline/engine.py:283-465` | ~180 | 9 planner branches + completeness + validation + governance inline |
| `chain_health()` | `hub/hub.py` | ~320 | All chain checks inline rather than in helper functions |
| `_execute_async()` | `execution/godot_ai_mcp.py` | ~150 | File creation + batch execute + retry + individual fallback all inline |
| `api_mode()` | `hub/hub.py` | ~100 | 3-step runner inline |
| `_apply_spec_impl()` | `platform/mcp_server.py` | ~80 | Replan loop, execution, artifact storage inline |

### Duplication to collapse (real path:line examples)

1. **`_run_capture` duplicated across hub modules.**
   - `hub/hub.py:118-129` — `async def _run_capture(cmd, timeout)`
   - `hub/forge_ops.py:158-169` — `async def run_cmd_capture(*cmd)` (identical logic, different name)
   - `hub/forge_testbench/runner.py:46-55` — `async def _sh(*cmd, timeout)` (same logic, third name)
   - **Fix:** One `run_cmd_capture` in `forge_ops.py`, used by all three. The hub's `_run_capture` already strips ANSI (`ANSI.sub("", ...)`); add that as an optional parameter to the shared version.

2. **`_read_env` duplicated across hub modules.**
   - `hub/forge_env.py:71-86` — `read_env(path)` with proper quoting handling
   - `hub/forge_testbench/runner.py:23-32` — `_read_env()` with naive `strip('"').strip("'")` — **BUG:** this one does NOT handle single-quoted values correctly (it strips quotes one at a time, but a value like `'{"enable_thinking": false}'` would be mangled)
   - **Fix:** `forge_testbench/runner.py` should import and use `forge_env.read_env(ENVFILE)` directly.

3. **`_godot_ai_call` / MCP client boilerplate duplicated.**
   - `hub/forge_testbench/runner.py:58-68` — `_godot_ai_call(tool, args)`
   - `hub/bench.py` — similar pattern (the legacy `_godot_ai_call` function used by hub's chain health)
   - `hub/scenarios.py` — similar pattern
   - **Fix:** Factor into a shared `hub/mcp_client.py` that all modules use. The forge_testbench already has `_devforge_call` and `_devforge_raw_call` too — bundle them.

4. **`read_env` + `strip` pattern used without the shared library.**
   - `hub/hub.py` line 900 area: `env = read_env(ENVFILE)` is correct
   - But `hub/forge_testbench/runner.py:23-32` reimplements it (see above)
   - `hub/calibrate_vram.py` likely has its own version
   - **Fix:** Audit all `os.environ` and `.env` reads for the `read_env` pattern. If they reimplement it, switch them to the library.

5. **Scene reset logic duplicated.**
   - `hub/forge_testbench/runner.py:114-190` — `_scene_reset()` with bounce trick, health check, cleanup
   - `hub/scenarios.py` — likely has its own scene reset for scenario tests
   - `hub/bench.py` — the legacy bench also resets scenes
   - **Fix:** After migrating to forge_testbench, the runner's `_scene_reset` becomes the single implementation.

### Naming convention (+ fossil names to fix)

**Recommended convention:**
- **Files:** `snake_case.py` for modules. `kebab-case.md` for docs. One word + one role where possible (`forge_env.py`, `forge_ops.py`, `forge_models.py`).
- **Functions:** `snake_case`. Public API functions use verbs (`read_env`, `write_env`, `swap_model`). Private helpers use `_prefix`. Async functions don't need a different suffix — the `async def` is enough.
- **Classes:** `PascalCase`. Use the role as the noun: `ArchitecturePlanner`, `PipelineEngine`, `SceneDoctor`. Avoid `Manager`, `Handler`, `Processor` — they're vaguer.
- **Modules/packages:** One level of nesting where possible. `pipeline/engine.py` is better than `compilation/pipeline/engine.py` — the `compilation` prefix on EVERY pipeline import is noisy.

**Fossil names to fix:**
| Current name | File | Issue | Suggested |
|-------------|------|-------|-----------|
| `arch_delta` | `engine.py`, `mcp_server.py`, across the codebase | "Architecture delta" is a mouthful. It's the planner's output. | `plan_output` or just `delta` |
| `_remove` / `_rename` keys in arch_delta | `engine/.../pipeline/engine.py:869-900` | Underscore-prefixed string keys in a dict are a code smell. These are special markers. | Use a dedicated field on PipelineResult or a marker enum |
| `_HAS_SPATIAL`, `_HAS_GOVERNANCE` | `engine/.../pipeline/engine.py:41,145` | Module-level booleans set by try/except are fragile — a typo in the import silently disables a feature. | Replace with explicit `HAS_SPATIAL = True` after import; let the ImportError propagate or be caught at a single config init point |
| `ops_planner` vs `arch_planner` vs `layout_planner` vs `building_planner` vs... | `engine/.../pipeline/engine.py` | 9 planner modes with ad-hoc naming. Each gets its own `_run_X_path` method AND its own `_X_planner` attribute. | All planners implement a `Planner` protocol with `.plan()` and `.grammar`. The routing table becomes a dict `{"arch": self._planner, "layout": self._layout_planner, ...}` |
| `valid_ops` / `validated_ops` | `engine/.../pipeline/engine.py`, `mcp_server.py` | Inconsistent — sometimes `valid_ops`, sometimes `validated`. | Pick one: `valid_ops` (shorter). |
| `forge-stack` vs `forge_stack` vs `ForgeStack` | Throughout `FORGE-STACK.md`, env vars, directory names | Hyphen in filenames, underscore in Python identifiers — standard, but the inconsistent casing across docs adds friction. | Kebab-case for filenames/docs; snake_case for code. Already mostly followed — just clean up the few exceptions. |

### Minimal loose rules (each + one-line rationale)

1. **Every file starts with a one-sentence docstring saying WHAT it is.**
   - *Rationale:* A non-programmer reviewer can grep `"""` at the top of every file and know what it does without reading code.
   - Already followed in ~90% of files. Fix the remaining ~10%.

2. **If a function is over 60 lines, extract a helper — no exceptions without a comment saying why.**
   - *Rationale:* Long functions are the #1 barrier to AI assistants making safe edits. A helper with a name is self-documenting.

3. **One class per file, unless the secondary class is a small dataclass or exception (<20 lines) tightly coupled to the primary.**
   - *Rationale:* Keeps files scannable. Already followed in most of the engine (`spatial/`, `knowledge/`, `reasoning/`).

4. **Shared utilities go in named libraries, not copy-pasted into callers.**
   - *Rationale:* The `_read_env` bug in `forge_testbench/runner.py` (different from `forge_env.read_env`) is why duplication is dangerous.

5. **`from __future__ import annotations` at the top of every Python file that has type hints.**
   - *Rationale:* Prevents circular import issues with forward references. Already followed in ~95% of files — just standardize the last few.

6. **Section dividers use `# ── Section Name ──` style. Keep sections under ~100 lines.**
   - *Rationale:* Makes scanning with `grep "^# ──"` give a table of contents for any file. Already the project's strongest convention — just enforce that sections don't grow beyond 100 lines.

### What you're not asking that I should be

1. **Should there be a `pyproject.toml` or a `Makefile` with the conventions ENCODED as automated checks?** A non-programmer shouldn't have to remember these rules. A single `make lint` that runs a formatter + checks is worth more than any documented convention. (See Task 3.)

2. **What's the MINIMUM viable test for every split?** You're asking where to split, but not what test proves the split was safe. For a non-programmer directing AI, every code change needs one — and ideally ONLY one — test to run afterward. "Run the gauntlet" is too broad. "Run `apply_spec` with 'add a red cube'" is specific.

3. **Which of these conventions is already broken in parts of the codebase, and should those be fixed BEFORE formalizing the convention?** E.g., the `_HAS_SPATIAL` pattern violates "don't silently disable features," but it's used in 3+ files. Fixing it is a separate task from recommending it.

---

## Task 3 — Review & navigation environment

### Structural signals

**What already works well:**
- **Section dividers: `# ── Section ──`** — Used consistently in `hub/hub.py`, `engine/.../mcp_server.py`, `engine/.../engine.py`. Running `grep "^# ──" *.py` gives a table of contents. This is the single best navigational aid in the codebase.
- **Module docstrings** — Almost every file opens with a `"""..."""` explaining its purpose. `forge_env.py` is exemplary: lists its public API right at the top (`forge_env.py:1-3`). `forge_ops.py` does the same (`forge_ops.py:1-10`).
- **`__init__.py` as a public API declaration** — `hub/forge_testbench/__init__.py:1-27` lists every public symbol with a one-line comment. This is the right pattern for every subpackage.

**What to add:**
1. **Top-level architecture map file.** A single `ARCHITECTURE.md` at the repo root with:
   ```
   hub/          → Ops panel (FastAPI, port 8003). Talks to engine via MCP/SSE.
   engine/       → DevForge pipeline. Talks to godot-ai via MCP/HTTP.
   docs/         → Current docs, archive, decisions.
   ```
   One diagram. One sentence per directory. This is what a non-programmer reads first. (Already exists as `docs/current/FORGE-STACK.md` but it's buried. Link it from the README.)

2. **Consistent entry points.** Every subpackage with >3 files should have an `__init__.py` that re-exports its public API, like `hub/forge_testbench/__init__.py` does. Audit the engine: `engine/devforge/knowledge/`, `engine/devforge/spatial/`, `engine/devforge/reasoning/` should all have clear `__init__.py` files.

3. **Predictable file placement.** The rule of "one class, one file" should be the default. When you see `spatial/ssp.py` + `spatial/ssp_planner.py`, the naming convention (`_planner` = LLM interface, bare name = engine) is discoverable. Document this in the architecture map: "`*_planner.py` = LLM-facing, `*.py` = deterministic engine."

4. **`# noqa` comments with reasons.** Several files use `# noqa: E402` for late imports (`hub/hub.py:37`, `hub/hub.py:35`). Those are fine but the REASON should be in a comment: `# noqa: E402 — imported after app creation to avoid circular deps`. Without the reason, a reviewer doesn't know if the noqa is intentional or lazy.

### Reviewable diffs for a non-coder

**What makes a diff understandable:**
1. **Descriptive commit messages that say WHY.** The existing convention of "Bug 2 (2026-06-14): ..." in code comments is excellent (`engine/.../pipeline/engine.py:75-78`). Extend this to commit messages: `"[Bug fix] Scene reset bounce trick prevents stale Main2 cache"` is reviewable. `"fix stuff"` is not.

2. **One logical change per commit.** When an AI makes 5 unrelated changes in one commit, the diff is unreadable. The non-coder should be able to look at a commit and say "this only changes how scenes are reset."

3. **`git diff --stat` as a gut check.** Before reviewing, run `git diff --stat`. If 15+ files changed, the change is probably too broad. If 1-3 files changed, it's scannable.

4. **Self-documenting test results.** The forge_testbench's `summary()` function (`hub/forge_testbench/reporting.py:119-155`) produces a human-readable summary with ✓/✗ icons and plain-language scores. After every change, running the testbench and pasting the summary into the commit message gives a non-coder a "before/after" picture without reading code.

**Specific recommendations:**
- Add a `make test-quick` target that runs the fast probe suite and prints the summary. The non-coder runs ONE command and sees ONE output.
- Add a `make diff-summary` target that runs `git diff --stat HEAD~1` and prints it. This is the first thing to read before any review.

### Automated guardrails (most relief per setup)

**What to add, ordered by benefit ÷ setup cost:**

1. **Black (formatter) — 5 minutes setup, infinite relief.**
   ```bash
   pip install black
   # Add to both virtualenvs
   ```
   Run `black --check .` in CI or as a pre-commit hook. Zero configuration. Zero decisions. Removes ALL formatting debates from code review forever. The non-coder never has to say "fix the indentation."
   - **Files to check:** All `hub/*.py` and `engine/devforge/**/*.py`.
   - **One-time cost:** Running `black .` once will reformat everything. Do it in one commit so the diff is pure formatting.

2. **Ruff (linter) — 10 minutes setup, high relief.**
   ```bash
   pip install ruff
   ```
   Single `ruff.toml` at the repo root. Enable the rules that catch REAL bugs:
   - `F` (pyflakes) — catches undefined names, unused imports
   - `E/W` (pycodestyle) — catches syntax errors, bad whitespace
   - `B` (flake8-bugbear) — catches common bugs like mutable defaults
   - `SIM` — catches over-complicated code
   - Explicitly DISABLE style-only rules to avoid noise.
   
   Run `ruff check .` in CI. This catches the `_read_env` bug type: a function that looks right but has a subtle quoting error.

3. **mypy (type checker) — 30 minutes setup, medium relief.**
   This codebase already has thorough type hints (`hub/hub.py`, `engine/.../engine.py`, `forge_testbench/**/*.py`). Adding `mypy --strict` is feasible. Start with `mypy hub/forge_testbench/` (small, well-typed) and expand.
   - **Benefit:** Catches the "passed wrong type to function" class of bugs that AI assistants introduce.
   - **Cost:** Some existing modules will fail. Add `# type: ignore` with a comment, fix them incrementally.

4. **Pre-commit hooks — 15 minutes setup, ongoing relief.**
   ```yaml
   # .pre-commit-config.yaml
   repos:
     - repo: https://github.com/psf/black
       rev: 24.x
       hooks:
         - id: black
     - repo: https://github.com/astral-sh/ruff-pre-commit
       rev: v0.x
       hooks:
         - id: ruff
   ```
   After installing, every `git commit` runs the checks. The AI can't commit code that fails them. The non-coder never has to enforce conventions.

5. **One `make check` target — 5 minutes setup.**
   ```makefile
   .PHONY: check
   check:
   	black --check hub/ engine/
   	ruff check hub/ engine/
   	# mypy hub/forge_testbench/  (uncomment when ready)
   	@echo "All checks passed."
   ```
   The non-coder runs ONE command. That's the whole interface. Individual tools don't matter — only `make check` matters.

**What NOT to add (over-engineering for a solo project):**
- DON'T add `pylint` — too many false positives, too much configuration. Ruff covers 80% of what pylint does with zero config.
- DON'T add `isort` separately — Ruff has import sorting built in.
- DON'T add complex CI pipelines — a single `make check` in `.github/workflows/` is enough. The non-coder isn't managing CI infrastructure.
- DON'T add coverage thresholds — they're noise at this stage. Run tests, see pass/fail; coverage is for when there's a dedicated QA person.

### What you're not asking that I should be

1. **What's the ONE command the non-coder runs after every AI change to know if it's safe?** The answer should be `make check && make test-quick`. Everything else is noise. If those pass, the change is probably fine. If they don't, something broke. Designing that ONE command is the most important system decision.

2. **How do we prevent the guardrails from breaking the AI workflow?** If `black` reformats a file the AI is editing, the AI's next edit might fail on whitespace mismatch. Solution: run `black .` once to normalize the whole codebase, THEN start the split work. Don't interleave formatting with functional changes.

3. **Should there be a `.git-blame-ignore-revs` file?** When you run `black .` on the whole codebase, it creates one massive reformatting commit. Adding that commit hash to `.git-blame-ignore-revs` means `git blame` skips it and shows the real author of each line. Without this, every line blames to "format everything" and history is lost. This is a 30-second fix that saves hours of confusion.

---

## Cross-cutting / anything else

### The project's true strengths (don't lose these)
1. **The section-divider convention** (`# ── Section ──`) is genuinely excellent. It makes every file scannable.
2. **The `forge_testbench/` redesign** is clean: one runner, one result shape, self-describing metrics. This is the right pattern for everything else.
3. **The MCP boundary is enforced.** No `hub/` file imports from `engine/`. No `engine/` file imports from `hub/`. This is architectural hygiene that many projects lose over time.
4. **Public API documentation in `__init__.py`** (`forge_testbench/__init__.py`) and module docstrings (`forge_env.py`, `forge_ops.py`) is thorough and consistent.
5. **The testbench migration is correctly scoped.** Deleting 6 legacy test runners and replacing them with one chassis is the right call. Don't let scope creep delay it.

### Things that work against the non-coder review goal
1. **The `_HAS_*` try/except pattern** silently disables features. A non-coder reviewer can't tell that `_HAS_SPATIAL = False` is a catastrophic failure vs. an expected state.
2. **The 9-planner routing in `engine.py`** makes every change to the pipeline require understanding all 9 paths. A non-coder reviewing a diff to `_run_arch_path` can't know if it accidentally broke `_run_ssp_path`.
3. **The `arch_delta` dict keys** (`_remove`, `_rename`, `entities`, `systems`, `connections`) are magic strings. A non-coder can't grep for "where does `_remove` get set?" and find all the places.

### One change that would pay for itself immediately
Add a `make doctors` target that runs:
- `black --check`
- `ruff check`
- `grep -r "TODO\|FIXME\|HACK\|XXX" hub/ engine/ --include="*.py"` (find all tech debt markers)

The non-coder runs it once per session, sees a list of issues, and knows where to point the AI next. This is higher leverage than any documentation change.
