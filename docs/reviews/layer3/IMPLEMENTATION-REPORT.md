# Implementation Report — cleanup/layer3-code-health

**Date:** 2026-06-17  
**Branch:** `cleanup/layer3-code-health`  
**Status:** Phase 0 + Guardrails + Navigation Aids complete. Phase 1 (god-file splits) deferred.

---

## STEP G — Guardrails ✓

- **pyproject.toml**: Ruff config with format (Black-compatible, line-length 120) + lint rules F, I, B. Disabled B904, B028.
- **Format pass**: Single commit `d5f69a2` — reformatted 272 files across `hub/` and `engine/`.
- **.git-blame-ignore-revs**: Added formatting commit hash.
- **scripts/check.sh**: Runs `ruff check`, `ruff format --check`, and file-length gate (fail if any `.py` > 500 lines).
- **Smoke**: `ruff format --check` passes after initial format; `ruff check` shows remaining violations (4 in hub.py, none critical).

---

## STEP 0.1 — `hub/mcp_client.py` ✓

Created shared MCP client wrappers:
- `devforge_call(tool, args)` — any DevForge MCP tool
- `apply_spec(prompt, planner, ...)` — DevForge pipeline call
- `read_artifact(artifact_id)` — artifact fetch
- `godot_ai_call(tool, args)` — any godot-ai MCP tool

**Repointed live callers:**
- `hub/forge_testbench/runner.py` — imports from mcp_client
- `hub/diagnostics.py` — imports from mcp_client (kept bench imports for scene helpers)
- `hub/hub.py` — chain_health, logs_read, screenshot use mcp_client

**Smoke:** Module imports without errors in Python environment. Owner must verify `/api/status` chain-health.

---

## STEP 0.2 — Fix `read_env` quote-strip bug ✓

- `hub/forge_testbench/runner.py` now imports `read_env` from `hub/forge_env` instead of reimplementing it with naive `strip('"').strip("'")`.
- The bug: single-quoted JSON values like `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'` were mangled by the old code.

**Smoke:** Owner must verify a testbench run reads `enable_thinking` correctly.

---

## STEP 0.3 — Shell helper consolidation ✓

- `forge_ops.run_cmd_capture` now accepts `timeout` (seconds) and strips ANSI codes.
- Hub's `_run_capture` delegates to `run_cmd_capture`.
- Runner's `_sh` delegates to `run_cmd_capture` with timeout passthrough.

**Smoke:** Module import check. Owner must verify live: `/api/status` still returns clean output.

---

## STEP 0.4 — Extract `_start_job` in hub.py ✓

- Added `_start_job(label, action_fn)` helper that acquires the lock, creates the job dict, runs the action, and releases the lock.
- `/api/run` endpoint converted to use `_start_job`.
- Fixed double lock-release: `_job_runner` no longer releases the lock (callers own the lifecycle).
- Other endpoints (swap, reconcile, bench, scenarios, gauntlet, shootout, mode, persona) still use manual pattern — safe, just not yet converted to `_start_job`.

**Smoke:** Owner must verify `/api/swap` still streams + releases lock.

---

## STEP 0.5 — Kill silent HAS_SPATIAL / HAS_GOVERNANCE ✓

- Removed module-level `try: import / except: HAS_X = True/False` pattern.
- `PipelineEngine.__init__` now does explicit `try/except ImportError` with logger.warn on failure.
- `_run_governance_gates` now does its own `try/except ImportError` instead of checking `_HAS_GOVERNANCE`.

**Smoke:** Owner must verify engine MCP server starts and `apply_spec` works.

---

## STEP 0.6 — Trim monitor / delete dead stub ✓

- Deleted `engine/devforge/compilation/pipeline/incremental_context_builder.py` (dead stub).
- Moved Monitor class from `monitor/__init__.py` to `monitor/monitor.py`.
- `monitor/__init__.py` is now a thin re-export (`from .monitor import Monitor; monitor = Monitor()`).
- Fixed duplicate Monitor singleton — only `__init__.py` creates the instance.

**Smoke:** Owner must verify engine MCP server starts (monitor is imported at startup).

---

## STEP N — Navigation Aids ✓

- **`docs/current/CODE-ARCHITECTURE.md`**: File-by-file map with one-line job descriptions.
- **Root `README.md`**: Added links to CODE-ARCHITECTURE.md and FORGE-STACK.md.
- **`engine/README.md`**: Notes the `devforge` package name is a historical fossil.
- **Per-package `__init__.py`**: `hub/mcp_client.py` provides clean API surface. Monitor re-export improved.

---

## Phase 1 — DEFERRED

Phase 1 god-file splits were NOT executed:
- **1A**: `godot_ai_mcp.py` → `godot_ai_executor.py` + `mcp_session.py` + `op_translator.py` (1076 lines)
- **1B**: `pipeline/engine.py` → `pipeline_orchestrator.py` + `result.py` + `planner_routing.py` + `post_planner.py` (1444 lines)
- **1C**: `mcp_server.py` → thin server + `platform/tools/*.py` (2143 lines)

These are high-risk refactors that require the live stack for smoke testing and carry the highest API risk (tool names must not drift). They are gated on **the owner having the live stack ready for end-to-end testing**.

---

## Remaining ruff lint violations

4 violations remain in `hub/hub.py` after auto-fix:
- `_json` is used but ruff can't resolve it (mid-function `import json as _json` pattern)
- Not critical — behavior is unchanged

---

## Smoke checks owner must run on live stack

| Step | What to verify |
|------|---------------|
| 0.1 | `/api/status` chain-health is green |
| 0.2 | Testbench run reads `enable_thinking` correctly from stack.env |
| 0.3 | `/api/status` returns clean (ANSI-free) output |
| 0.4 | `/api/swap` streams progress and releases lock correctly |
| 0.4 | `/api/run` (e.g. restart-llama) streams and completes |
| 0.5 | Engine MCP server starts; `apply_spec "add a red cube"` works |
| 0.6 | Engine MCP server starts (monitor is imported at startup) |
| 1A | `get_scene()` + `execute` of "add a red cube" (deferred) |
| 1B | Gauntlet "add a red cube" + one spatial prompt (deferred) |
| 1C | MCP registration loads; `apply_spec` runs end-to-end (deferred) |

---

## Commits on branch

1. `d5f69a2` — chore: add ruff config, format entire tree, add check.sh guardrail
2. `f21665c` — chore: add .git-blame-ignore-revs for ruff formatting pass
3. `3c7701a` — refactor: extract hub/mcp_client.py, fix stderr-loss, use forge_env.read_env, add _start_job
4. `34247d2` — refactor: fix silent HAS_SPATIAL/HAS_GOVERNANCE, trim monitor, delete dead stub, add navigation aids
5. `5a3b686` — fix: double lock-release in _job_runner, duplicate Monitor singleton, _sh timeout passthrough
