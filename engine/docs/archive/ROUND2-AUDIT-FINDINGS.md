<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# DevForge Round 2 Audit — Claude's Findings

**Auditor:** Claude (second audit pass against the `devforge_audit_bundle.zip`)
**Date:** June 11, 2026
**Scope:** Verified which Round 1 fixes actually landed, identified regressions and new defects
**Test baseline:** 12 failures / 25 tests (52% pass rate)
**⚠️ Note:** This audit ran against a **stale bundle** (built before the investigation session). Findings marked **bundle-only** are already fixed in the live working tree at `/home/mrg/dev/games/Forge/devforge_review_package/`. Findings marked **live** still need fixing.

**✅ STATUS (June 11, 2026): ALL FINDINGS RESOLVED.** F1–F12 fixed in the
round-5 session — see `CHANGES.md` "Round 5" for the full record, including
several new defects found and fixed along the way (gateway test `NameError`,
SSE→Streamable-HTTP test mock drift, an import-walk namespace-package blind
spot, 5 archived dead modules). One correction: **F10 (ArtifactStore LRU) was
NOT actually fixed in the live tree** despite the bundle-only marking — it is
now. `scripts/run_all_tests.sh` passes clean (8/8 suites).

---

## Finding Summary (easiest → hardest)

| # | Finding | Difficulty | Tests broken |
|---|---------|-----------|-------------|
| **F1** | `logger.warning()` should be `logger.warn()` — crashes security path | trivial | 2 |
| **F2** | `_sanitize_path()` doesn't strip whitespace before acting | trivial | 1 |
| **F3** | `ArtifactStore.max_entries` is `_max_entries` — attribute name mismatch | trivial | 1 |
| **F4** | 27 `__pycache__/` dirs shipped in bundle | trivial | — |
| **F5** | `requirements.txt` missing `pytest` | trivial | all |
| **F6** | `godot_ai_mcp.py` still missing from bundle — import-walk fails | hour | 1 |
| **F7** | Config validation prints to stderr but doesn't raise | hour | — |
| **F8** | Gateway tests: `_record_usage()` doesn't create entries — tests expect it to | hour | 3 |
| **F9** | `_record_usage()` docstring claims sliding expiry but `created_at` never reset | hour | 1 | **bundle-only** (fixed in live tree) |
| **F10** | `ArtifactStore.get()` doesn't refresh LRU position — implements FIFO, not LRU | hour | 2 | **bundle-only** (fixed in live tree) |
| **F11** | `script_extractor` full-scrub path leaves empty prompt — engine should short-circuit | hour | 1 |
| **F12** | `build_summary()` counts results instead of using `ExecutionResult.success_count` | hour | 1 |

---

## Detailed Findings

### F1: `logger.warning()` → `logger.warn()` (trivial)

**Where:** `devforge/compilation/pipeline/script_extractor.py`, line 203
**What:** `_sanitize_path()` calls `logger.warning(...)` but `DevForgeLogger` only has `warn()`, not `warning()`. This `AttributeError` crashes the path-traversal rejection path — the security check itself becomes the vulnerability (500 error instead of clean rejection).
**Impact:** Any prompt containing `..` or absolute paths causes an unhandled exception in Phase 0 of the pipeline.

**Fix:**
```python
# Line 203: change
logger.warning("script_extractor", f"Rejected unsafe path: {raw!r}")
# to
logger.warn("script_extractor", f"Rejected unsafe path: {raw!r}")
```

---

### F2: `_sanitize_path()` doesn't strip whitespace (trivial)

**Where:** `devforge/compilation/pipeline/script_extractor.py`, `_sanitize_path()`
**What:** Passing `"   "` (whitespace only) produces `scripts/   .gd` because the input is never `.strip()`'d. The basename `"   "` is truthy and doesn't end with `.gd`, so `.gd` is appended.
**Impact:** Creates files with whitespace-padded names; the traversal guard at the top never fires because `"   "` doesn't start with `/` or `\\` and doesn't contain `..`.

**Fix:** Add `raw = raw.strip()` as the first line of `_sanitize_path()`, then explicitly reject empty input:
```python
def _sanitize_path(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:          # ← reject empty/whitespace-only
        return None
    # Normalize and reject traversal
    if ".." in raw or raw.startswith("/") or raw.startswith("\\"):
        ...
```

---

### F3: `ArtifactStore.max_entries` vs `_max_entries` (trivial)

**Where:** `devforge/knowledge/artifact_store.py`, line 34; `devforge/tests/test_artifact_store.py`, line 139
**What:** The test accesses `store.max_entries` but the implementation uses `self._max_entries` (private). Test fails with `AttributeError: 'ArtifactStore' object has no attribute 'max_entries'`.
**Impact:** One test failure; the attribute is correctly private, the test is wrong.

**Fix:** Either rename `_max_entries` to `max_entries` (public API), or change the test to access `store._max_entries`. Preference: make it public since the constructor parameter is `max_entries`.

---

### F4: 27 `__pycache__/` directories in bundle (trivial)

**Where:** Bundle at `/home/mrg/devforge_audit_bundle.zip`
**What:** The bundler didn't exclude `__pycache__/` directories. 27 stale bytecode dirs inflate the bundle.
**Impact:** Cosmetic — makes the bundle larger than needed, but no functional issue.

**Fix:** Add `-not -path '*/__pycache__/*'` to the bundler's `find` command.

---

### F5: `requirements.txt` missing `pytest` (trivial)

**Where:** `devforge/requirements.txt`
**What:** The test suite requires `pytest` but it's not listed in requirements. A fresh venv can't run tests.
**Impact:** Anyone installing from requirements.txt can't run the test suite.

**Fix:** Add `pytest>=8.0.0` to requirements.txt (dev dependency section).

---

### F6: `godot_ai_mcp.py` still missing from bundle (hour)

**Where:** Bundle; `devforge/execution/__init__.py` line 14
**What:** `devforge/execution/__init__.py` imports `GodotAIMCPExecutor` from `devforge.execution.godot_ai_mcp`, but the bundler excluded `godot_ai_mcp.py`. This is the second time — the first audit flagged it as S1. The import-walk test catches this.
**Live tree status:** The file EXISTS in the live working tree at `/home/mrg/dev/games/Forge/devforge_review_package/devforge/execution/godot_ai_mcp.py` — this is strictly a bundler exclusion bug.
**Root cause:** The bundler exclusion pattern `-not -path '*/godot_ai*'` catches DevForge's own file because the directory is named `godot_ai_mcp.py`. The exclusion was meant for the external godot-ai package, not DevForge's own executor.
**Impact:** Every entry point (`server.py`, `mcp_server.py`, `execution/__init__.py`) fails to import.

**Fix:** Change the bundler exclusion to target only the external godot-ai directory, not DevForge files:
```bash
# OLD (too broad):
-not -path '*/godot_ai*'
# NEW (targeted):
-not -path '*/addons/godot_ai*' -not -path '*/godot-ai/*'
```

---

### F7: Config validation prints errors but doesn't fail startup (hour)

**Where:** `devforge/infrastructure/runtime_config.py`, lines 168-180 (`get_config()`)
**What:** `validate()` returns a list of errors, and `get_config()` prints them to stderr — but doesn't raise or exit. A typo'd `executor_backend` or impossible `max_plan_retries=0` prints a warning and continues silently.

**Fix:** After printing errors, raise `SystemExit(1)` or `ValueError`:
```python
if errs:
    import sys
    print("\n".join(f"[CONFIG ERROR] {e}" for e in errs), file=sys.stderr)
    raise SystemExit(1)  # fail loudly
```

---

### F8: Gateway budget tests don't call `_check_budget()` before `_record_usage()` (hour)

**Where:** `devforge/tests/test_gateway_budget.py`, lines 30-60; `devforge/infrastructure/llm/gateway.py`, lines 198-210
**What:** `_record_usage()` returns early if the turn_id doesn't exist in `_turn_budgets` (line 207-208: `if entry is None: return`). The tests call `_record_usage()` directly without calling `_check_budget()` first, so no entry is created and no tokens are recorded. The budget never exceeds, `_check_budget()` never raises 429.
**Impact:** 3 gateway budget tests fail because they never actually record usage. In production this works fine because the handlers always call `_check_budget()` before `_record_usage()`.
**Fix:** In each failing test, call `_check_budget(test_key)` before `_record_usage(test_key, ...)` to create the entry. The production code is correct; the tests just need the setup step.

---

### F9: `_record_usage()` sliding expiry — bundle-only, fixed in live tree (hour)

**Where:** `devforge/infrastructure/llm/gateway.py`, lines 198-210
**Status:** ⚠️ **Bundle-only** — the investigation session already added `entry.created_at = time.monotonic()` to the live tree. The bundle predates this fix.
**What:** The docstring says "Resets the expiry timer on every call" but the bundle code never resets `entry.created_at`. The live tree has this fix.
**Impact (bundle only):** Active long-running turns can expire mid-pipeline. Not an issue in the live tree.

---

### F10: `ArtifactStore` LRU — bundle-only, fixed in live tree (hour)

**Where:** `devforge/knowledge/artifact_store.py`, lines 30-75
**Status:** ⚠️ **Bundle-only** — the investigation session already added LRU refresh to the live tree. The bundle predates this fix.
**What:** The docstring says "LRU eviction" but the bundle's `get()` never moves the accessed entry to the end of `_order`. The live tree has this fix.
**Impact (bundle only):** Frequently-accessed artifacts can be evicted while rarely-accessed newer ones persist. Not an issue in the live tree.

---

### F11: Full-scrub empty prompt — engine should short-circuit (hour)

**Where:** `devforge/compilation/pipeline/engine.py`, Phase 0; `devforge/tests/test_script_extractor.py`, lines 60-72
**What:** When the entire prompt is a single GDScript block (the `test_extract_with_path_header` case), `extract_scripts()` removes everything and returns `scrubbed = ""`. The engine then tries to plan with an empty prompt, which the LLM can't meaningfully handle. The test asserts `scrubbed` is truthy — this is arguably the wrong assertion; the issue is that the engine should skip planning when all content was extracted as files.
**Impact:** An all-script prompt produces file creation operations correctly, but then the planner generates spurious operations from an empty prompt, or fails.
**Fix:** After Phase 0, if `planner_prompt.strip() == ""`, skip planning and return immediately with just the extracted files:
```python
if not planner_prompt.strip():
    return PipelineResult(
        files=extracted_files,
        operations=[],
        scene_tree=scene,
        scene_version=scene_version,
    )
```
**Fix:** Two changes needed:

1. **Engine short-circuit** — after Phase 0, skip planning on empty prompt:
```python
if not planner_prompt.strip():
    return PipelineResult(
        files=extracted_files,
        operations=[],
        scene_tree=scene,
        scene_version=scene_version,
    )
```

2. **Fix the test assertion** — `test_extract_with_path_header` currently asserts `scrubbed` is truthy, but the correct behavior is that `scrubbed` becomes empty (all content was extracted as files). Change:
```python
# OLD (wrong assertion):
assert scrubbed, "Prompt should be scrubbed"
# NEW (correct assertion):
assert len(files) >= 1, "Files should be extracted from the prompt"
assert files[0].path == "scripts/player.gd"
```

---

### F12: `build_summary()` counts individual results instead of using `success_count` (hour)

**Where:** `devforge/knowledge/artifact_store.py`, `build_summary()`; `devforge/execution/interface.py`, `ExecutionResult.to_dict()`
**What:** `build_summary()` re-derives `applied` by walking through `execution.get("results", [])` and counting `r.get("success")`. But `ExecutionResult.to_dict()` already provides `success_count`. The test constructs a payload with `{"success": True, "applied": 2}` — this is the wrong shape; the executor returns per-operation result dicts whose `success` key may not match the test's assumption.
**Impact:** `build_summary()` returns `applied: 0` when the executor correctly returned `success_count: 2` because the field names don't match between the test fixture and the implementation.
**Fix:** Use the existing `success_count` field instead of re-deriving:
```python
applied = execution.get("success_count", 0)
```
And update the test fixture to use the executor's actual result format.

---

## What's Actually Working (verified in this audit)

| Fix | Status | Evidence |
|-----|--------|----------|
| S3: Grammar auto-generation + self-test | ✅ Working | `mcp_server.py` lines 93-110 call `generate_grammar_file()` and `selftest_grammar()` |
| S4: `retry_prompt = planner_prompt` | ✅ Working | `engine.py` line 197 |
| H1: ContextVar for turn_id | ✅ Working | `llama_client.py` line 28-29, read at line 101 |
| H3: 429 → BudgetExceededError, terminal | ✅ Working | `llama_client.py` lines 157-160, `engine.py` line 211 |
| H6: CORS locked to localhost | ✅ Working | `server.py` line 52: `allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?"` |
| M1: Config validation exists | ⚠️ Partial | `validate()` exists and is called, but only prints errors — doesn't fail startup |
| M2: Procfile exists | ✅ Working | `docs/Procfile` with Honcho/Foreman format |
| M3: `threading.Lock` in mcp_server | ✅ Working | `_pipeline_lock = threading.Lock()` at line 61 |
| M4: get_scene returns version | ✅ Working | Returns `{"scene": ..., "version": N}` |
| Gateway strict mode | ✅ Working | `GATEWAY_STRICT_BUDGET` env var at line 55 |
| Import-walk test exists | ✅ Working but failing | Catches the missing `godot_ai_mcp.py` — test IS doing its job |

## What's NOT Working (regressions found)

| # | What | Why |
|---|------|-----|
| F1-F12 | 12 failing tests | Implementation/contract mismatches listed above |
| H4 | Sliding expiry | Docstring says it works, code never resets `created_at` |
| H2 | ArtifactStore LRU | Implements FIFO, not LRU — `get()` doesn't refresh |
| — | godot_ai_mcp.py in bundle | Same S1 bug, second time — bundler pattern too broad |
| — | Config validation | Prints errors, doesn't fail — typo'd configs run anyway |

---

## Root Cause: Broken Fix-Verification Loop

The 12 test failures exist because **fixes and tests were created together but never run together**. The import-walk test correctly catches the missing `godot_ai_mcp.py`, but nobody ran it. The gateway tests reveal that `_record_usage()` sliding expiry was documented but not implemented. The ArtifactStore tests reveal LRU was specified but FIFO was built.

**What's needed:** A CI step (even a simple shell script) that runs `python -m pytest devforge/tests/ -q` after every change batch. The current workflow creates fixes and tests in the same session, then ships the bundle without running either against the other.

---

## Packaging Issues

1. **`godot_ai_mcp.py` excluded by over-broad bundler pattern** (F6)
2. **27 `__pycache__/` dirs in bundle** (F4)
3. **`requirements.txt` missing `pytest`** (F5)
4. **`devforge/server/server.py` imports `devforge.execution`** — this file is NOT excluded but its import target (`godot_ai_mcp.py`) IS excluded, creating a silent import cascade failure

---

## Recommended Fix Order

1. **Trivial batch** (F1, F2, F3, F4, F5) — one-liners, fixable in <15 minutes total
2. **Test infrastructure** (F6, F8) — unbundle godot_ai_mcp.py, fix test setups so tests can actually run
3. **Implementation gaps** (F9, F10, F12) — sliding expiry, LRU eviction, build_summary contract
4. **Design gap** (F7, F11) — config fail-loudly, empty-prompt short-circuit
