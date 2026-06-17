# CHANGES.md — Complete Bug Fix Audit Trail

Every bug found and fixed across all DevForge hardening cycles, ordered chronologically.

---

## Round 1: Showstoppers (S1-S4)

Bugs that block the bundle from working at all.

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **S1** | `devforge/execution/__init__.py` references absent `godot_ai_mcp.py` | `execution/__init__.py` | Removed dead import; godot-ai bundler exclusion was catching DevForge's own file | hour |
| **S2** | `verify_pipeline.py` runs entire suite at import time; `tests/` empty | `verify_pipeline.py`, `tests/__init__.py` | Deferred test calls to `__main__` guard; added 4 test files | hour |
| **S3** | Grammar constraint off by default — `llama_grammar_path=""`, no `.gbnf` exists, `selftest_grammar()` orphaned | `runtime_config.py`, `godot_node_types.py` | Auto-generate `arch_planner_generated.gbnf` at startup from `godot_node_types.py` | hour |
| **S4** | `retry_prompt = prompt` instead of `planner_prompt` — first attempt gets unscrubbed prompt | `engine.py` | Changed to `retry_prompt = planner_prompt` | trivial |

---

## Round 2: High-Priority (H1-H7)

Bugs that cause incorrect behavior or silent failures in production.

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **H1** | Turn-ID thread race via shared `backend._turn_id` attribute | `llama_client.py` | Switched to `contextvars.ContextVar` — concurrent calls each get their own turn_id | hour |
| **H2** | ArtifactStore never evicts — unbounded memory growth | `artifact_store.py` | Added LRU eviction with cap=50 | hour |
| **H3** | Script extractor path traversal via `# path:` header | `script_extractor.py` | Path sanitization + content-hash filenames | hour |
| **H4** | Gateway budget: 300s expiry shorter than worst-case turn (runaway turns reset their own budget) | `gateway.py` | Default bucket (`__default__`), sliding expiry (`created_at` reset on every call), `GATEWAY_STRICT_BUDGET` env var | day |
| **H5** | Gateway 429 treated as retryable mystery (no distinct exception) | `gateway.py`, `llama_client.py`, `engine.py` | `BudgetExceededError(RuntimeError)` raised on 429; caught as terminal in retry loop | hour |
| **H6** | `allow_origins=["*"]` on a config-mutating API | `mcp_server.py`, `server.py` | CORS locked to localhost | trivial |
| **H7** | Dead code: `llm_retry.py` (zero callers), `worker.py` (zero callers) | `llm_retry.py`, `worker.py` | Deleted both files | trivial |

---

## Round 3: Medium-Priority (M1-M6)

Gaps that enable 2 a.m. production mysteries.

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **M1** | No config validation — typos silently fall through | `runtime_config.py` | Added `validate()` with 11 checks (backends, numeric ranges, sampler profiles); wired into `get_config()` | hour |
| **M2** | `requirements.txt` incomplete; no startup entry point | `requirements.txt`, `Procfile` | Added httpx, mcp, GitPython; created Procfile for Honcho/Foreman | hour |
| **M3** | No concurrent safety in `_apply_spec_impl` | `mcp_server.py` | `threading.Lock` around `_apply_spec_impl`, `_init()`, and `validate_spec` | hour |
| **M4** | `get_scene()` returns only scene data, no version | `mcp_server.py` | Now returns `{"scene": ..., "version": N}` | trivial |
| **M5** | No file logging; log levels not env-controlled | `logger.py` | Rotating file handler (`DEVFORGE_LOG_FILE`), env-controlled levels (`DEVFORGE_LOG_LEVEL`), structured JSON output | hour |
| **M6** | Dead subtrees: `simulation/`, `reasoning/evolution/`, `reasoning/autonomy/` | `experiments/` | Moved dead subtrees to `experiments/` directory | trivial |

---

## Round 3b: Test Coverage

| ID | File created | What it tests |
|----|-------------|---------------|
| **T1** | `tests/test_import_walk.py` | Import walk smoke test — catches import-time side effects |
| **T2** | `tests/test_gateway_budget.py` | Default bucket, sliding expiry, 429 handling |
| **T3** | `tests/test_artifact_store.py` | LRU eviction, reorder, summary |
| **T4** | `tests/test_script_extractor.py` | Traversal rejection, content-hash filenames |

---

## Round 4: Investigation Session — Pipeline Integration Bugs

Bugs discovered while trying to get the DevForge → godot-ai → Godot pipeline working end-to-end.

### Bug #1: GBNF Grammar Parse Failure (MEDIUM)

**Symptom:** llama.cpp logged `parse: error parsing grammar: expecting name at | system ... {0,15}`

**Root cause:** The `{0,15}` repetition range syntax in `arch_planner.gbnf` is not supported by all llama.cpp builds. The current build actually supports it, but older builds don't.

**Fix:** Changed `{0,15}` → `*` (zero-or-more) in both `system-list` and `entity-list` rules. Regenerated `arch_planner_generated.gbnf`.

**Files changed:**
- `devforge/reasoning/prompts/arch_planner.gbnf` — `{0,15}` → `*`
- `devforge/reasoning/prompts/arch_planner_generated.gbnf` — regenerated

**Difficulty:** trivial

---

### Bug #2: DevForge Cannot Connect to godot-ai MCP (HIGH — BLOCKER)

**Symptom:** `ConnectionError: Failed to establish MCP session to http://localhost:8000/mcp: unhandled errors in a TaskGroup (1 sub-exception)`

**Root cause (revised after investigation):** godot-ai uses **Streamable HTTP** (not SSE) for its MCP transport. The `GodotAIMCPExecutor` was using `sse_client()` from the `mcp` library, which tried to establish an SSE connection to a Streamable HTTP endpoint. The curl tests showed `{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}` — misleading because the actual fix isn't changing the header; it's changing the transport protocol.

**Fix:** Switched from `mcp.client.sse.sse_client` to `mcp.client.streamable_http.streamable_http_client`. Both are `@asynccontextmanager` — same `__aenter__`/`__aexit__` pattern, different import and return tuple (3 values: read, write, get_session_id instead of 2).

**Files changed:**
- `devforge/execution/godot_ai_mcp.py` — import change, context manager pattern adapted, `_sse_ctx` → `_transport_ctx`, docstrings updated
- `devforge/infrastructure/runtime_config.py` — URL defaults stayed at `/mcp` (correct for Streamable HTTP)

**Verified:** `_ensure_session()` connects to godot-ai and lists 40 tools successfully.

**Difficulty:** hour

---

### Bug #3: batch_execute Parameter Name Mismatch (HIGH — BLOCKER)

**Symptom:** `applied: 0` despite operations being generated and `batch_execute` returning "0 errors". Scene stays empty.

**Root cause:** godot-ai's `batch_execute` expects the parameter `commands` (list of `{"command": str, "params": dict}` objects) but DevForge was sending `operations` (list of flat `{"type": "add_node", ...}` objects). The parameter name AND format were both wrong.

**Fix:** Added `_translate_ops_to_commands()` static method that converts DevForge's flat operation format to godot-ai's nested command format:

```
DevForge: {"type": "add_node", "parent": "/root/Main", "node_type": "Camera3D", "name": "MainCam"}
godot-ai: {"command": "create_node", "params": {"parent_path": "/root/Main", "type": "Camera3D", "name": "MainCam"}}
```

Added class-level mapping tables: `_OP_TO_COMMAND`, `_FIELD_MAP`, `_DROP_FIELDS`.

**Files changed:** `devforge/execution/godot_ai_mcp.py` — translation layer + call site change

**Verified:** Translation produces correct godot-ai command format. `batch_execute` returns `succeeded: 1, status: "ok"`. Nodes appear in Godot scene via direct godot-ai query.

**Difficulty:** hour

---

### Bug #4: Tool Name Mismatches (MEDIUM)

**Symptom:** DevForge's `get_scene` returned empty results; file creation silently failed.

**Root cause:** Two tool names in `GodotAIMCPExecutor` didn't match godot-ai's actual tool names:
- `TOOL_SCENE_HIERARCHY = "godot://scene/hierarchy"` → actual tool is `"scene_get_hierarchy"`
- File creation called `"create_file"` → actual tool is `"script_create"`

These were silent failures — godot-ai returned error responses but DevForge didn't surface them clearly.

**Fix:** Changed both constant and inline string to match godot-ai's tool inventory.

**Files changed:** `devforge/execution/godot_ai_mcp.py`

**Difficulty:** trivial

---

### Bug #5: scene_get_hierarchy Response Format Mismatch (MEDIUM)

**Symptom:** After fixing the tool name, `get_scene` returned scene name/type but `children: []` even though direct godot-ai queries showed 6 children.

**Root cause:** godot-ai's `scene_get_hierarchy` wraps the tree in `{"root": {...}, "nodes": [...], "total_count": N, ...}` but DevForge expected the tree shape directly. The `root` key doesn't carry children in the current godot-ai version; `nodes[0]` does.

**Fix:** Added `_unwrap_scene_hierarchy()` static method that extracts `nodes[0]` (preferred, carries children) or falls back to `root`. Applied to both `_get_scene_async()` and `_execute_async`'s scene snapshot parsing.

**Files changed:** `devforge/execution/godot_ai_mcp.py`

**Difficulty:** trivial

---

## Round 5: Round-2 Audit Fixes (June 11, 2026 session)

Worked through `ROUND2-AUDIT-FINDINGS.md` (F1–F12) plus new defects found
while running the suite. Baseline at session start: 12/25 tests failing.
After this round: **all 8 suites in `scripts/run_all_tests.sh` pass**
(health_check, verify_pipeline, import walks ×2, gateway 8/8,
artifact store 8/8, script extractor 8/8, executor pytest 18/18).

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **F1** | `logger.warning()` crashes the path-rejection path (`DevForgeLogger` only has `warn`) | `script_extractor.py` | `logger.warning` → `logger.warn` | trivial |
| **F2** | `_sanitize_path()` never strips whitespace — `"   "` → `scripts/   .gd` | `script_extractor.py` | `raw.strip()` + reject empty before any other check | trivial |
| **F3** | Test expects `store.max_entries`, impl had `_max_entries` | `artifact_store.py` | Made `max_entries` public (matches ctor param) | trivial |
| **F5** | `requirements.txt` missing test/governance deps | `requirements.txt` | Added `pytest>=8.0.0`, `PyYAML>=6.0.0` (yaml was failing all of `devforge/governance/` at import) | trivial |
| **F7** | Config validation printed errors but kept running | `runtime_config.py` | `get_config()` now raises `ValueError` on invalid config (and doesn't cache the bad config, so a fixed env recovers) | hour |
| **F8** | Gateway tests called `_record_usage()` without `_check_budget()` — no entry, nothing recorded | `test_gateway_budget.py` | Tests now create the entry first, same as production handlers | hour |
| **F10** | ArtifactStore was FIFO, not LRU — `get()` never refreshed position. ⚠️ The Round-2 audit marked this "fixed in live tree"; it was NOT | `artifact_store.py` | `get()` moves the entry to the end of `_order` under the lock | hour |
| **F11** | All-script prompt scrubs to empty; engine still called the planner | `engine.py`, `test_script_extractor.py` | Phase-0 short-circuit: empty planner prompt → return extracted files, skip LLM; fixed the wrong `assert scrubbed` test assertion | hour |
| **F12** | `build_summary()` re-derived `applied` from per-result dicts | `artifact_store.py`, `test_artifact_store.py` | Use `ExecutionResult.to_dict()`'s `success_count`; test fixture now uses the executor's real result shape | hour |
| **F4/F6** | Bundle built by ad-hoc one-liner: shipped 27 `__pycache__` dirs, dropped `devforge/execution/godot_ai_mcp.py` via over-broad `*/godot_ai*` exclusion (twice — S1 was the same bug) | `scripts/build_audit_bundle.sh` (new) | Checked-in bundler: targeted exclusions, runs full test suite first, sanity-checks the zip for `godot_ai_mcp.py` and `__pycache__` leaks | hour |
| **New** | `test_gateway_budget.py` `__main__` list referenced undefined `test_strict_mode_rejects_default_bucket` — `NameError`, whole suite unrunnable | `test_gateway_budget.py` | Point at the function that exists (`test_strict_mode_env_var_configurable`) | trivial |
| **New** | Executor tests mocked the old SSE transport; code uses Streamable HTTP since the transport fix — 9/18 failed | `test_godot_ai_mcp.py` | Fixture now patches `mcp.client.streamable_http.streamable_http_client` and yields the 3-tuple `(read, write, get_session_id)` | hour |
| **New** | `test_get_scene_returns_dict` mocked godot-ai's response in the old bare-tree shape | `test_godot_ai_mcp.py`, `godot_ai_mcp.py` | Mock now uses the real wrapped `{"root", "nodes", ...}` shape; `_unwrap_scene_hierarchy` also gained a bare-tree fallback instead of returning None | trivial |
| **New** | Import-walk blind spot: 9 dirs had no `__init__.py` (namespace packages), so `pkgutil.walk_packages` silently skipped them — walk covered 94 of 141 modules and missed 17 broken ones | `world_model/`, `patterns/`, `reasoning/{architecture,prompts,verification,agents,ai,ai/design}/`, `world_model/compiler/` | Added `__init__.py` files; walk now covers 141 modules, all pass | hour |
| **New** | 5 dead modules referenced packages that don't exist in this tree (`devforge.core`, `devforge.state`, `devforge.knowledge.state`, `devforge.knowledge.specs`, `devforge.reasoning.ai.context`); nothing imports them | `preview_api.py`, `plan_cache.py`, `plan_generator.py`, `planner_interfaces.py`, `prompt_builder.py` | Moved to `docs/archive/dead-modules/` with a README of original locations. `LRUPlanCache` (`lru_cache.py`) is live and untouched | hour |
| **New** | `devforge_project_tests/test_imports.py` had no path bootstrap and no `__main__` — running it per CLAUDE.md instructions failed with `ModuleNotFoundError` | `test_imports.py` | Added the same `sys.path` bootstrap + `__main__` runner the other standalone tests use | trivial |

Also new: `scripts/run_all_tests.sh` — the fix-verification loop the Round-2
audit's root-cause section called for. Run it after every change batch;
`build_audit_bundle.sh` refuses to bundle a tree that fails it.

**F9 was genuinely already fixed** in the live tree (sliding expiry resets
`created_at`) — verified, no change needed.

---

## Summary by Difficulty

| Difficulty | Count | IDs |
|-----------|-------|-----|
| Trivial | 13 | S4, H6, H7, M4, M6, Bug #1, Bug #4, Bug #5, F1, F2, F3, F5, +2 new |
| Hour | 22 | S1, S2, S3, H1, H2, H3, H5, M1, M2, M3, M5, Bug #2, Bug #3, F4/F6, F7, F8, F10, F11, F12, +3 new |
| Day | 1 | H4 |
| Multi-day | 0 | — |

**Total: 38 bugs fixed across 5 rounds (plus Round 6 below).**

---

## Round 6: Advanced Fixes — Pipeline Gaps + godot-ai Contract Audit (June 11, 2026)

Tackled the harder known issues. godot-ai (port 8000) was down, so the
contract audit was done statically against the godot-ai source at
`~/dev/ai/godot-ai` (plugin dispatcher registry in `plugin.gd`, handler
param reads in `handlers/*.gd`, MCP tool signatures in `src/godot_ai/tools/`).
**The batch-command fixes still need one live smoke test once the stack is up.**

### Known issue #3: `_rename`/`_remove` deltas now compile (was: silently dropped)

The full chain was missing — now implemented and tested end-to-end
(`devforge/tests/test_rename_remove.py`, 7 tests, in `run_all_tests.sh`):

| Layer | Change |
|-------|--------|
| `architecture_planner.py` | Rename/delete regexes now match the case-preserved prompt ("rename Player to Hero" no longer lowercases "Hero"; the regexes were already IGNORECASE) |
| `ir/plan.py` | New `RemoveNodeStep` / `RenameNodeStep` with validate() + compile() |
| `architecture_compiler.py` | Handles `_rename`/`_remove` markers; resolves bare names to scene paths case-insensitively; unresolved targets fall through to a clear validator rejection |
| `godot_ai_mcp.py` | `remove_node` → `delete_node`, `rename_node` → `rename_node` (params: `path`, `new_name`) |

### godot-ai contract audit: 4 real mismatches found and fixed

**Root cause:** `batch_execute` sub-commands use godot-ai's *plugin command
names* (registered in `plugin.gd`'s dispatcher), NOT the category-prefixed
MCP *tool* names. DevForge had tool names and wrong param keys in its maps.
Only `add_node`/`create_node` was fully correct — which is why node creation
worked in the smoke test while the other op types were silently broken:

| Op | Was sent | Now sends | Why it failed before |
|----|----------|-----------|----------------------|
| `attach_script` | command `script_attach`, param `node_path` | command `attach_script`, param `path` | `script_attach` isn't a registered plugin command; handler reads `path` |
| `set_property` | param `node_path` | param `path` | `_resolve_node()` reads `params.path` → "Missing required param" |
| `connect_signal` | param `source` | param `path` | handler requires `path`/`signal`/`target`/`method` |
| files → `script_create` tool | `path: "scripts/x.gd"` | `path: "res://scripts/x.gd"` | godot-ai's path validator rejects anything not starting with `res://` (param *names* were correct, resolving the old open question) |

`script_path` values in batch commands get the same `res://` normalization
(new `_res_path()` helper). Node paths like `/root/Main/Player` were verified
OK — godot-ai's `McpScenePath.resolve()` handles the `/root/<SceneRoot>` alias.
3 new regression tests in `test_godot_ai_mcp.py` (21 total).

### Known issue #5: LRU plan cache disk-write debounce

`lru_cache.py` wrote the full cache JSON on every `set()`. Writes are now
debounced (`SAVE_INTERVAL_S = 5.0`): mutations inside the window batch into
the next write; `flush()` forces; an `atexit` hook flushes on clean exit;
`clear()` still writes immediately. Worst case on a crash: the last ≤5s of
cache entries — acceptable for a local plan cache.

### Known issue #1: `get_scene` children — verified correct in code

Static trace: `mcp_server.get_scene` → `SceneStore.get_or_fetch` →
`executor.get_scene()` → `_get_scene_async()` → `_unwrap_scene_hierarchy()`.
Both hierarchy fetch sites unwrap; nothing bypasses. The June symptom was the
**stale running server instance**, not the code. Remaining action is
operational only: restart the server on port 8001.

---

## Round 7: Grab-Bag — Small Fixes and Hardening (June 11, 2026 session)

Bundled everything too small for its own round. All 9 suites pass after
(`scripts/run_all_tests.sh`; rename/remove suite included since Round 6).

| Finding | File(s) | Fix |
|---------|---------|-----|
| Script extractor could emit **two files with the same path** when one script splits at a blank line under a single `# path:` header — the executor's second `script_create` would overwrite the first, silently losing content | `script_extractor.py` | Fragments inferring an existing path now **merge** into that file instead of duplicating; regression test added (extractor suite now 9 tests) |
| `DevForgeLogger` had no `warning()` — the stdlib-habit call crashed a security path once already (F1) | `logger.py` | `warning = warn` alias; the bug class can't recur |
| Import-walk used `pkgutil.walk_packages`, which silently skips namespace dirs — the same blind spot that hid 17 broken modules could re-open with any new `__init__`-less directory | `test_import_walk.py` | File-based (rglob) module discovery; covers 142 modules (vs 141); explicit, documented `EXCLUDED_MODULES` (only `patch/grammars/setup.py`, a packaging script) |
| Deprecated Claude model pinned: `claude-sonnet-4-20250514` **retires June 15, 2026** (4 days) — the `claude` backend would 404 | `runtime_config.py`, `claude_client.py`, `router.py` | Default → `claude-sonnet-4-6` (current API ID, verified against the API reference); `chat()` also now extracts the first *text* block instead of `content[0]` (which can be a thinking block) |
| Executor silently skipped files with empty content (`if path and content`) — godot-ai's `script_create` explicitly supports blank files | `godot_ai_mcp.py` | Skip only on missing path |
| Procfile started llama.cpp on port **8080**; everything else (config default, CLAUDE.md, SETUP-GUIDE) uses **9090** | `Procfile` | 9090 |
| `devforge/README.md` had actively wrong copy-paste commands: `tools/verify_pipeline.py` (moved), `tests/` (moved), FastAPI on port 8000 (now godot-ai's port), llama default 8080 | `devforge/README.md` | Historical-status banner pointing to CLAUDE.md + corrected commands (FastAPI example moved to port 8002) |

Note: the Procfile's `transport='sse'` for the DevForge MCP server was left
alone — it matches `mcp_server.py:444`. The Streamable-HTTP migration applied
to the *executor's client* connection to godot-ai, not DevForge's own server
transport (Odysseus connects to that; changing it is a coordinated change,
not a cleanup).

---

## Round 8: Hardware-Fit Tuning — RX 6800 / llama.cpp (June 11, 2026 session)

Goal: make the pipeline fit the machine it actually runs on (RX 6800 16GB,
Gemma 4 26B-A4B Q4_K_XL, `--ctx-size 12288`). All 10 suites pass after.

| Finding | File(s) | Fix |
|---------|---------|-----|
| **Context budget overshot the server window**: configured 24000-token budget + 4096 generation + template overhead vs a 12288-token server window. llama.cpp silently drops the OLDEST prompt tokens on overflow — i.e. the instruction prefix | `runtime_config.py`, `llama_client.py`, `mcp_server.py`, `server.py` | New `LlamaClient.server_props()` queries `/props` for the real `n_ctx`; `apply_server_limits()` clamps `context_token_budget` at startup, before the ContextAssembler computes section budgets (verified live: 24000 → 7168). Pure math in `effective_context_budget()`, unit-tested (`test_context_clamp.py`, 5 tests, in `run_all_tests.sh`) |
| Hardcoded 120s LLM timeout sits exactly on the worst-case edge for this GPU (full 7K prefill + 4K decode ≈ 90–120s) | `llama_client.py`, `router.py`, both entry points | `llm_timeout_s` config (default 300, env `DEVFORGE_LLM_TIMEOUT`, validated) |
| No pre-flight check existed; misconfigurations surfaced mid-pipeline | `devforge/doctor.py` (new) | `python -m devforge.doctor` — checklist for config, llama `/props` + window math, grammar generation, godot-ai/DevForge-MCP ports, game_root, deps. `--warm` warms the model (server runs `--no-warmup`) by priming the planner's real static prefix, and **measures** prompt-cache reuse via `timings.prompt_n` |
| **Measured finding: prompt-cache reuse is broken on this setup** — doctor probe showed the second identical call reprocessed 89/88 prefix tokens. Gemma's sliding-window attention defeats llama.cpp `cache_prompt`; every turn pays full prefill | `TUNING.md` (new) | Documented fix to try: `--swa-full` on llama-server, with the measure-after procedure. Also: `DEVFORGE_LLAMA_MAX_TOKENS=2048` recommendation (planner emits a small delta; halving generation reserve hands ~2K tokens back to context), batch-size and KV-quant guidance, and a "leave these alone" table |

Design note: the clamp treats configuration as a *wish* and the server's
`/props` as *reality* — the same principle as the Round-2 audit's
fix-verification loop, applied to capacity instead of correctness.

---

## Round 9: Architect Review of the Executor Build-Out (June 11, 2026 session)

Context: per `workorders/`, implementation moved to executor agents while
Claude reviews. The executors delivered 22 work orders in one burst — the
entire Phase A–D capability layer (Scene Doctor, Batch Operator, Error
Triage, Template Forge + 10 templates, Lorekeeper, Quest Validator,
Performance Sentinel, Smoke Runner, and more): 16 new packages, 30 MCP
tools, suite grown to 25 suites / ~290 tests, all passing. This round is
the review the workorder system was designed for. Verdict: module-level
code quality is genuinely good (clean dependency injection, consistent
two-step mutation patterns) — but the green suite hid an entire class of
defect: **everything testable offline was right; everything that touches
the live wire was guessed, and mostly guessed wrong.**

### Fixed: executor wire layer — 6 of 10 godot-ai call shapes were wrong

The new executor methods were tested only against injected fakes; their
actual MCP calls used invented tool names. Audited every call against
godot-ai's registered tools and the manage-tool convention
(`{"op": ..., "params": {...}}`):

| Method | Was (wrong) | Now (verified) |
|---|---|---|
| `get_performance_monitors` | tool `performance_monitors_get` (doesn't exist) | `editor_manage` op `monitors_get` |
| `game_eval` | tool `game_eval`, param `expression` | `editor_manage` op `game_eval`, param `code` |
| `take_screenshot` | tool `take_screenshot` | `editor_screenshot`, `source="game"`, `include_image=False`; returns `"game:WxH"` (godot-ai returns image data, never file paths) |
| `run_project` | `project_manage` op `run_project` (no such op) | dedicated `project_run` tool, `mode`/`scene` params |
| `stop_project` | `project_manage` op `stop_project` | `project_manage` op `stop` |
| `find_symbols` / `search_filesystem` | kwargs flat beside `op`; op `search_filesystem`; param `query`/`recursive` | kwargs nested under `params`; op `search`; param `name` (search is always recursive) |

Every consumer (Sentinel, Smoke Runner, Navigator, Signal Mapper) is fixed
transitively since they inject these methods. **7 wire-shape regression
tests** added to `test_godot_ai_mcp.py` (34 total) so guessed names can
never pass green again.

### Fixed: template_apply silently destroyed customized scripts

Node-path collisions were checked; script files were not — godot-ai's
`script_create` overwrites silently, so re-applying a template clobbered
any user edits to e.g. `scripts/health.gd`. Now: `instantiate_template`
takes a `file_exists` probe (wired to live filesystem search) and refuses
when a template script already exists — or when existence can't be
verified — unless the new `overwrite_files=true` argument gives explicit
consent. 4 regression tests.

### Fixed: templates that apply cleanly and then silently do nothing

The fps_controller (and others) read Input Map actions (`sprint`,
`move_left`, …) that fresh Godot projects don't define — the system
applies green and the player can't move. New `required_input_actions()`
scans template scripts deterministically; `template_preview` and
`template_apply` now surface the action list plus a hint pointing at
Project Settings → Input Map / godot-ai's `input_map_manage`. 2 tests
(forge suite now 33).

### Verified good (no change needed)

- `batch_preview`/`batch_apply`: scene-version drift gate, validation
  before execution, pipeline lock, journal entry — textbook.
- `scene_extract`: read-only preview feeding `batch_apply`. Correct.
- Error triage: classifies real Godot 4 wording correctly (spot-checked
  E01/E02/E03 against canonical messages).
- Journal: in-project storage (`.devforge/journal/`), atomic rewrite.
- Scene Doctor: live property rules correctly wired to
  `resolve_node_properties` (WO-004 delivered).
- Sentinel: None-safe sampling.
- The executors' worklog discipline: honest deviations sections, accurate
  file lists. One process violation: they specced and built WO-005..020
  without architect review between phases — it worked out, but the wire
  layer defects are exactly what the one-WO-at-a-time rule exists to catch.

---

## Remaining Known Issues

(Issues #1, #2, #3, #5 from the original list were resolved in Round 6 above.)

1. **Live-stack verification of the Round-6 contract fixes** — needs godot-ai
   (port 8000) + Godot editor running:
   - Restart the DevForge MCP server on port 8001 (the running instance
     predates all of Rounds 5–6).
   - Run `python integration_tests/integration/test_smoke.py`.
   - Exercise one `apply_spec` whose plan includes `attach_script` +
     `set_property` (e.g. a system + entity prompt) — these op types were
     silently broken before Round 6 and have never executed live.
   - Exercise "rename X to Y" and "delete node X" prompts end-to-end.

2. **`chat()` multi-turn** — Single-turn only; documented but not exercised by any call site.
   → **Low priority.** Only needed if Odysseus starts sending conversation history.

## Round 6: Stream B — DevForge Robustness Sweep (June 13, 2026)

Fixes drawn from the ~30 C/D findings in the v2 pipeline investigation.

### D1 — Log remaining token budget after each LLM call

**Problem:** The LLM gateway was opaque — you couldn't see budget exhaustion
coming until it hit the 429 limit and killed the pipeline.

**Fix:** Gateway now returns `X-Budget-Remaining` header on every response;
`LlamaClient` logs it at info level. Operators/agents can now spot the trend
before it becomes a failure.

**Files:** `gateway.py`, `llama_client.py`

### D2 — Preserve full scene context on non-budget retries

**Problem:** The planning retry loop trimmed scene context on EVERY retry
(`minimal=(attempt >= 2)`), even when the failure was a parse error or model
incoherence — cases that benefit from MORE context, not less.

**Fix:** Only trim context when the error is a budget/token error
(`is_budget_error = "budget" in str(pe).lower()`). Non-budget retries now
keep the full scene context.

**Files:** `engine.py`

### D6 — Per-injection error handling in CompletenessChecker

**Problem:** The completeness checker's injection rules (Camera3D,
DirectionalLight3D, CollisionShape, BoxMesh) shared a single try/except path.
One malformed injection (e.g. a corrupted scene path) killed the entire pass.

**Fix:** Each injection rule is now wrapped in its own try/except with
`logger.warn(..., "skipping")`. The remaining rules proceed independently.

**Files:** `completeness.py`

### C8 — Per-operation retry with backoff in GodotAIMCPExecutor

**Problem:** `batch_execute` had zero retry logic. Transient failures from
editor importing, WS blips, or project-scan pauses killed the whole execution.

**Fix:** `_execute_async` now retries `batch_execute` up to 2 additional
times (3 total) with exponential backoff (0.5s → 1.0s → attempt exhausted)
on ConnectionError / TimeoutError / OSError. Non-transient errors still fail
fast on the first attempt.

**Files:** `godot_ai_mcp.py`

### C5 — Lock acquisition timeout on pipeline lock

**Problem:** `_pipeline_lock = threading.Lock()` had no acquisition timeout.
A wedged `apply_spec` call would hang all subsequent calls forever with zero
signal.

**Fix:** `_acquire_pipeline_lock()` now calls `lock.acquire(timeout=300)`.
On timeout, raises `RuntimeError("Pipeline lock acquisition timed out...")`
so the wedged call fails loudly rather than hanging silently. Context manager
wrapper `_acquire_pipeline_lock_ctx()` replaces bare `with _pipeline_lock:`.

**Files:** `mcp_server.py`

### D10 — Verify op dedup can't silently merge distinct ops

**Problem (investigated):** `_dedupe_operations` uses `json.dumps(op,
sort_keys=True, default=str)` as the dedup key. `default=str` is the
potential risk — if two dicts differ only in datetime/NaN/unknown objects,
both would serialize as plain `<repr>` via `str()`, producing the same key.

**Verdict:** This is safe for the current operation schema. Every field in
a DevForge operation dict (type, parent, node_type, name, node, property,
value, script_path, signal_name, target, method) has string or number
values — JSON-native types. `default=str` only fires for values unknown to
JSON (datetime, Path, object references), which never appear in operations.
Test added asserting that: (1) identical ops produce identical keys, (2)
ops differing only in a string value produce different keys, (3) ops
differing only in a numeric property produce different keys.

**Files:** `test_prompt_templates.py` (new `TestDedupOperations` class)

### C10/D7 — Grammar self-test documented + normalize_gbnf idempotency confirmed

**C10 (document grammar self-test non-blocking):** The grammar self-test
(`selftest_grammar()`) is intentionally non-blocking — it warns but does not
refuse to start. This is correct: GBNF enforcement is unreliable across
model families/quantizations, and post-generation JSON validation catches
malformed output. Documented here so this doesn't get re-investigated.

**D7 (normalize_gbnf idempotency):** Confirmed — `normalize_gbnf` is
idempotent by construction (it only joins continuation lines that start with
`|`; once joined, no more `|`-starting lines exist). Tests already exist in
`test_prompt_templates.py` (`test_normalize_gbnf_idempotent_on_single_line`).
Added a stronger test: `normalize(normalize(x)) == normalize(x)` for
multi-line grammars with continuation lines.

**Files:** `CHANGES.md` (this entry), `test_prompt_templates.py`

### Also — Flipped DEVFORGE_DEBUG=1 → 0

The chain is stable now. Debug verbosity is just noise + log volume.
Confirmed `stack doctor` still green after the change.

**Files:** `stack.env`

---

## Round 10 — Stream F: Gruntwork, Diagnostics & A/B Planner (June 14, 2026)

Three rounds of refinement after the capability work (Phases 4–6 from
`STAGE-2-HANDOFF.md` and `ROADMAP.md`). Round 1 hardened code quality;
Round 2 integrated pipeline diagnostics into probes + shootout; Round 3
added A/B planner comparison and regression detection.

### Round 1 — Gruntwork Cleanup

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **G1** | `arch_planner.gbnf` template had drifted from the generated grammar — 17 godot-types were in the generated file but missing from the human-readable template | `arch_planner.gbnf` | Backported all 17 types (`Area2D`, `RigidBody3D`, `Marker3D`, `SubViewport`, `TextureRect`, `NavigationRegion3D`, etc.). Regenerated `arch_planner_generated.gbnf` to confirm zero diff. Sync comment now names all 3 grammar files. | trivial |
| **G2** | Mesh/shape/material `__class__` dicts duplicated across 3 files — `architecture_compiler.py`, `ops_planner.py`, and `completeness.py` each embedded the same BoxMesh/SphereMesh/StandardMaterial3D resource templates | `resource_templates.py` (new), `architecture_compiler.py`, `completeness.py` | Extracted `MESH_RESOURCES`, `SHAPE_RESOURCES`, and `make_material()` into a shared `devforge/knowledge/scene/resource_templates.py` module. Updated all consumers to import from it. | hour |
| **G3** | 7 `REVIEW` markers left from Phase 4–6 implementation had no resolution — an auditor would ask "what's the verdict?" | `engine.py` (3), `architecture_compiler.py` (1), `architecture_planner.py` (1) | Converted each REVIEW to a permanent docstring comment describing the design decision. | trivial |
| **G4** | Lambda closure pattern `lambda p, g=grammar_path: ...` in `engine.py` is a known Python gotcha (late-binding confusion) | `engine.py` | Replaced with `functools.partial(self._llm.generate, grammar_path=...)` for clarity. | trivial |
| **G5** | Mid-file `import bench` / `import scenarios` / `import shootout` in `hub.py` with `# noqa: E402` comments — placed there defensively but no actual circular dependency exists | `hub.py` | Moved imports to top of file with explanatory comment. | trivial |
| **G6** | Bare `except Exception: pass` at 4 sites swallowed errors silently — `context_assembler.py` (token counter, script read) and `hub.py` (chain-health /props, shootout body parse) | `context_assembler.py`, `hub.py` | Added `logger.warning()` / `logging.debug()` before each `pass`. | trivial |

### Round 2 — Diagnostic Integration

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **D11** | Pipeline diagnostics (per-stage latency, retry counts, repair activity, completeness ops) were tracked internally by `engine.py` but never surfaced to probes or shootout — you could see a score of 77/100 but not *why* | `engine.py`, `bench.py`, `shootout.py` | **PipelineResult** extended with `plan_retries`, `repair_count`, `completeness_added`, `token_used` fields (all safe defaults). `_run_arch_path` and `_run_ops_path` now return 4-tuples including `plan_retries`. `run_pipeline` captures `repair_count` and `completeness_added` by diffing op counts before/after each stage. | hour |
| **D12** | Probes had no visibility into per-stage timing or retry/repair activity | `bench.py` | `p_devforge_plan` now surfaces `plan_stage_ms`, `compile_ms`, `plan_retries`, and full `stage_latencies` breakdown. `p_devforge_execute` shows `repair_count` and `completeness_added`. | hour |
| **D13** | Shootout failures had no root-cause attribution — you knew an assertion failed but not *which pipeline stage* was responsible | `shootout.py` | New `_attribute_failures()` helper cross-references every failed assertion against `arch_delta`/`operations`/`files` to attribute each failure to `plan` / `compile` / `execute` / `completeness` / `runtime`. Scorecards enriched with `stage_latencies`, `plan_retries`, `repair_count`, `completeness_added`. | hour |

### Round 3 — A/B Planner Comparison + Regression Detection

| ID | Finding | File(s) | Fix | Difficulty |
|----|---------|---------|-----|-----------|
| **D14** | The Phase 6 ops planner (`DEVFORGE_PLANNER=ops`) had no automated way to A/B test against the arch planner — you had to manually edit config, restart DevForge, and run two separate shootouts | `shootout.py` | **`--all-planners` flag.** Runs each model through both `arch` and `ops` planner paths. New `_set_planner_mode()` modifies `DEVFORGE_PLANNER` in `stack.env`; `_restart_devforge()` restarts systemd service and polls MCP health. `_compare_planners()` produces side-by-side scorecards with per-model delta and winner. | hour |
| **D15** | No automated regression detection — a model could silently drop from 77 to 55 without any alert | `shootout.py` | **`_detect_regressions()`** compares each model's current score against its best score from all previous shootouts. Flags any model dropping >10 points. Scorecard enriched with `regression_flags` field: `{model, alias, current_score, previous_best, previous_ts, delta}`. | hour |

**Validation (all three rounds):** 318 DevForge tests pass, 133 hub tests pass
(11 skip), `llama.grammar` + `llama.throughput` probes green, `forge-devforge`
service active. Zero behavior changes to existing paths. All new fields have
safe defaults.

**Files changed across Stream F:** `arch_planner.gbnf`, `resource_templates.py`
(new), `architecture_compiler.py`, `completeness.py`, `engine.py`,
`architecture_planner.py`, `context_assembler.py`, `hub.py`, `bench.py`,
`shootout.py` — **10 files total.**

---

## Summary by Difficulty (Round 10 additions)

| Difficulty | Count | IDs |
|-----------|-------|-----|
| Trivial | 5 | G1, G3, G4, G5, G6 |
| Hour | 6 | G2, D11, D12, D13, D14, D15 |

**Total: 53 bugs/improvements across all rounds.**
