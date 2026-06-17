# God-file split & cleanup plan (handoff for the implementing AI)

**Date:** 2026-06-17 · **Source:** Layer-3 review consensus, reconciled.
**Gate:** owner-approved before any code moves. Each step ships green, behind a
**one named smoke test**, lowest risk first. Reference style: `hub/forge_testbench/`.

> **Per-step rule:** one concern per commit; run the step's smoke test; run
> `ruff format && ruff check --fix` on changed files; commit with a one-sentence
> message. Do **not** split the legacy runners (`bench.py`, `shootout.py`,
> `scenarios.py`, `gauntlet.py`, `multi_model_bench.py`, `comprehensive_bench.py`)
> — they are being deleted.

## Phase 0 — Quick wins (do first; low risk, fixes live bugs, shrinks god files)

These collapse duplication that all six reviewers flagged. **Only touch the live
consumers** (`hub.py`, `hub/forge_testbench/`, `hub/diagnostics.py`) — leave the
dying legacy copies alone.

1. **Create `hub/mcp_client.py`** — one `devforge_call(tool, args)` and
   `godot_ai_call(tool, args)` (open session → call → parse JSON). Repoint the
   live callers. *Smoke: `/api/status` chain-health still green.*
2. **Use `forge_env.read_env` everywhere.** **Bug fix:**
   `hub/forge_testbench/runner.py` reimplements it with a naive quote-strip that
   mangles single-quoted JSON values — delete that copy, import the real one.
   *Smoke: a testbench run reads `enable_thinking` correctly.*
3. **One shell helper.** Consolidate `_sh` / `_run_capture` /
   `forge_ops.run_cmd_capture` into one (keep the ANSI-strip + correct `stderr`).
   **Bug fix:** the stderr divergence currently loses error messages.
4. **Extract the job-runner block** (`hub.py`, repeated 11×: lock → job dict →
   spawn task → release) into `_start_job(label, action_fn)`. *Smoke: `/api/swap`
   still streams + releases the lock.*
5. **Kill silent feature-disabling:** replace `_HAS_SPATIAL` / `_HAS_GOVERNANCE`
   try/except booleans with a single explicit init that fails loudly.
6. **Trim `engine/.../platform/monitor/__init__.py`** (502 lines → move body to a
   module, keep `__init__` a re-export). Delete dead stub
   `incremental_context_builder.py`.

## Phase 1 — Engine god files (unblocked; mechanical extraction)

**A. `engine/devforge/execution/godot_ai_mcp.py` (1076)** → rename to
`godot_ai_executor.py`; extract `mcp_session.py` (session/circuit-breaker),
`op_translator.py` (pure op→command translation + result parsing). Class keeps the
`Executor` interface. *Smoke: `get_scene()` + an `execute` of "add a red cube".*

**B. `engine/.../compilation/pipeline/engine.py` (1444)** → rename to
`pipeline_orchestrator.py`; move `PipelineResult`/`GateResult` to `result.py`;
lift the 9 `_run_*_path` methods into a `planner_routing.py` (collapse the 7 thin
spatial wrappers into a **dict dispatch**); move delete/rename intent + entity
recovery into `post_planner.py`; keep `run_pipeline` as a thin composer. *Smoke:
gauntlet "add a red cube" + one spatial prompt (e.g. a small room) on one model.*

**C. `engine/.../platform/mcp_server.py` (2143)** → thin server (`_init`, lock,
`__main__`) + tools grouped by concern into `platform/tools/*.py`
(`pipeline_tools`, `scene_tools`, `lore_tools`, `dev_tools`, `monitoring_tools`),
each exposing `register_tools(mcp, ctx)`. **Highest API risk** — tool names must
not drift. *Smoke: MCP registration loads; `apply_spec` runs end-to-end.*

## Phase 2 — `hub/hub.py` (1940) — GATED on legacy deletion

`hub.py` imports and serves routes for the dying legacy runners. **Do not split
until those are deleted** (the `forge_testbench` migration, see
`TESTBENCH-MIGRATION-HANDOFF.md`). Then split into FastAPI `APIRouter` files
(`routes_status`, `routes_models`, `routes_config`, `routes_testbench`,
`routes_persona`, …) + a slim app keeping the job system and shared helpers.
*Smoke: every endpoint group responds after the move.*

## Open owner decision (blocks Phase 2)
**Legacy cutover:** once `forge_testbench` reaches parity — (a) hard-delete the
legacy routes, or (b) keep a deprecated `_legacy_routes.py` shim for a while?
Recommended: **(a) hard cut** — the goal is less surface. Record as ADR-005.

## Navigation aids to add alongside (cheap, owner-side relief)
- `docs/current/CODE-ARCHITECTURE.md` — one page mapping each key file → its job.
- Link `FORGE-STACK.md` from the root `README.md`; add per-package `__init__.py`
  re-exports and a short `engine/README.md` (notes the `devforge` fossil name).
