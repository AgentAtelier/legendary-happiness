# Layer-3 Code-Health Review — Mimo (mimo-v2.5)

**Date:** June 17, 2026
**Tasks answered:** 1 (Architecture + god-file splits), 2 (Conventions guide), 3 (Review & navigation environment)

---

## Task 1 — Architecture + god-file splits

### Recommended architecture

The Forge stack already has one natural architecture. It just needs a name so you can talk about it:

**Three services, one boundary.**

1. **Hub** (`hub/hub.py`, port 8003) — the ops panel. Its only job is to present status, manage the stack (swap models, restart services, edit config), and run test suites. It shells out to `stack` CLI and `forge-model`; it never reimplements their logic.

2. **Engine** (`engine/devforge/`, port 8001) — the generation pipeline. Prompt in, Godot operations out. Internally: context assembly → LLM planner → architecture compiler → operation generator → validation → repair → execution against Godot. The engine talks to Godot exclusively through godot-ai's MCP interface; it never touches Godot directly.

3. **Godot bridge** (`godot-ai`, port 8000) — a thin MCP server wrapping the Godot editor's GDExtension API. It is not yours to maintain; treat it as a black box.

The boundary between Hub and Engine is the HTTP/MCP boundary on port 8001. The boundary between Engine and Godot is the MCP boundary on port 8000. Neither side imports the other. That's the whole architecture — two seams, three services, each independently restartable.

Supporting pieces that don't live in the service architecture:
- **llama.cpp** (port 8002) — the LLM inference server. The engine calls it via HTTP; nothing else touches it.
- **Odysseus** (port 7000, Docker) — the AI agent that calls DevForge's MCP tools. It's a consumer of the engine, not part of it.
- **Test runners** (`hub/bench.py`, `hub/shootout.py`, `hub/scenarios.py`, `hub/gauntlet.py`) — legacy, being migrated to `hub/forge_testbench/`.

### Where the code follows it vs. muddies it

**Follows it well:**

- The MCP boundary is clean. `mcp_server.py` imports `PipelineEngine` and `GodotAIMCPExecutor` but never imports hub code. `hub.py` imports `bench`, `scenarios`, `shootout`, `gauntlet` but never imports engine code. The two never cross-import. ✓
- `engine/devforge/compilation/pipeline/engine.py:192` (`PipelineEngine`) is the right abstraction — one class owns the full prompt→operations pipeline. ✓
- `engine/devforge/execution/godot_ai_mcp.py:30` (`GodotAIMCPExecutor`) cleanly implements the `Executor` interface, keeping the godot-ai transport behind a clean seam. ✓
- `hub/forge_env.py`, `hub/forge_models.py`, `hub/forge_ops.py` are well-factored support modules — small, focused, reused by hub.py. ✓

**Muddies it:**

- **hub.py has testing logic that belongs in the test system.** The hub imports `bench`, `scenarios`, `shootout`, and `gauntlet` directly (`hub/hub.py:51-53`, `hub/hub.py:1125`) and defines 20+ route handlers for test orchestration. This means hub.py is simultaneously the ops panel AND the test runner coordinator. The test system should own its own FastAPI routes or CLI entry point; the hub should just proxy to it or provide a link.
- **mcp_server.py is a god-tool-file, not a layer.** It imports 25+ modules (`mcp_server.py:28-62`) and exposes 20+ MCP tools in a flat list. The tools have no grouping — lore tools, perf tools, template tools, scene tools, and the core pipeline tools all live side-by-side. This makes it hard to see what the "core" surface is vs. optional extensions.
- **engine.py mixes routing with business logic.** The `run_pipeline()` method (`engine.py:283`) has a 7-way if/elif dispatch for planner modes, each calling a `_run_*_path()` method. But `_run_arch_path()` (`engine.py:785`) embeds 200+ lines of delete/rename intent parsing, entity recovery, system inference, and dedup — these are post-planner fixups that belong in their own module.

### God-file split plan

#### 1. `hub/hub.py` (1,940 lines) — Split FIRST (lowest risk)

**Why first:** Hub is a pure HTTP facade — no business logic to untangle, just route handlers to reorganize. Every route is self-contained. Low risk of breaking anything.

**Target modules:**

| New file | Lines (approx) | Responsibility |
|----------|-----------------|---------------|
| `hub/routes_status.py` | ~120 | `/api/status`, `/api/version`, `/api/selfcheck`, `/api/job/active` |
| `hub/routes_config.py` | ~100 | `/api/config` (GET/POST), `/api/config/restore`, `/api/config/backups` |
| `hub/routes_models.py` | ~100 | `/api/models`, `/api/models/search`, `/api/swap` |
| `hub/routes_stack.py` | ~80 | `/api/run`, `/api/reconcile`, `/api/stream` (job system) |
| `hub/routes_testing.py` | ~350 | `/api/bench/*`, `/api/scenarios/*`, `/api/shootout/*`, `/api/gauntlet/*`, `/api/runs/*`, `/api/tools/*`, `/api/runs/stability` |
| `hub/routes_diagnostic.py` | ~200 | `/api/chain-health`, `/api/logs/*`, `/api/logs-read`, `/api/screenshot` |
| `hub/routes_persona.py` | ~130 | `/api/mode`, `/api/persona/*`, `/api/thinking/*`, `/api/odysseus/*` |
| `hub/routes_activity.py` | ~50 | `/api/actions` |
| `hub/hub.py` (remains) | ~150 | App creation, middleware, job lock, helpers (`_run_capture`, `_job_runner`), `app.include_router()` calls, `__main__` |

**How:** Create an `APIRouter` per group. Move the route functions. Import the shared helpers (`_run_capture`, `_job_runner`, `_job_lock`, `app`). Wire them into `hub.py` via `app.include_router(router)`. The helpers and job system stay in `hub.py` since they're used by every router.

**Risk order:** Routes are pure function搬家 — no logic changes. Test by hitting every endpoint after the move.

#### 2. `engine/devforge/execution/godot_ai_mcp.py` (1,076 lines) — Split SECOND

**Why second:** This is a single class with clear internal seams. The session management, operation translation, and async dispatch are distinct concerns.

**Target modules:**

| New file | Responsibility |
|----------|---------------|
| `engine/devforge/execution/mcp_session.py` | `_ensure_session`, `_close_session`, `_call_tool_safe`, `_record_mcp_failure`, circuit breaker state (~150 lines). This is reusable transport logic. |
| `engine/devforge/execution/op_translator.py` | `_OP_TO_COMMAND`, `_FIELD_MAP`, `_translate_ops_to_commands`, `_res_path`, `_normalize_op_result`, `_parse_tool_result`, `_parse_tool_result_text`, `_unwrap_scene_hierarchy`, `_tree_from_flat` (~200 lines). Pure functions, easy to unit test. |
| `engine/devforge/execution/godot_ai_mcp.py` (remains) | `GodotAIMCPExecutor` class: `__init__`, interface methods (`execute`, `get_scene`, `read_logs`, etc.), async internals (`_execute_async`, `_get_scene_async`, etc.). Drops to ~700 lines. |

**Risk order:** Extract the static/pure functions first (op_translator), then the session management, then slim the main class.

#### 3. `engine/devforge/compilation/pipeline/engine.py` (1,444 lines) — Split THIRD

**Why third:** The planner routing and post-planner fixups are entangled. Requires careful untangling of the delete/rename intent logic.

**Target modules:**

| New file | Responsibility |
|----------|---------------|
| `engine/devforge/compilation/pipeline/planner_routing.py` | The 7-way planner dispatch (layout/building/scatter/ssp/room/wfc/voronoi/ops/arch). Extract the `_run_spatial_path` factory and the 7 thin `_run_*_path()` methods. Also the `_run_ops_path` and `_run_arch_path` methods. (~500 lines) |
| `engine/devforge/compilation/pipeline/post_planner.py` | `_clean_rename_target`, `_DELETE_INTENT_RE`, `_RENAME_TO_RE`, `_ENTITY_FROM_PROMPT_RE`, `_recover_entities_from_prompt`, the delete/rename intent pre-pass from `_run_arch_path`, entity recovery, `infer_systems` delegation, deterministic dedup (`_live_scene_names`). (~200 lines of pure functions + the fixup orchestration extracted as a function). |
| `engine/devforge/compilation/pipeline/engine.py` (remains) | `PipelineEngine.__init__`, `run_pipeline` (simplified — just calls routing + post-planner + completeness + validation + repair + governance), dataclasses, helpers. Drops to ~600 lines. |

**Risk order:** Extract pure functions first (post_planner.py — regex patterns, entity recovery, rename cleaning). Then extract the routing table (planner_routing.py). Then simplify `run_pipeline()` to compose the extracted pieces.

#### 4. `engine/devforge/platform/mcp_server.py` (2,143 lines) — Split LAST

**Why last:** The MCP server's tools are the most sensitive surface — they're what Odysseus calls. Breaking tool names or signatures breaks the AI agent. Split carefully.

**Target modules:**

| New file | Responsibility |
|----------|---------------|
| `engine/devforge/platform/tools/pipeline_tools.py` | `apply_spec`, `_apply_spec_impl`, `validate_spec`, `get_scene`, `read_artifact` — the core pipeline tools (~350 lines) |
| `engine/devforge/platform/tools/scene_tools.py` | `audit_scene`, `batch_preview`, `batch_apply`, `scene_extract`, `scene_list_extractable` (~250 lines) |
| `engine/devforge/platform/tools/lore_tools.py` | `lore_schema_list`, `lore_data_validate`, `lore_integrity_check`, `quest_validate`, `lint_content`, `dialogue_validate` (~300 lines) |
| `engine/devforge/platform/tools/dev_tools.py` | `template_list`, `template_preview`, `template_apply`, `test_scaffold`, `project_search`, `signal_map`, `design_companion`, `smoke_run` (~300 lines) |
| `engine/devforge/platform/tools/monitoring_tools.py` | `perf_sample`, `perf_history`, `journal_entries`, `journal_summary`, `triage_errors`, `polish_pass` (~250 lines) |
| `engine/devforge/platform/mcp_server.py` (remains) | MCP server setup, `_init()`, shared state, pipeline lock, `if __name__ == "__main__"`. Tool registration via `mcp.tool()` imports. Drops to ~300 lines. |

**How:** Each tools module defines functions that take the shared state (`_engine`, `_executor`, `_scene_store`, etc.) as parameters or via a context object. The main `mcp_server.py` calls `register_tools(mcp, ctx)` from each module.

**Risk order:** Extract the pure-deterministic tools first (lore, monitoring — no side effects, easy to test). Then scene tools. Then pipeline tools last (most complex, most side effects).

### What you're not asking that you should be

1. **"What is the blast radius of a bad edit?"** — The four god files are all in the hot path. A bug in `mcp_server.py` breaks every AI interaction. A bug in `godot_ai_mcp.py` breaks every scene operation. Consider whether any of these files should have a basic smoke test that catches regressions before the AI agent notices.

2. **"Should I delete the legacy test runners before or after splitting hub.py?"** — The ROADMAP says they're scheduled for deletion. Deleting them first removes ~1,000 lines from hub.py's import surface and ~6 route groups, making the split simpler. Do that first.

3. **"What's the test surface for the splits?"** — The project has no unit tests for these files. Each split should produce at least one test per extracted module (even just "import succeeds and key function is callable"). Otherwise you're flying blind.

---

## Task 2 — Conventions guide

### File & function length (+ offenders with line counts)

**Rule: Files ≤ 400 lines. Functions ≤ 60 lines.**

400 lines is roughly the point where a file requires scrolling past what fits on one screen. 60 lines is roughly the point where a function requires more than one mental "chunk" to hold in your head. These are soft limits — a 450-line file is fine if it's cohesive; a 70-line function is fine if it's a straight-line sequence. But crossing these triggers a "should I split?" question, not an automatic refactor.

**Offenders (files):**

| File | Lines | Over by |
|------|-------|---------|
| `engine/devforge/platform/mcp_server.py` | 2,143 | 5.4× |
| `hub/hub.py` | 1,940 | 4.9× |
| `engine/devforge/compilation/pipeline/engine.py` | 1,444 | 3.6× |
| `engine/devforge/execution/godot_ai_mcp.py` | 1,076 | 2.7× |

**Offenders (functions):**

| Function | File:Line | Approx lines | Over by |
|----------|-----------|---------------|---------|
| `_init()` | `mcp_server.py:111` | ~120 | 2× |
| `_apply_spec_impl()` | `mcp_server.py:321` | ~115 | 1.9× |
| `chain_health()` | `hub.py:523` | ~150 | 2.5× |
| `run_pipeline()` | `engine.py:283` | ~180 | 3× |
| `_run_arch_path()` | `engine.py:785` | ~200 | 3.3× |
| `_execute_async()` | `godot_ai_mcp.py:483` | ~130 | 2.2× |
| `api_runs_stability()` | `hub.py` (stability route) | ~100 | 1.7× |

### Duplication to collapse (real path:line examples)

**1. The logger+journal twin pattern in mcp_server.py**

Every tool function does the same three steps: call the tool, log the result, journal-append. There are 15+ instances of this pattern:

```python
# Pattern repeated 15+ times in mcp_server.py
logger.info("mcp_server", f"...: {result['finding_count']} findings ...")
_journal.append("tool_name", f"...", {dict})
return result
```

**Where:** `mcp_server.py:545-552` (audit_scene), `mcp_server.py:816-823` (triage_errors), `mcp_server.py:946-954` (lore_data_validate), `mcp_server.py:1031-1037` (lore_integrity_check), `mcp_server.py:1115-1122` (quest_validate), `mcp_server.py:1286-1292` (lint_content), `mcp_server.py:1360-1367` (polish_pass), `mcp_server.py:1489-1493` (test_scaffold), `mcp_server.py:1581-1586` (smoke_run), `mcp_server.py:1652` (design_companion), `mcp_server.py:1756` (scene_extract).

**Fix:** Extract a `_record(tool_name, message, data, result)` helper that does `logger.info` + `_journal.append` in one call. Reduces each tool by 4-5 lines and makes the pattern impossible to get wrong.

**2. The _run_capture + _job_lock + job creation + runner pattern in hub.py**

Every long-running route does: acquire lock → create job dict → spawn asyncio task → runner function → release lock on completion. This is repeated verbatim in `run()`, `swap()`, `reconcile()`, `bench_run()`, `bench_probe_run()`, `api_scenarios_run()`, `api_shootout()`, `api_gauntlet_run()`, `api_tools_run()`, `api_mode()`, `api_persona_restore()`.

**Where:** `hub.py:207-231` (run), `hub.py:233-281` (swap), `hub.py:430-456` (reconcile), `hub.py:493-519` (bench_run), `hub.py:545-569` (bench_probe_run), `hub.py:610-640` (scenarios_run), `hub.py:653-688` (shootout), `hub.py:699-725` (gauntlet_run), etc.

**Fix:** Extract `async def _start_job(label, cmd_fn, action="") -> str` that handles lock acquire, job creation, task spawning, and lock release. Each route becomes: `job_id = await _start_job("swap model", lambda emit: swap_model(fragment, emit))` — one line.

**3. The `_run_path` delegation pattern in engine.py**

Seven methods (`_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_voronoi_path`, `_run_wfc_path`, `_run_room_path`) are 5-line wrappers that call `_run_spatial_path` with different arguments. They exist only to provide a named entry point for the if/elif dispatch.

**Where:** `engine.py:1214-1372` (seven 25-line methods that are all identical except for the planner instance and compile function).

**Fix:** Replace with a dict dispatch:
```python
_SPATIAL_ROUTES = {
    "layout": (self._layout_planner, self._spatial_compiler.compile_layout, "_layout"),
    "building": (self._building_planner, self._bsp_partitioner.compile_building, "_building"),
    ...
}
```
Eliminates ~150 lines of boilerplate. The `run_pipeline` if/elif chain becomes a dict lookup.

### Naming convention (+ fossil names to fix)

**Convention:** `snake_case` for everything. Module names describe what the file contains, not what it does. Classes are `PascalCase`. Private functions start with `_`.

| Name | Location | Issue | Fix |
|------|----------|-------|-----|
| `_run_capture` | `hub.py:118` | Misleading — it doesn't "capture" in any standard sense. It runs a command and strips ANSI. | `run_cmd` or `exec_cmd_stripped` |
| `_job_runner` | `hub.py:134` | Acceptable but generic. | Keep — the context is clear. |
| `_TimedLockContext` | `mcp_server.py:103` | Private class for a one-use context manager. Fossil from when the lock logic was more complex. | Inline as a `contextlib.contextmanager` function. |
| `Engine` (class) | `engine.py:192` | Named `PipelineEngine` externally but the file is `engine.py` — creates confusion about which is which. | Rename file to `pipeline_engine.py` to match the class name. |
| `devforge` (package) | Throughout | The engine was renamed from "DevForge" to "engine" but the package is still `devforge`. | Acceptable as a fossil — renaming would touch 200+ imports for no functional gain. Document it. |
| `TOOL_EDITOR_MANAGE` | `godot_ai_mcp.py:53` | "editor_manage" is a godot-ai tool name, not a DevForge concept. Fine as-is — it's a transport-level constant. | Keep. |

### Minimal loose rules (each + one-line rationale)

1. **No file > 400 lines.** — Keeps every file skimmable in one sitting.
2. **No function > 60 lines.** — Keeps every function understandable in one mental chunk.
3. **One class per file (unless the extras are small helpers).** — Makes file = concept; you know what a file is from its name.
4. **Every file starts with a one-line docstring.** — The non-coder owner can read the first line to know what a file is for.
5. **Every tool/route does: work → log → journal → return.** — Consistent pattern makes code review mechanical (check the pattern, not the logic).
6. **No business logic in hub.py route handlers.** — Hub is a facade; logic belongs in forge_ops, scenarios, or the engine.
7. **Tests live next to the code they test.** — `engine/foo.py` → `engine/tests/test_foo.py`. Keeps discoverability high.
8. **Delete dead code instead of commenting it out.** — Git preserves history; comments lie.
9. **One source of truth for config: `stack.env`.** — Prevents the drift bugs that already bit the project.
10. **Don't add a third copy of anything.** — Two is a pattern, three is a mess. (Already a cardinal rule in the docs.)

### What you're not asking that you should be

1. **"What happens when the AI assistant that maintains this code changes?"** — Conventions only work if the next AI reads them. Put the conventions file in `docs/current/CONVENTIONS.md` and have every AI session start by reading it.

2. **"Should I enforce these with a linter?"** — Yes, but only the ones that a linter can check (line length, file length, naming). The rest are review-time checks. Don't try to lint "no business logic in hub.py" — that's a human judgment call.

3. **"What's the naming convention for the modules I'm about to create?"** — Follow the existing pattern: `forge_env.py`, `forge_models.py`, `forge_ops.py` are support modules for the hub. New hub modules should be `hub/routes_*.py`. New engine modules should follow `devforge/*/module_name.py`.

---

## Task 3 — Review & navigation environment

### Structural signals

The goal: a non-coder (or a fresh AI assistant) should be able to look at any file and know what it is within 5 seconds.

**Already working:**

- `docs/INDEX.md` is a good entry point — it lists all current docs and explains the `current/` vs `archive/` convention. ✓
- `docs/current/FORGE-STACK.md` is the system map — it explains ports, components, and how they connect. ✓
- File-level docstrings exist in the key files: `mcp_server.py:1-14`, `engine.py:1-11`, `godot_ai_mcp.py:1-13`, `hub.py:1-12`. ✓

**Missing or broken:**

- **No architecture map file.** There's no single file that shows the 3-layer architecture (Hub → Engine → Godot) with file pointers. `FORGE-STACK.md` covers operational architecture (ports, services) but not code architecture (which file does what). Create `docs/current/CODE-ARCHITECTURE.md` — a one-page map:
  ```
  hub/hub.py          → FastAPI routes (the web UI)
  hub/forge_ops.py    → Stack operations (swap, reconcile, drift)
  hub/forge_models.py → Model scanning and VRAM estimation
  hub/forge_env.py    → stack.env read/write/validate

  engine/devforge/platform/mcp_server.py   → MCP tool surface (what Odysseus calls)
  engine/devforge/compilation/pipeline/engine.py → Pipeline orchestration
  engine/devforge/execution/godot_ai_mcp.py      → Godot-ai MCP client
  ```

- **Module docstrings are inconsistent.** Some files have excellent docstrings (`mcp_server.py:1-14`, `godot_ai_mcp.py:1-13`). Others have none. Every Python file should start with a one-sentence docstring that answers "what is this file for?" — no more.

- **The `engine/` directory tree is deep and unlabeled.** `engine/devforge/compilation/pipeline/engine.py` is 4 levels deep. There's no `__init__.py` docstring or README explaining what each subdirectory does. Add a `engine/devforge/README.md` that maps directories to responsibilities.

- **Fossil directory names.** `engine/devforge/` is the only surviving piece of the "DevForge" name. This is fine — renaming it would touch hundreds of imports — but add a one-line note in `engine/README.md`: "The `devforge` package name is a historical artifact from the DevForge era. It is the generation engine."

### Reviewable diffs for a non-coder

The non-coder owner reviews changes by looking at diffs. Here's what makes diffs understandable vs. opaque:

**Already working:**

- The `FORGE-STACK.md` cardinal rule "Verify LIVE, not just with unit tests" sets the right review priority. ✓
- The hub's `/api/selfcheck` endpoint (`hub.py:498`) verifies API shape matches frontend expectations — catches contract drift. ✓

**What would help:**

1. **Conventional commit messages tied to the task system.** Every commit should start with a prefix that maps to the roadmap: `[Phase-4]`, `[Phase-5]`, `[Fix]`, `[Refactor]`. The non-coder can then filter git log to see "what changed for Phase 4?" without reading every commit message.

2. **Diff-friendly function signatures.** When a function changes from 3 parameters to 7, the diff shows a wall of red/green. Use keyword-only arguments and dataclasses for function parameters with 4+ arguments. The diff then shows a clean add/remove of a single field.

3. **The `_init()` function in `mcp_server.py`** is 120 lines of configuration. Any change here produces a large diff that's hard to review. Splitting it into `_init_llm()`, `_init_executor()`, `_init_stores()` would make diffs surgical — a change to the LLM setup only touches `_init_llm()`.

### Automated guardrails (most relief per setup)

The owner can't babysit tooling. Pick the tools that run automatically and require zero manual intervention.

**Already working:**

- GitHub Actions CI (`claude.yml`, `claude-code-review.yml`) ✓

**High-value additions, in order of relief-per-setup:**

1. **`ruff check` (linter) — 5 minutes setup, runs on every commit.**
   Enforces: line length, unused imports, naming conventions, import sorting. This catches the most common "oops" mistakes without any human review load. Add to CI: `ruff check engine/ hub/`.
   
   Specific rules to enable:
   - `E501` (line length, set to 120 — generous but prevents 300-line lines)
   - `F401` (unused imports)
   - `F841` (unused variables)
   - `I001` (import sorting)

2. **`ruff format` (formatter) — 5 minutes setup, runs on every commit.**
   Eliminates all formatting debates. One command: `ruff format engine/ hub/`. The non-coder never thinks about indentation, trailing commas, or quote style again.

3. **`wc -l` gate in CI — 10 minutes setup.**
   A simple script that fails the build if any tracked Python file exceeds 400 lines:
   ```bash
   #!/bin/bash
   THRESHOLD=400
   for f in $(find engine/ hub/ -name '*.py' -not -path '*/.venv/*'); do
     lines=$(wc -l < "$f")
     if [ "$lines" -gt "$THRESHOLD" ]; then
       echo "FAIL: $f has $lines lines (max $THRESHOLD)"
       exit 1
     fi
   done
   ```
   This is the single most effective guardrail against god-file regrowth. It costs nothing to maintain and catches the problem before code review.

4. **No formatter beyond ruff.** Don't add black, isort, flake8, mypy, or pylint. Ruff covers all of them. Each additional tool is ongoing maintenance burden that the owner can't sustain.

### What you're not asking that you should be

1. **"What's the onboarding cost for a new AI assistant?"** — Today, a fresh AI session needs to read `FORGE-STACK.md` + `docs/INDEX.md` + the conventions guide + the code architecture map to be effective. That's 4 documents. Can you get it to 2? The architecture map and conventions guide can be merged into one `docs/current/CONTRIBUTING.md`.

2. **"What's the diff review process for the non-coder?"** — The owner reviews changes by looking at GitHub PRs. But most changes are made by AI assistants that commit directly. Consider: every AI session ends with a one-line summary of what changed and why, written in `docs/SESSION-CHANGES-YYYY-MM-DD.md`. This gives the owner a readable changelog without reading git diffs.

3. **"What if I need to revert a bad change?"** — The project uses git but doesn't appear to have branch protection or mandatory PRs. For a solo project this is fine, but consider: always create a branch before a multi-file refactor, and merge only after the tests pass. This gives you a clean revert point.

---

## Cross-cutting / anything else

**The biggest risk in this codebase is not code quality — it's the single-owner, AI-maintained review loop.** The owner trusts AI to write good code, but the AI has no memory between sessions. Every session starts fresh. The conventions, architecture map, and guardrails exist to give the next AI session the context it needs to not regress. Treat these documents as load-bearing infrastructure, not nice-to-haves.

**The legacy test runners are a tax on every change to hub.py.** `bench.py`, `shootout.py`, `scenarios.py`, `gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py` are imported by hub.py and define routes that the frontend calls. Deleting them (as the ROADMAP plans) removes ~1,000 lines from hub.py and lets the hub focus on being an ops panel. Do this before splitting hub.py — it makes the split dramatically simpler.

**The `_init()` function in mcp_server.py is the scariest single point of failure.** It configures the LLM, creates the executor, initializes stores, and builds the pipeline engine — all behind a lazy-init pattern with a threading lock. If any of this goes wrong, every MCP tool call fails. Consider splitting it into smaller init functions and adding a health-check that verifies each component initialized correctly.
