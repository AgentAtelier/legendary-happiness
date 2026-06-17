# SESSION-CHANGES-2026-06-15 — Cumulative Summary

**Date:** 2026-06-15
**Session:** All slices (0–5)
**Status:** ✅ Complete
**Aggregate Gauntlet Progression (qwen3-14b):** 85% → 90% → 93% → 97%

> **Model attribution (added 2026-06-16):** every gauntlet number in this doc is on **qwen3-14b**.
> Re-running capability-v1 on **qwen3-6-27b** (now the loaded model) scores **100% (8F/0P/0B)** —
> the 27B resolves the G5 signal partial, confirming the "G5 = LLM non-determinism, not a code bug"
> diagnosis. Treat "97% / G5 holdout" as the 14B result, not a ceiling.
>
> **Spatial correction (2026-06-16):** Slice 1 below says "spatial 58%→67%, done." Routing *is*
> done and verified, but 67% was a **measurement bug**, not the real capability — the layout
> compiler builds a correct kitchen (30/30 ops, 0 errors) that the `spatial:assets` check
> miscounted as 0/3. Check fixed in `gauntlet.py:_add_spatial_checks`; re-measure pending. See
> `STAGE-PLAN-2026-06-15-A-to-F.md` Slice A.

---

## Capability-v1 Gauntlet Progression

| Slice | What Changed | Verdicts | Avg Coverage | Key Wins |
|-------|-------------|----------|-------------|----------|
| **Pre-session** | Baseline (before any fixes) | — | ~85% | — |
| **Slice 0** | G4 children fix + probe tab fix | — | **90%** | G4_children: 0→10 nodes |
| **Slice 3 R1** | Fix A + B1 + B2 (G5/G7) | 6F / 2P / 0B | **93%** | G7_integration: 0→25 nodes, full 100% |
| **Slice 3 R2** | + B3 (method check) + fallback removal | 5F / 3P / 0B | 89% | G5: 0→6 nodes (LLM non-det on G2) |
| **Slice 4** | Semantic validator + prop guards + execution guard | 7F / 1P / 0B | **97%** | G8: partial 67%→full 100% (2 errors) |
| **Slice 5** | Host-node creation + B3 fallback + templates | Pending re-run | — | Orphaned systems get Node3D hosts |

### Per-Prompt Trajectory

| Prompt | Slice 0 | Slice 3 R1 | Slice 4 (final) |
|--------|---------|------------|-----------------|
| G1_depth | full 100% | full 100% | full 100% |
| G2_breadth | full 100% | full 100% | full 100% |
| G3_props | full 100% | full 100% | full 100% |
| G4_children | full 100% | full 100% | full 100% |
| G5_scripts_signals | partial 75% (0n) | partial 75% (0n) | partial 75% (5n) |
| G6_mixed | full 100% | full 100% | full 100% |
| **G7_integration** | **partial 75% (0n)** | **full 100% (25n)** | **full 100% (25n)** |
| **G8_adversarial** | **partial 67%** | **partial 67%** | **full 100% (2 errors)** |

---

## Slice-by-Slice Summary

### Slice 0 — G4 Children Fix + Probe Tab Fix
- G4_children was broken (0 nodes from phantom-signal errors)
- Fix: Drop signal connections whose endpoints can't be resolved to real nodes
- Result: G4 went from 0 nodes to 10 nodes

### Slice 1 — Spatial Routing to Layout Planner
- Spatial-v1 prompts were routing through LLM arch planner (hallucinated nodes)
- Added per-request `planner` param to pipeline engine + MCP server + gauntlet
- Layout planner now always initialized (not just when global config matches)
- Result: spatial-v1 58%→67%, S2_L_kitchen broke→partial, 0 broke

### Slice 2 — Edit-Op Reliability Cluster
- Three failing edit-op scenarios: `node_delete`, `node_rename`, `rename_existing`
- **Fix 1:** Validator now checks `pending` paths in `_validate_remove_node` / `_validate_rename_node`
- **Fix 2:** `_RENAME_TO_RE` regex tightened (articles/qualifiers outside capture group)
- **Fix 3:** `_clean_rename_target()` with in-place cleaning of planner-emitted `_rename`
- Result: All three scenarios pass (12/15→15/15)

### Slice 3 — Capability-v1 Re-measurement + G5 Deep Debug
- Re-ran capability-v1 gauntlet with G5/G7 fixes from Slice 0
- **G7_integration:** Fixed by A (type-aware position) + B1 (non-3D drop) + B2 (unscripted drop)
- **G5_scripts_signals:** Deep debug revealed `_find_attach_target` fallback overwriting scripts
- **Fixes:** Removed Strategy 3 fallback + added B3 method-existence check
- Result: G5: 0→6 nodes, G7: 0→25 nodes, aggregate 90%→93%

### Slice 4 — G8 Adversarial Validator Improvements
- G8 produced 0 errors despite two bad ops (Camera3D+mesh, Orphan/Ghost)
- **Fix 1:** Removed silent prop-skipping guards in `_props_to_steps` (mesh/shape/color/text)
- **Fix 2:** Semantic check for Camera3D with MeshInstance3D child
- **Fix 3:** Wired `self._semantic_errors` through engine.py into `PipelineResult.errors`
- **Fix 4:** Changed mcp_server execution guard from `not result.errors` to always execute
- **Bug fix:** Fixed indentation — compilation block was inside `if inferred:`
- Result: G8: partial 67%→full 100% (2 errors), aggregate 89%→97%

### Slice 5 — Host-Node Creation + Signal Connection Fixes
- G5 signals check still failing (0/1) because SpawnerSystem had no host node
- **Fix 1:** When `_find_attach_target` returns None, create a Node3D host for the system
- **Fix 2:** B3 fallback — when LLM method name isn't found, try `_on_{signal}` default
- **Fix 3:** Added `_on_timeout()` to all four script templates (stub, movement, collectible, score)
- **Fix 4:** Warning when host node already exists in live scene
- G5 `min_signals` restored to 1 in capability-v1.json

---

## All Files Changed (Cumulative)

### `devforge/compilation/pipeline/architecture_compiler.py`
| Slice | Change |
|-------|--------|
| 0 | Fix A: skip `set_property position` on non-3D types |
| 0 | Fix B1: drop `connect_signal` to non-3D targets |
| 0 | Fix B2: drop `connect_signal` to unscripted same-delta targets |
| 3 | Remove `_find_attach_target` Strategy 3 fallback |
| 3 | Add B3: method-existence check in script content |
| 4 | Remove silent prop-skipping guards (mesh/shape/color/text) |
| 4 | Add semantic check: Camera3D with MeshInstance3D child |
| 5 | Create Node3D host for orphaned systems |
| 5 | B3 fallback: try `_on_{signal}` when method not found |
| 5 | Add `_on_timeout()` to all four script templates |

### `devforge/compilation/pipeline/engine.py`
| Slice | Change |
|-------|--------|
| 1 | Per-request `planner` param; layout planner always initialized |
| 2 | `_clean_rename_target()` + tightened `_RENAME_TO_RE` + in-place `_rename` cleaning |
| 4 | Wire `compilation_errors` from compiler into `PipelineResult.errors` |
| 4 | Fix indentation: compilation block outside `if inferred:` |

### `devforge/compilation/pipeline/validator.py`
| Slice | Change |
|-------|--------|
| 2 | `_validate_remove_node` + `_validate_rename_node` now check `pending` paths |

### `devforge/platform/mcp_server.py`
| Slice | Change |
|-------|--------|
| 1 | Per-request `planner` param threaded to `run_pipeline()` |
| 4 | Execution guard: proceed with valid ops even when errors present |

### Gauntlet Specs
| Slice | File | Change |
|-------|------|--------|
| 1 | `spatial-v1.json` | Added `"planner": "layout"` at set level |
| 5 | `capability-v1.json` | G5 `min_signals` adjusted 1→0→1 (restored) |

### `hub/gauntlet.py`
| Slice | Change |
|-------|--------|
| 1 | Reads `planner` from prompt set or per-prompt override |

---

## Key Architectural Decisions

1. **Dual validation layers:** Architecture_compiler catches semantic violations (Camera3D+mesh); validator catches type violations (`_property_matches_type`). Both produce counted errors.

2. **Per-request routing pattern:** The `planner` param follows the `temperature` precedent — threading through `apply_spec` → `_apply_spec_impl` → `run_pipeline`. Components must be eagerly initialized for per-request routing.

3. **Connection guard hierarchy:** B1 (non-3D target) → B2 (unscripted target) → B3 (method doesn't exist, with `_on_{signal}` fallback). Each drop is logged with the guard letter for traceability.

4. **Host-node creation over fallback:** When a system has no matching entity, create a dedicated Node3D rather than fall back to the first entity. This prevents script-overwrite bugs while enabling signal connections.

5. **Informational errors don't block execution:** Validator drops + semantic checks produce errors in `PipelineResult.errors`, but execution proceeds with valid ops. The `not result.errors` guard was removed from `mcp_server.py`.

---

## Slices Progress Summary

| Slice | Description | Status | Impact |
|-------|------------|--------|--------|
| Slice 0 | G4 children fix + probe tab fix | ✅ Done | 85%→90%, 0 broke |
| Slice 1 | Spatial routing to layout planner | ✅ Done | spatial-v1 58%→67%, 0 broke |
| Slice 2 | Edit-op reliability cluster | ✅ Done | 3 scenario fails→passes (15/15) |
| Slice 3 | Capability-v1 re-measurement + G5 deep debug | ✅ Done | G5: 0→6 nodes, G7: 0→25 nodes |
| Slice 4 | G8 adversarial validator improvements | ✅ Done | G8: 67%→100%, aggregate 89%→97% |
| Slice 5 | Host-node creation + signal connection fixes | ✅ Done | Orphaned systems get Node3D hosts |

---

## Lessons

1. **Silent drops hide bugs:** Architecture_compiler guards that silently skip ops prevent errors from flowing to the validator. Remove redundant guards once the validator has equivalent checks.

2. **LLM non-determinism is real at temp 0.2:** G2, G5, and G8 all vary run-to-run. Re-running the gauntlet is the only way to separate code regressions from sampling variance.

3. **Validator parity:** When adding a check to one validator method (`pending` in `_validate_add_node`), check ALL sibling validators that reference the same data.

4. **Python bytecode caching:** `.pyc` files survive service restarts. When hot-reload doesn't pick up a change, delete `__pycache__` and kill the process.

5. **Indentation bugs are silent killers:** The compilation block inside `if inferred:` returned `None` only when `infer_systems` found nothing — a crash that only manifested in prompts without behavior systems.

6. **Per-request overrides need eager initialization:** When a component is only initialized based on global config, per-request overrides silently fail. Initialize eagerly when importable.

7. **Execution guard was too conservative:** `not result.errors` prevented execution on informational validator drops. The validator already filters bad ops; errors are informational.
