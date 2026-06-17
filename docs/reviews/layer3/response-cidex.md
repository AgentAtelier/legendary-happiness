# Layer-3 Code-Health Review — Codebuff (cidex)
June 17, 2026 — Tasks 1, 2, and 3

## Task 1 — Architecture + god-file splits

### Recommended architecture

**The "Pipeline + Registry" pattern.** The project has three natural layers that a non-programmer can hold in their head:

1. **Orchestration Layer** (`hub/`) — a FastAPI web UI that talks to the stack CLIs, never reimplements their logic. Think of it as a remote control: press a button, it shells out.
2. **Pipeline Layer** (`engine/devforge/`) — the generation engine. Natural-language prompt goes in → validated Godot scene operations come out. Inside it has a linear chain: context assembly → planning → compilation → operation generation → completeness → validation → repair → execution. Each step is a module.
3. **Execution Layer** — the MCP boundary. DevForge talks to two servers over MCP: `godot-ai` (editor bridge) and `llama.cpp` (LLM). Neither is "our code" — they're upstream services we call.

**The code follows this pattern** where it matters: `hub/hub.py` shells out to `stack` and `forge-model`, never parsing stack.env logic directly (that's in `forge_env.py`). The pipeline in `engine.py` chains named phases (Phase 1: context → Phase 2: planning → etc.) with clean `@dataclass PipelineResult` output.

**Where it muddies it:** The four god files below violate the separation. `mcp_server.py` imports from nearly every subsystem (spatial, lore, quests, sentinel, lint, companion, dialogue, refactorer, templates — 25+ import lines) and registers 20+ MCP tools, turning it into a monolith that knows about everything. `hub/hub.py` mixes routing logic, job management, chain-health checks, test orchestration, and config editing into one file. `engine.py` has 8 different planner paths (arch → layout → building → scatter → ssp → wfc → voronoi → room) inlined via `if/elif/elif/...`. `godot_ai_mcp.py` mixes session management, operation translation, and all async internals.

### God-file split plan

**SAFETY RULE:** No god file should exist. A file at 500+ lines is a candidate for splitting. At 1000+ it's harming reviewability. The splits below target ~200-400 lines per module, which is readable for an AI to maintain and a non-coder to navigate.

---

**1. `engine/devforge/platform/mcp_server.py` (~2150 lines)**

*Risk: Medium. Tools are independently testable. Each split is a no-op refactor — just move registration + handler to another file and import it.*

Current structure: ~20 `@mcp.tool()` functions in one file + shared init + pipeline lock.

Proposed modules:

| Module | Responsibility | Line est. |
|--------|---------------|-----------|
| `mcp_server/__init__.py` | Server bootstrap, `_init()`, pipeline lock, imports `_engine`/`_executor` | ~80 |
| `mcp_server/tools_core.py` | `apply_spec`, `validate_spec`, `get_scene` — the 3 core pipeline tools | ~200 |
| `mcp_server/tools_diagnostics.py` | `audit_scene`, `triage_errors`, `lint_content`, `polish_pass`, `batch_preview`, `batch_apply` | ~300 |
| `mcp_server/tools_data.py` | `lore_schema_list`, `lore_data_validate`, `lore_integrity_check`, `quest_validate`, `dialogue_validate`, `template_*`, `test_scaffold` | ~400 |
| `mcp_server/tools_monitoring.py` | `perf_sample`, `perf_history`, `journal_entries`, `journal_summary`, `project_search`, `smoke_run`, `scene_extract`, `scene_list_extractable`, `signal_map`, `balance_sim`, `design_companion` | ~400 |
| `mcp_server/tools_readonly.py` | `read_artifact` and any remaining read-only tools | ~80 |

**Safe order:** tools_core → tools_diagnostics → tools_data → tools_monitoring → tools_readonly (highest churn first, least disruptive last).

---

**2. `hub/hub.py` (~1940 lines)**

*Risk: Medium. The job-runner pattern is the most entangled; routes are independent but share `_jobs` / `_job_lock` / `_run_capture`.*

Current structure: ~40+ route handlers + 3 helper functions + job system + chain health.

Proposed modules:

| Module | Responsibility | Line est. |
|--------|---------------|-----------|
| `hub/app.py` | FastAPI app creation, middleware, `_run_capture`, job system (`_jobs`, `_job_lock`, `_job_runner`), main entry | ~150 |
| `hub/routes_status.py` | `/`, `/api/status`, `/api/chain-health`, `/api/version`, `/api/selfcheck`, `/api/job/active` | ~300 |
| `hub/routes_models.py` | `/api/models`, `/api/models/search`, `/api/swap`, `/api/reconcile`, `/api/mode` | ~250 |
| `hub/routes_config.py` | `/api/config`, `/api/config/restore`, `/api/config/backups` | ~150 |
| `hub/routes_testing.py` | `/api/bench/*`, `/api/scenarios/*`, `/api/shootout/*`, `/api/gauntlet/*`, `/api/runs/*`, `/api/tools/*`, `/api/screenshot`, `/api/logs-read` | ~500 |
| `hub/routes_odysseus.py` | `/api/odysseus/*`, `/api/persona/*`, `/api/thinking/*`, `/api/actions` | ~250 |
| `hub/routes_random.py` | `/api/doc`, `/api/logs/*` + one-off endpoints | ~100 |

**Safe order:** config → status → models → odysseus → testing (biggest, do last).

---

**3. `engine/devforge/compilation/pipeline/engine.py` (~1440 lines)**

*Risk: Low-Medium. The 8 planner paths already have individual methods, just inlined into one file. Extracting each into its own module is a pure move.*

Current structure: `_run_arch_path`, `_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_voronoi_path`, `_run_wfc_path`, `_run_room_path` + `_run_spatial_path` factory + `_run_ops_path` + `run_pipeline` orchestrator + `_run_governance_gates`.

Proposed modules:

| Module | Responsibility | Line est. |
|--------|---------------|-----------|
| `pipeline/engine.py` | `PipelineEngine` class: `run_pipeline`, `__init__`, `_normalize_scene`, `update_history`, `validate_pipeline`, `_dedupe_*` — the orchestrator + shared infrastructure | ~300 |
| `pipeline/paths/arch.py` | `_run_arch_path` — the default planner path | ~200 |
| `pipeline/paths/ops.py` | `_run_ops_path` — experimental direct-ops path | ~150 |
| `pipeline/paths/spatial.py` | `_run_spatial_path` factory + all spatial route methods | ~250 |
| `pipeline/governance.py` | `_run_governance_gates`, `GateResult` | ~100 |

**Safe order:** governance → paths/spatial (the factory, no net new code) → paths/arch → paths/ops → trim engine.py.

---

**4. `engine/devforge/execution/godot_ai_mcp.py` (~1080 lines)**

*Risk: Low. Session management, op translation, and executor interface are cleanly separable.*

Current structure: `GodotAIMCPExecutor` class with executor interface + persistent session management + async internals + op format translation + per-op fallback execution.

Proposed modules:

| Module | Responsibility | Line est. |
|--------|---------------|-----------|
| `execution/godot/executor.py` | `GodotAIMCPExecutor` class: executor interface methods (`execute`, `get_scene`, `read_logs`, `resolve_node_properties`, etc.) + `backend_name` | ~200 |
| `execution/godot/session.py` | `_ensure_session`, `_close_session`, circuit breaker, `_call_tool_safe`, `_record_mcp_failure`, background event-loop management | ~200 |
| `execution/godot/translate.py` | `_translate_ops_to_commands`, `_FIELD_MAP`, `_OP_TO_COMMAND`, `_res_path` | ~100 |
| `execution/godot/helpers.py` | `_execute_ops_individually`, `_normalize_op_result`, `_parse_tool_result`, `_parse_tool_result_text`, `_unwrap_scene_hierarchy`, `_tree_from_flat` | ~200 |
| `execution/godot/async_ops.py` | All `_async` methods (`_execute_async`, `_get_scene_async`, `_read_logs_async`, `_resolve_node_properties_async`, `_get_performance_monitors_async`, etc.) | ~300 |
| `execution/godot/__init__.py` | Re-exports `GodotAIMCPExecutor` | ~20 |

**Safe order:** translate → helpers → session → async_ops → executor (depends on all the above) → __init__.py.

### What you're not asking that you should be

**"Should we also split `bench.py` (the legacy runner) now, or wait?"** — It's marked for deletion with the testbench migration. Splitting it would be wasted effort. Document in a README that it's legacy and stop committing to it.

**"Who owns each new module?"** — With AI assistants writing all code, every split must also document the import boundary (what does this module import? what imports it?). Without that, an AI adding a feature doesn't know where to put it and creates a new god file.

---

## Task 2 — Conventions guide

### File & function length (+ offenders with line counts)

**File limit: 400 lines.** A file over 400 lines is a candidate for splitting. Exceptions: test fixtures (can be longer) and auto-generated files.

**Function limit: 80 lines.** A function over 80 lines should be broken into named sub-functions.

**Offenders (file level):**
- `engine/devforge/platform/mcp_server.py` — ~2150 lines (20+ tools in one file)
- `hub/hub.py` — ~1940 lines (40+ route handlers)
- `engine/devforge/compilation/pipeline/engine.py` — ~1440 lines (9 planner paths inlined)
- `engine/devforge/execution/godot_ai_mcp.py` — ~1080 lines (session + translation + executor mixed)
- `hub/bench.py` — ~1000 lines (legacy, marked for deletion — skip)
- `hub/scenarios.py` — ~930 lines (legacy, marked for deletion — skip)
- `hub/gauntlet.py` — ~900 lines (legacy, marked for deletion — skip)
- `hub/shootout.py` — ~880 lines (legacy, marked for deletion — skip)

**Offenders (function level):**
- `hub/hub.py:_apply_spec_impl` — ~120 lines (nested replan logic + executor dispatch)
- `hub/shootout.py:_test_one_model` — ~170 lines (swap + reset + apply + assertions in one function)
- `engine/devforge/compilation/pipeline/engine.py:run_pipeline` — ~130 lines (9 planner branches)
- `hub/bench.py:_probe_scene_reset` — ~120 lines with deep nesting

### Duplication to collapse (real path:line examples)

**1. MCP client connection boilerplate** — The same `_devforge_call` and `_godot_ai_call` pattern (SSE client → initialize → call_tool → JSON parse) appears in 3 places:
- `hub/bench.py:80-130` — `_godot_ai_call` and `_devforge_call`
- `hub/scenarios.py:70-130` — duplicate `_godot_ai_call` and `_devforge_call`
- `hub/forge_testbench/runner.py:50-110` — third copy of `_godot_ai_call` and `_devforge_call`

**Fix:** Move both to `hub/forge_env.py` or a new `hub/mcp_client.py` and import them. ~100 lines total → saved ~200 lines of duplication.

**2. `read_env()` function** — Parses `stack.env` with quote stripping:
- `hub/forge_env.py:50-75` — the canonical version
- `hub/bench.py:75-90` — duplicate (simpler version)
- `hub/scenarios.py:90-115` — duplicate WITH an import fallback

**Fix:** `bench.py` and `scenarios.py` should import `read_env` from `forge_env.py`. The import fallback in `scenarios.py` exists because it can run standalone — extract that fallback pattern into `forge_env.py` itself so every consumer benefits. ~50 lines of duplication.

**3. Probe scene helpers** — `_probe_scene_reset`, `_scene_paths`, `PROBE_SCENE`, `PROBE_EXPECTED`:
- `hub/bench.py:290-480` — ~190 lines of probe scene infrastructure
- `hub/forge_testbench/runner.py:60-240` — ~180 lines of duplicated probe scene infrastructure

**Fix:** Extract into `hub/probe_scene.py` as shared module. Both the legacy bench and the new testbench import from it. ~370 lines of near-identical logic.

**4. `_sh` shell helper** — Calls `create_subprocess_exec` with timeout:
- `hub/bench.py:45-55` — `_sh`
- `hub/harness.py:55-65` — `_sh` (legacy, skip)
- `hub/forge_testbench/runner.py:30-40` — `_sh`
- `hub/forge_ops.py:100-115` — `run_cmd_capture` (same thing, different name: one has `stdout=subprocess.PIPE` alone; the other passes `stderr=subprocess.STDOUT` too)

**Fix:** Consolidate into `forge_env.py` or `forge_ops.py`. The `stderr` difference is a subtle bug (error messages lost) — the consolidation would surface and fix it. ~40 lines per copy → ~80 lines saved.

### Naming convention (+ fossil names to fix)

**Convention:** `snake_case` for files, functions, and variables. `PascalCase` for classes and exceptions. Test file names: `test_<module>.py`.

**Current violations:**
- `hub/forge_models.py` — `_SCALARS` dict keys use `<` prefix format strings (internal, fine) but `KV_BYTES_PER_EL` and `FIT_SAFETY_MARGIN` are constants — should be `KV_BYTES_PER_EL` is actually already `UPPER_SNAKE` for module-level constants, so this part is fine.
- `hub/scenarios.py` — `_llama_chat_call()` (snake_case, fine) but `TOOL_CALL_PROBES` is `UPPER_CASE` (module-level list constant — this is correct).
- Actually, most naming is surprisingly consistent. The bigger issue is **misleading/fossil names:**

| Fossil name | Where | Why misleading | Fix |
|-------------|-------|---------------|-----|
| `engine/` directory | project root | The generation engine lives in `engine/devforge/`, not at `engine/` root. An AI looking for "the pipeline" sees `engine/devforge/compilation/pipeline/` but `engine/` also contains experiments, tests, docs, and `terraforge_project_meta` | No change yet (ADR 001 kept it). When you next refactor, rename `engine/` to `devforge/` flat at root. |
| `bench.py` | `hub/bench.py` | Implies a benchmark, but it's a 21-test diagnostic suite + probe mode. "Bench test" is an overloaded term in this codebase. | Keep it (marked for deletion). New name in testbench: `forge_testbench/tests/probes.py`. |
| `_test_*` methods in `_apply_spec_impl` | `engine/devforge/platform/mcp_server.py` | They're not tests — they're replan loops. | Rename to `_apply_spec_with_replan` or just inline. |

### Minimal loose rules (each + one-line rationale)

1. **"Files under 400 lines."** — A file above 400 lines is hard for an AI to read in one context window and hard for a non-coder to know what it does.
2. **"Functions under 80 lines."** — A function above 80 lines is doing too many things; the non-coder can't tell where one phase ends and another begins.
3. **"One class per file, one public function per file for utilities."** — This maps 1:1 to file names: `scene_doctor.py` has `SceneDoctor`, `forge_env.py` has `read_env`/`write_env`/`plan_env`. When a file has two classes in the title comment (like `result.py` has `Result` + `ScoredResult`), that's a smell to fix.
4. **"Groups of 3+ similar imports → a shared module."** — The MCP client duplication (Rule 7) is the prime example: if you write the same connection pattern 3 times, extract it.
5. **"No `import *`. Always named imports."** — AI assistants can't reason about wildcard imports and will miss name conflicts.
6. **"Docstrings on every module (`"""module docstring"""` first line) and every public class/function."** — The non-coder reads docstrings to understand what a file is for. `forge_testbench/` does this well; `hub/hub.py` and `mcp_server.py` have weak docstrings.

### What you're not asking that you should be

**"Which of these rules will I actually enforce a month from now?"** — Rules 1 (400-line limit) and 3 (one class per file) are the only ones that matter. The rest are nice-to-have. If you only enforce two conventions, enforce those. They have the highest payoff per unit of review burden.

---

## Task 3 — Review & navigation environment

### Structural signals

**What already works well:**
- `forge_testbench/` modules each have a clear one-line docstring explaining what they do. `metric.py`, `result.py`, `test.py`, `artifact.py` are self-explanatory.
- The `docs/INDEX.md` is a single jumping-off point. This pattern works — keep it.
- `forge_env.py`, `forge_models.py`, `forge_ops.py` are three focused "utility belt" files that hub consumers import from. This is the pattern to copy.

**What to add:**

1. **Module docstrings as table of contents.** Every `.py` file should start with a docstring that lists the public symbols it exports. `forge_testbench/test.py` does this well with its `Test` class docstring. `hub/hub.py` starts with a good design-rules block but does NOT list its routes — add a table.
2. **`__init__.py` that re-exports.** `forge_testbench/__init__.py` lists everything you can import from the package. Every package should do this. `engine/devforge/` packages have `__init__.py` files but many are empty or just `from .module import X`. A central re-export is better for AI navigation.
3. **A top-level `ARCHITECTURE.md`** (not buried in `docs/current/`). Put a one-paragraph file at the repo root that says: "Three layers: hub (web UI) → DevForge (generation pipeline) → MCP services (llama.cpp, godot-ai). Testbench tests everything. See docs/current/FORGE-STACK.md for details." Non-coders see it immediately when they open the repo.
4. **Consistent entry point naming.** Every MCP tool in `mcp_server.py` is `@mcp.tool()` above a `def`. Every FastAPI route in `hub.py` is `@app.get/post()` above a `def`. This is already consistent. Good. Keep it.

### Reviewable diffs for a non-coder

The owner cannot read code deeply. A diff is reviewable if it tells a story without reading every line.

**What helps:**
1. **One concern per diff.** A PR that renames a function AND adds a feature AND fixes a bug is impossible to review. Split it into 3 commits.
2. **Generated content is NOT in the diff.** `forge_models.py:scan` calls `detect()` which reads GGUF headers. A model file change does NOT appear in diffs because models are binary — the diff shows the scan function and that's reviewable.
3. **Test files as specification.** When a test is added/modified, the non-coder can see: "this test checks that a cube created is visible." The assertion labels (`"arena_exists"`, `"player_mesh"`) in `shootout.py:_run_static_assertions` are human-readable and make the diff reviewable.
4. **Avoid giant JSON/configuration diffs.** The gauntlet prompt sets in `hub/data/gauntlet/sets/*.json` could be hundreds of lines. The non-coder can't review those — move them to `docs/reviews/` with a summary of what changed.

**Mechanism to enforce:** There is none (willpower-based). But you can **reduce the need for review by making changes safer.** The `swap_model` function in `forge_ops.py` already does this — it's transactional with rollback. The `write_env` function preserves formatting. Every state-modifying function should be written like this: "can I undo this? If not, can I at least detect what changed?"

### Automated guardrails (most relief per setup)

**Highest payoff, lowest setup burden:**

1. **`ruff` as a formatter + linter.** `ruff format` enforces consistent formatting (single ground truth). `ruff check` with a small ruleset catches: unused imports, missing docstrings (with `D` rules), variable naming. Setup: one `pyproject.toml` block, one shell command. Burden: zero — `ruff format --check` in CI, `ruff format` locally.
    - **Rules to enable:** `F` (pyflakes errors), `I` (import sort), `D` (docstrings — just `D100`, `D103`, `D200`), `N` (naming — `N802` for lowercase function names).
    - **Rules to skip:** `E501` (line length — AI-generated code hits 120+ naturally), `C90` (complexity — over-engineers simple code).

2. **`204` (the Forge convention linter).** There's already a linter in `engine/devforge/lint/linter.py` — it's designed for Godot content files, not Python. Don't make it police Python conventions. Use `ruff` for Python and keep the existing linter for content.

3. **Git pre-commit hook for formatting.** `pre-commit install` with one hook: `ruff format --check`. Catches formatting before submit. The owner never babysits it.

4. **CI that runs tests on push.** The `.github/workflows/claude.yml` exists — but it runs Claude, not test scripts. Add a second workflow that runs:
    - `ruff format --check`
    - `cd hub && .venv/bin/python -m pytest tests/ -v` (the fast, isolated unit tests — not the live integration tests which need a real stack)
    - This catches import errors, naming violations, and logic bugs in ~30 seconds.

**What NOT to add (too much setup/burden for this owner):**
- `mypy` strict mode — too many false positives for an AI-generated codebase. The fast type-checking in existing code (e.g., `forge_testbench/test.py` uses annotated class fields, `result.py` uses `Literal` types) is already good.
- Full test coverage enforcement — impractical for a solo non-coder project. Focus on: "does it format?" and "do the isolated tests pass?"
- Package lockfile (`poetry.lock` / `Pipfile.lock`) — the project has two venvs and no dependency pinning. For a local-only toolchain this is fine; the cost of lockfile maintenance outweighs reproducibility benefit.

### What you're not asking that you should be

**"How do I know an AI didn't sneak a bad variable name or side effect into a 200-line change?"** — You can't read every line. You CAN ask the AI to summarize its changes in the commit message using a structured format: "Changed files: X, Y. New functions: foo() and bar(). Deleted: _old_thing(). Risk: medium (touches config path)." Make this a prompt you paste into the AI before it writes code.

---

## Cross-cutting / anything else

**The testbench migration is the right call — don't slow it down for this review.** The legacy runners (`bench.py`, `scenarios.py`, `gauntlet.py`, `shootout.py`, `harness.py`) contain good test content embedded in duplicative and hard-to-review runners. The `forge_testbench/` in `hub/` is the better pattern: each test is a plug-in, each file is <300 lines, each class has clear docstrings. The priority should be: finish the migration → delete the legacy files → THEN split the god files. Splitting the god files during the migration would create merge conflicts.

**The most impactful single change you can make right now**, measured in lines saved per hour of work: extract the shared MCP client helpers (`_devforge_call`, `_godot_ai_call`, `_sh`) into `hub/mcp_client.py`. It touches 3 files, eliminates ~200 lines of duplication, and every future test/module benefits. This is a 15-minute refactor for an AI that could save 30+ minutes of debugging per session because the "connection pattern" won't be wrong in one of three places.

**The review report that matters most is not this one — it's the diff.** A non-coder can't read a 200-line function, but they CAN read "changed `createEntity` to `_create_entity`" in a 3-line diff. The code review process should reward small diffs, not penalize them.
