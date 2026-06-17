# Layer-3 Code-Health Review — Mimo (mimo-v2.5-pro)

**Date:** 2026-06-17  
**Tasks answered:** 1, 2, 3 (all three)

---

## Task 1 — Architecture + god-file splits

### Recommended architecture

**Four-box model, described in one sentence each:**

1. **Hub** (`hub/`) — the ops panel. A FastAPI web app that starts/stops services, swaps models, runs tests, and shows health. It orchestrates; it never contains pipeline logic.
2. **Engine** (`engine/devforge/`) — the generation brain. Takes a prompt, plans a scene, compiles operations, executes them in Godot. Lives behind an MCP boundary (port 8001) — the hub calls it over the network, not by importing it.
3. **Bridge** (`godot-ai`, port 8000) — translates between MCP calls and the live Godot editor. The engine calls it to read/write scenes.
4. **Test system** (`hub/forge_testbench/` + supporting scripts) — measures everything: probes, scenarios, gauntlet runs, shootouts. Talks to the engine and bridge over MCP, same as the hub.

The data flow is linear: **User → Hub → Engine → Bridge → Godot** (with llama.cpp sitting beside the engine for LLM inference). This is already how the code works. The key rule: **each box talks to the next box over a network boundary, never by importing its Python modules.**

### Where the code follows it vs. muddies it

**Follows it well:**
- `hub/forge_env.py`, `hub/forge_models.py`, `hub/forge_ops.py` — clean hub-only support modules with focused responsibilities. The hub never imports engine code. `forge_env.py:60` `read_env()` is the single source of truth for `stack.env`.
- `engine/devforge/execution/godot_ai_mcp.py` — the executor talks to godot-ai over MCP, never by importing it. Clean boundary.
- `engine/devforge/compilation/pipeline/` — well-decomposed pipeline stages (context assembler, planner, compiler, validator, repair engine) imported by the pipeline engine.
- `hub/forge_testbench/` — clean new test system with good separation: `test.py` (interface), `runner.py` (execution), `result.py` (data shape), `reporting.py` (rendering), `catalog.py` (registry). Tests receive a `Context` dataclass and never touch global state (`context.py:16`).
- `hub/forge_ops.py:94` `record_action()` — durable action log with failure classification, cleanly separated from the routes that call it.

**Muddies it:**
- `hub/hub.py` is a 1,940-line god file that contains **all** route definitions, chain-health checks, Odysseus integration, mode toggling, persona management, embedding status, config operations, bench/probe/scenario/shootout/gauntlet orchestration, screenshot proxying, tool-call probes, thinking toggle, stability analysis, and unified run aggregation — all in one file. The hub's "orchestrate, don't contain logic" rule is stretched thin.
- `engine/devforge/platform/mcp_server.py` (2,143 lines) mixes three concerns: MCP server setup, lazy initialization of all shared state, and **30+ tool registrations** that contain real business logic (e.g., `apply_spec` at line 108 does scene-store flow control, replanning, and execution — that's pipeline orchestration, not MCP plumbing).
- `hub/bench.py` (1,534 lines, legacy) contains `_godot_ai_call()` at line 79, `_probe_scene_reset()` at line 713, and `read_env()` at line 39 — three functions that are copy-pasted into `scenarios.py`, `shootout.py`, `gauntlet.py`, and `forge_testbench/runner.py`. The hub violates its own "hub shells out to `stack`" rule by directly reimplementing MCP client helpers.
- `hub/diagnostics.py:37` imports directly from `bench.py`: `from bench import read_env, _devforge_call, _probe_scene_reset, _scene_paths`. This creates a hard coupling between a diagnostic script and a legacy test runner.

### God-file split plan

#### 1. `hub/hub.py` (1,940 lines) → 4 modules

| Target module | Responsibility | Key lines to move |
|---|---|---|
| `hub/routes_status.py` | Status, chain-health, selfcheck, version, config, backups, logs, doc | Lines 178–428 (status, config, logs, doc endpoints) |
| `hub/routes_test.py` | Bench, probes, scenarios, shootout, gauntlet, tools, scorecards, unified runs, stability | Lines 830–1580 (all `/api/bench/*`, `/api/scenarios/*`, `/api/shootout/*`, `/api/gauntlet/*`, `/api/tools/*`, `/api/runs/*`, `/api/scorecards/*`) |
| `hub/routes_ops.py` | Swap, reconcile, mode toggle, persona, embedding, warmup, thinking, screenshots | Lines 238–830 (swap, models, mode, persona, thinking endpoints) |
| `hub/hub.py` (slim) | App factory, middleware, job runner, shared helpers (`_run_capture`, `_job_runner`, `_job_lock`) | Lines 1–175 + import wiring |

**Why this order:** Routes are the clearest seam — each group is self-contained (its own endpoints, no shared mutable state except `_job_lock` and `_jobs`). The slim `hub.py` keeps the FastAPI app + job infrastructure. Risk: lowest — each new file is pure extraction, no logic changes.

**Safe order:** `routes_status.py` first (read-only, simplest), then `routes_ops.py` (mutable but isolated), then `routes_test.py` (largest but most self-contained).

#### 2. `engine/devforge/platform/mcp_server.py` (2,143 lines) → 3 modules

| Target module | Responsibility | Key sections |
|---|---|---|
| `engine/devforge/platform/server_init.py` | `_init()`, shared state (`_engine`, `_executor`, `_scene_store`, etc.), pipeline lock | Lines 52–160 (lazy init, lock, shared objects) |
| `engine/devforge/platform/tools_scene.py` | Scene tools: `apply_spec`, `validate_spec`, `get_scene`, `audit_scene`, `batch_preview`, `batch_apply` | Lines 108–640 (the core scene mutation tools) |
| `engine/devforge/platform/mcp_server.py` (slim) | MCP server creation, remaining tool registrations (lore, journal, quest, perf, lint, polish, search, scaffold, sim, signal, smoke, companion, dialogue, template, refactor) | Lines 1–107 + lines 640–2143 |

**Why this order:** The scene tools are the high-risk, high-complexity core (they call `_engine.run_pipeline`, `_executor.execute`, manage replanning). Extracting them first isolates the hardest logic. The remaining tools are simpler and follow a uniform pattern: `_init()` → call a subsystem → `_journal.append()` → return dict.

**Safe order:** `server_init.py` first (just moving global state + `_init()`), then `tools_scene.py` (the core tools), then slim `mcp_server.py` stays with remaining registrations.

#### 3. `engine/devforge/compilation/pipeline/engine.py` (1,444 lines) → 3 modules

| Target module | Responsibility | Key sections |
|---|---|---|
| `engine/devforge/compilation/pipeline/planner_routing.py` | All `_run_*_path` methods (arch, ops, layout, building, scatter, ssp, room, wfc, voronoi) + `_run_spatial_path` factory | Lines 530–1444 (9 path methods + spatial factory) |
| `engine/devforge/compilation/pipeline/pipeline_result.py` | `PipelineResult` dataclass, `GateResult` dataclass | Lines 50–90 (dataclasses) |
| `engine/devforge/compilation/pipeline/engine.py` (slim) | `PipelineEngine.__init__`, `run_pipeline`, `validate_pipeline`, governance gates, helpers | Lines 1–530 minus dataclasses |

**Why this order:** The 9 `_run_*_path` methods are already well-isolated (they only depend on `self._llm`, `self._config`, planner instances, and `_generator`). The `_run_spatial_path` factory at line 780 already consolidates the spatial paths — extracting the whole group is mechanical. `PipelineResult`/`GateResult` are pure data classes with no behavior.

**Safe order:** `pipeline_result.py` first (zero risk — just moving dataclasses), then `planner_routing.py` (moving self-contained methods), then slim `engine.py`.

#### 4. `engine/devforge/execution/godot_ai_mcp.py` (1,076 lines) → 2 modules

| Target module | Responsibility | Key sections |
|---|---|---|
| `engine/devforge/execution/mcp_session.py` | Persistent MCP session management: `_ensure_session`, `_close_session`, `_call_tool_safe`, circuit breaker, `_run` dispatch, `shutdown` | Lines 70–360 (session lifecycle + circuit breaker) |
| `engine/devforge/execution/godot_ai_mcp.py` (slim) | `GodotAIMCPExecutor` class with all `Executor` interface methods + async internals + op translation + result parsing | Lines 1–70 + lines 360–1076 |

**Why this order:** The session management (persistent connection, circuit breaker, reconnect, background event loop) is a self-contained concern. It's already behind clean boundaries (`_ensure_session` returns a session; `_run` dispatches coroutines). Extracting it makes the executor class purely about "what to call" rather than "how to connect."

**Safe order:** `mcp_session.py` first (session management is already encapsulated behind `_ensure_session` and `_run`), then slim the executor.

### What you're not asking that you should be

1. **The engine has 29+ top-level packages** (`sentinel/`, `refactorer/`, `companion/`, `simulator/`, `navigator/`, `mapper/`, `lore/`, `quests/`, `dialogue/`, `journal/`, `forge/`, etc.). Many are 1–3 files. This is a flat namespace explosion — a non-coder looking at `engine/devforge/` sees 29 folders and has no idea which ones matter. Consider grouping into 5–6 top-level packages: `core/` (compilation, execution, platform), `knowledge/` (scene, system_graph, artifact_store), `tools/` (lint, polish, triage, audit, refactor, navigator, mapper, scaffold, sim, companion), `content/` (lore, quests, dialogue, templates), `infra/` (logger, config, llm, gateway), `spatial/` (keep as-is, already coherent).

2. **The legacy runners aren't just "scheduled for deletion" — they're actively leaking.** `diagnostics.py:37` imports from `bench.py`. `gauntlet.py` imports from `bench.py`. `shootout.py` imports from `bench.py`. Until the forge_testbench migration is complete, the `_godot_ai_call` / `read_env` / `_probe_scene_reset` helpers should be extracted into a shared hub utility so the legacy runners import from there instead of from each other.

3. **`hub/bench.py` reimplements `read_env()` at line 39** instead of importing from `forge_env.py`. So does `comprehensive_bench.py:77` and `multi_model_bench.py:71`. This is the exact duplication `forge_env.py` was created to prevent.

---

## Task 2 — Conventions guide

### File & function length (+ offenders with line counts)

**Rule: Files should be under 500 lines. Functions should be under 80 lines.**

Rationale: A non-coder can hold a 500-line file in their head. Beyond that, files need splitting. A function over 80 lines is doing more than one thing.

**Current offenders (files):**

| Lines | File | Status |
|-------|------|--------|
| 2,143 | `engine/devforge/platform/mcp_server.py` | 4× over limit — god file, needs splitting |
| 1,940 | `hub/hub.py` | 4× over limit — god file, needs splitting |
| 1,534 | `hub/bench.py` | Legacy — scheduled for deletion |
| 1,444 | `engine/devforge/compilation/pipeline/engine.py` | 3× over limit — needs splitting |
| 1,277 | `hub/shootout.py` | Legacy — scheduled for deletion |
| 1,116 | `hub/scenarios.py` | Legacy — scheduled for deletion |
| 1,076 | `engine/devforge/execution/godot_ai_mcp.py` | 2× over limit — needs splitting |
| 1,032 | `hub/gauntlet.py` | Legacy — scheduled for deletion |
| 882 | `engine/devforge/compilation/pipeline/architecture_compiler.py` | Over limit — consider splitting compiler from semantic checks |
| 502 | `engine/devforge/platform/monitor/__init__.py` | Over limit — `__init__.py` should be tiny |

**Files that respect the limit well (examples):**
- `hub/forge_env.py` (189 lines) — perfect
- `hub/forge_score.py` (74 lines) — perfect
- `hub/forge_testbench/test.py` (78 lines) — perfect
- `hub/forge_testbench/metric.py` (74 lines) — perfect
- `hub/forge_testbench/context.py` (99 lines) — perfect
- `hub/forge_testbench/catalog.py` (83 lines) — perfect
- `engine/devforge/execution/interface.py` (clean interface) — perfect

**Current offenders (functions):**

| Lines | Function | File:line |
|-------|----------|-----------|
| ~260 | `chain_health()` | `hub/hub.py:534` |
| ~200 | `run_pipeline()` | `engine/devforge/compilation/pipeline/engine.py:182` |
| ~200 | `_apply_spec_impl()` | `engine/devforge/platform/mcp_server.py:161` |
| ~180 | `api_runs_stability()` | `hub/hub.py:1488` |
| ~170 | `_execute_async()` | `engine/devforge/execution/godot_ai_mcp.py:398` |
| ~170 | `api_mode()` | `hub/hub.py:1640` |
| ~150 | `_run_arch_path()` | `engine/devforge/compilation/pipeline/engine.py:580` |
| ~140 | `run()` (Runner) | `hub/forge_testbench/runner.py:108` |

### Duplication to collapse (real path:line examples)

**1. `_godot_ai_call` — MCP client helper copy-pasted 3 times**

The exact same function (open MCP session, call tool, parse JSON result) appears in:
- `hub/bench.py:79`
- `hub/scenarios.py:65`
- `hub/forge_testbench/runner.py:79`

**Fix:** Extract into `hub/mcp_helpers.py`. All three import from there.

**2. `_runner` job pattern in hub.py — repeated 11 times**

Every long-running endpoint in `hub.py` repeats this exact pattern:
```python
job_id = uuid.uuid4().hex[:12]
job = {"lines": [...], "done": False, "exit": None, "t": time.time()}
_jobs[job_id] = job
async def _runner():
    try:
        ...
    except Exception as e:
        job["lines"].append(f"[...] crashed: {e}")
        job["exit"] = 1
    finally:
        job["done"] = True
        _job_lock.release()
asyncio.get_running_loop().create_task(_runner())
return {"job": job_id}
```

Found at `hub/hub.py`: lines 224, 262, 436, 857, 914, 984, 1063, 1154, 1353, 1660, 1859.

**Fix:** Create a `run_background_job(app, lock, jobs, action_fn)` helper that encapsulates the job creation + lock + task spawn. Each endpoint passes only its `action_fn`.

**3. `import json as _json` — re-imported mid-file 10 times in hub.py**

`hub/hub.py` imports `json` at the top (line 28), then re-imports it as `_json` inside 10+ route functions (lines 321, 947, 1108, 1215, 1256, 1276, 1412, 1488, 1685, 1808). This is a leftover from when these were copy-pasted.

**Fix:** Remove all `import json as _json` mid-file imports. Use the top-level `json` import.

**4. `_scene_reset` / probe scene management — duplicated 2+ times**

- `hub/bench.py:713` `_probe_scene_reset()`
- `hub/forge_testbench/runner.py:96` `_scene_reset()`

Both do the same "bounce trick" (open a different scene, then open probe.tscn, verify root, clean non-baseline nodes).

**Fix:** Extract into `hub/mcp_helpers.py` alongside `_godot_ai_call`.

**5. `_read_env()` reimplemented in legacy runners instead of using `forge_env.py`**

- `hub/bench.py:39` — reimplements `read_env()` (same logic as `forge_env.py:60`)
- `hub/comprehensive_bench.py:77` — reimplements again
- `hub/multi_model_bench.py:71` — reimplements again
- `hub/forge_testbench/runner.py:36` — reimplements again

**Fix:** All should `from forge_env import read_env`. The runner at `forge_testbench/runner.py:36` should use the shared one too.

**6. `swap_model` duplicated in `harness.py` and `forge_testbench/runner.py`**

- `hub/harness.py:76` `swap_model()` — wraps `forge_ops.swap_model` with emit
- `hub/forge_testbench/runner.py:92` `_swap_model()` — same wrapper

**Fix:** One shared `swap_with_emit(alias, emit)` in `forge_ops.py` or `hub/mcp_helpers.py`.

### Naming convention (+ fossil names to fix)

**Convention: `snake_case` everywhere. Files named for their single responsibility. Classes in `PascalCase`.**

| Current name | Problem | Suggested fix |
|---|---|---|
| `hub/bench.py` | "bench" is vague — it's really a test runner + MCP helpers + scene management | Split into `hub/mcp_helpers.py` (shared helpers) + delete legacy bench tests |
| `hub/diagnostics.py` | Runs diagnostic tests but also imports bench helpers | Keep for now (legacy); ensure new diagnostics go in forge_testbench |
| `hub/comprehensive_bench.py` | Legacy runner | Delete (per migration plan) |
| `hub/multi_model_bench.py` | Legacy runner | Delete (per migration plan) |
| `engine/devforge/platform/monitor/__init__.py` | 502 lines in `__init__.py` — should be in `monitor.py` | Move content to `monitor.py`, make `__init__.py` a re-export |
| `engine/devforge/compilation/pipeline/incremental_context_builder.py` | Deprecated stub (Round 4) | Delete |
| `engine/devforge/reasoning/ai/planning/lru_cache.py` | Duplicated in `engine/devforge/reasoning/ai/planning/` and referenced from `pipeline/engine.py` | Ensure single canonical location |
| `_runner` (local function in hub.py) | Used 11 times as a local function name — meaningless | Rename to `_run_{action}` (e.g., `_run_bench_tests`, `_run_swap`) or extract to shared helper |

### Minimal loose rules (each + one-line rationale)

1. **Every file starts with a one-line docstring saying what it does.** A non-coder scanning filenames needs confirmation they're in the right place. (Already followed by `forge_env.py`, `forge_score.py`, `forge_models.py`, `forge_ops.py` — just enforce it everywhere.)

2. **No file over 500 lines; no function over 80 lines.** The point where a non-coder loses the thread. Split at the natural seams identified above.

3. **One `read_env()` implementation, imported everywhere.** Eliminates the class of bug where different files parse `stack.env` differently. `forge_env.py` already exists — use it.

4. **Shared helpers live in `hub/mcp_helpers.py`, not inside test runners.** `_godot_ai_call`, `_scene_reset`, `swap_with_emit` belong in one place so the forge_testbench doesn't depend on legacy runners.

5. **New tools/functions go in the existing module that matches their concern.** Before creating a new file or package, check if there's already one for that concern. (The engine has 29+ packages — some could be merged.)

6. **No mid-file imports except for lazy/conditional loading.** `import json as _json` inside a function body is a smell. Import at the top; the only exception is import-time side-effect avoidance or optional dependencies.

### What you're not asking that you should be

1. **How long until the legacy runners are actually deleted?** They're marked "scheduled for deletion" but `diagnostics.py`, `gauntlet.py`, `shootout.py`, and `scenarios.py` are still imported by `hub.py` (lines 52–54) and actively used by hub routes. The migration to forge_testbench won't be complete until the hub routes call forge_testbench instead.

2. **Should the engine's 29 packages be reorganized?** A non-coder looking at `engine/devforge/` sees `sentinel/`, `refactorer/`, `companion/`, `simulator/`, `navigator/`, `mapper/`, `lore/`, `quests/`, `dialogue/`, `journal/`, `forge/`, `patch/`, `components/`, `triage/`, `patterns/`, `runner/`, `governance/`, `operations/`, `lint/`, `polish/`, `harness/`, `validation/`, `auditing/`, `transaction/`, `knowledge/`, `spatial/`, `compilation/`, `execution/`, `platform/`, `infrastructure/`, `world_model/`, `reasoning/`. That's 32 directories. Grouping into 5–6 top-level concerns would cut navigation time dramatically.

---

## Task 3 — Review & navigation environment

### Structural signals

**What already works well:**
- `docs/current/FORGE-STACK.md` — excellent single entry point with ASCII diagram, port table, operations guide. A non-coder can understand the whole system from this one file.
- `docs/current/ROADMAP.md` — clear status legend (✅/🔨⬜), phased plan with exit criteria.
- `hub/forge_testbench/` — the new test system has clean module docstrings explaining each file's role (e.g., `test.py:1`: "Test plug-in interface..."). This is the gold standard.
- `engine/devforge/CHANGES.md` — comprehensive bug audit trail. Every bug has ID, finding, file, fix, difficulty. A non-coder can follow the narrative.
- `hub/forge_env.py:1-16` — perfect module docstring: says what it does, who uses it, lists the public API.
- `hub/forge_ops.py:1-17` — same pattern: purpose, public API, design notes.

**What needs improvement:**
- `engine/devforge/platform/mcp_server.py` has no module-level comment explaining "this is the MCP entry point — 30 tools registered here." A non-coder opening this 2,143-line file has no map.
- `hub/hub.py` has a good top docstring (lines 1–17) but no section markers for the 50+ route groups. Adding `# ── Status routes ──`, `# ── Test routes ──`, etc. would make scanning possible.
- `engine/devforge/compilation/pipeline/engine.py:1-10` has a good docstring but the 9 planner paths (`_run_arch_path`, `_run_layout_path`, `_run_building_path`, etc.) are not labeled with section markers.
- No `docs/current/ARCHITECTURE.md` exists — the FORGE-STACK.md covers operations but not code structure. A non-coder needs a "which file does what" index.

**Recommendations:**

1. **Add a `docs/current/ARCHITECTURE.md`** — a one-page map of the codebase. For each directory, one line saying what it does and which files matter. Update it when files split. Cost: 30 minutes to write; saves hours per review session.

2. **Add section markers to god files** (before they're split). In `hub/hub.py`, add `# ── Status routes ──`, `# ── Test routes ──`, `# ── Ops routes ──` section comments. In `mcp_server.py`, add `# ── Scene tools ──`, `# ── Content tools ──`, `# ── Analysis tools ──`. Cost: 10 minutes per file.

3. **Every new module gets a 3-line docstring**: what it does, who calls it, public API. Follow the `forge_env.py` / `forge_ops.py` pattern. Enforce in review.

### Reviewable diffs for a non-coder

**The problem:** A non-coder reviewing a PR that touches `engine.py` or `mcp_server.py` sees a wall of green/red lines and has no idea what changed or why.

**Recommendations:**

1. **Small PRs, one concern each.** A PR that splits `hub.py` into 4 files is reviewable ("I see routes_status.py was extracted — that's the status endpoints"). A PR that splits + refactors + adds features is not.

2. **PR description template with a "what changed and why" section.** Force every PR to answer: (a) what was wrong/missing, (b) what was done, (c) how to verify. The `CHANGES.md` format (ID, finding, fix, difficulty) is a good model.

3. **Diff-friendly conventions:** Avoid reformatting existing code in the same PR as logic changes. A non-coder can't tell "this line was reformatted" from "this line was changed."

4. **The forge_testbench result shape (`result.py`, `metric.py`) is a good model for reviewability.** Every number has a unit and a `higher_is_better` flag. A non-coder can check: "the score went from 77 to 55, and `higher_is_better=True`, so that's a regression." No code reading required.

### Automated guardrails (most relief per setup)

**Highest-value, lowest-burden tools (recommended in priority order):**

1. **Ruff** (Python linter + formatter) — replaces flake8, isort, black, and pycodestyle in one tool. Zero config needed for a Python project. Enforces: line length (100 chars), unused imports, naming conventions, import order. Setup: `pip install ruff`, add `ruff check --fix` and `ruff format` to a pre-commit hook or CI. **Effort: 15 minutes to set up. Ongoing: zero (runs automatically).**

2. **File-length check** — a simple script that fails if any `.py` file exceeds 500 lines. Can be a 10-line shell script in `.github/workflows/` or a Ruff per-file-ignores rule. **Effort: 10 minutes. Catches the god-file problem before it grows back.**

3. **`ruff check --select I`** (import sorting) — catches the `import json as _json` mid-file pattern and enforces all imports at the top. **Effort: included in Ruff setup above.**

4. **pytest with coverage** — already in use (`hub/tests/`). Ensure `forge_testbench/tests/` is also wired up. The existing test suite is solid (133 hub tests, 318 engine tests). **Effort: already done. Just ensure new code has tests.**

**What NOT to add (over-engineering for this project):**
- Type checking (mypy/pyright) — the codebase uses type hints but inconsistently. Enforcing them would require a large cleanup pass. Not worth it for a solo non-coder project.
- Complex CI pipelines — the owner can't babysit them. A single `ruff check` + `pytest` step is enough.
- Pre-commit hooks that require manual setup per developer — the owner is the only developer. A CI check is sufficient.

### What you're not asking that you should be

1. **How does the owner currently review changes?** If they're using `git diff` and reading raw code, the biggest win is a PR template that forces "what/why/how to verify" sections. If they're using the hub's UI, the biggest win is surfacing test results and score changes in the UI itself.

2. **Should there be a "docs bot" that auto-updates ARCHITECTURE.md when files change?** For a solo project, probably not — but a quarterly manual review (15 minutes) where the owner checks "does this doc still match reality?" would catch drift.

3. **The `engine/devforge/` has a `doctor.py` (line 417) and a `health_check.py`** — are these discoverable? A non-coder should be able to run `python -m devforge.doctor` and get a pass/fail report. Make sure the README says this.

---

## Cross-cutting / anything else

1. **The forge_testbench is the best code in the repo.** Clean separation, self-describing metrics, plugin architecture, dependency injection via `Context`. It should be the model for all new code. The question is: when does the migration from legacy runners complete?

2. **The engine's spatial subsystem is well-architected.** 7 planners (layout, building, scatter, SSP, WFC, Voronoi, room intent) all share `_run_spatial_path()` as a factory. This is exactly the right pattern — parameterized variation, not copy-paste. The `_run_spatial_path` factory at `engine.py:780` is one of the cleanest abstractions in the codebase.

3. **Bug tracking is excellent.** `CHANGES.md` with 53 bugs across 10 rounds, each with ID/finding/file/fix/difficulty. This is the gold standard for a project maintained by AI assistants — every fix is documented so future AI sessions don't regress.

4. **The `hub/` helper modules (`forge_env.py`, `forge_models.py`, `forge_ops.py`, `forge_score.py`) are well-factored.** Each is under 500 lines, has a clear docstring listing its public API, and serves a single purpose. They should be the template for splitting the god files.

5. **Watch out for the "29 packages" problem in the engine.** Each package was created for a workorder by an AI assistant. Some are single-file modules that could be merged (e.g., `dialogue/`, `quests/`, `lore/` are all "content validation" concerns). The owner should decide: keep the fine-grained packages (good for AI navigation, bad for human overview) or consolidate (good for human overview, requires renaming imports).
