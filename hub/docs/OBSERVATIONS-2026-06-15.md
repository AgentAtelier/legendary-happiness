# OBSERVATIONS-2026-06-15 — Ideas, Gaps, and Forward-Looking Notes

**Date:** 2026-06-15
**Context:** Post-session reflections after completing Slices 0–5 on the DevForge pipeline / Forge Hub.

---

## Architecture Observations

### 1. Dual Validation Layers Are Powerful

The session evolved a two-layer validation pattern:
- **Compiler layer (architecture_compiler):** Semantic checks (Camera3D+MeshInstance3D, orphaned systems → host-node creation)
- **Validator layer (validator.py):** Type checks (`_property_matches_type`, `PROPERTY_ALLOWLIST`)

These complement each other. The compiler catches semantic wrongness (camera shouldn't have mesh children); the validator catches type wrongness (mesh property invalid on Camera3D). Both produce counted errors that flow into `PipelineResult.errors`.

**Pattern:** When adding a new check, ask: is this type-level (validator) or semantic-level (compiler)? Put it in the right layer.

### 2. Informational Errors Shouldn't Block Execution

The old `not result.errors` guard in `mcp_server.py` was the single biggest false-failure source. It meant ANY error — even a single validator dropping one bad op — would skip ALL valid ops. Changing to `if result.operations:` (execute whenever there are valid ops) fixed this.

**Lesson:** The validator's job is to filter bad ops. The remaining ops are valid. Execution should always proceed with valid ops.

### 3. Connection Guard Hierarchy (B1→B2→B3) Works Well

The three-tier connection drop system is clear and debuggable:
- **B1:** Target is non-3D type (Label can't handle `body_entered`)
- **B2:** Target is unscripted same-delta entity
- **B3:** Method doesn't exist in target's script, with `_on_{signal}` fallback

Each drop is logged with the guard letter for traceability. The B3 fallback is a nice touch — the LLM often over-specifies method names (`_on_SpawnTimer_timeout` instead of `_on_timeout`), and falling back to the signal-derived default name makes connections work without manual fixes.

### 4. Host-Node Creation Over Fallback

The old `_find_attach_target` Strategy 3 (fallback-to-first-entity) caused silent script-overwrite bugs. The new approach — create a dedicated Node3D host for orphaned systems — is safer AND enables signal connections. But it only handles one direction (system → no entity). The reverse case (entity → no system, e.g., LLM creates "SpawnerLogic" as entity with no matching system) is still unhandled.

---

## Known Gaps

### 1. Ghost Parent Detection (G8)

**Problem:** The LLM "helpfully" creates Ghost as an entity when the prompt says "child of a node named Ghost." This makes the parent reference valid — no error is produced.

**Challenge:** Distinguishing legitimate parent containers (Arena in G7) from fabricated parents (Ghost in G8) requires understanding prompt intent. Options:
- Flag entities with no props AND referenced only as parents (weak signal)
- Compare entity names against the prompt's standalone noun phrases (complex)
- Just accept that fabricated parents are a minor issue and focus elsewhere

**Priority:** Low — G8 already passes with 2 errors from the Camera3D checks.

### 2. Position Allowlist Missing

**Problem:** The validator's `PROPERTY_ALLOWLIST` doesn't have a `position` entry. The compiler's `_NON_3D_TYPES` guard is the only protection against `set_property position` on Timer/Label/etc.

**Fix:** Add `position` to `PROPERTY_ALLOWLIST` with the complement of `_NON_3D_TYPES`. But the complement set is large (~50+ 3D types). Maybe use a wildcard pattern: anything ending in "3D" + Node3D itself.

**Priority:** Medium — the compiler guard works, but moving it to the validator would consolidate validation in one place.

### 3. G5 Signal Connection Stability

**Problem:** G5's signal count varies from 0 to 1 across gauntlet runs due to LLM non-determinism. The pipeline correctly handles the signal when the LLM emits compatible entity/system names. But when names diverge ("SpawnerLogic" entity with no system), the connection is dropped.

**Fix:** When a connection targets an unscripted entity (B2 would drop it), auto-create a stub script + attach it instead of dropping. This handles the reverse case of the host-node fix.

**Priority:** Medium — G5 is the last partial at 75%. Fixing this would push the gauntlet toward 100%.

### 4. Reverse Host-Node (Entity → System)

**Sibling to Gap #3:** The host-node fix creates a node when a system has no entity. The reverse — create a system when an entity is targeted by a signal connection — is not implemented. The B2 "+ auto-create stub" approach would address both.

---

## LLM Non-Determinism

### qwen3-14b at temp 0.2 is Still Non-Deterministic

Observed across multiple gauntlet runs:
- **G2_breadth:** Flips between full 100% and partial 67% with identical 25 nodes (coverage model issue, not code)
- **G5_scripts_signals:** Entity names vary ("Spawner" vs "SpawnerLogic"), system counts vary, connection targets vary
- **G8_adversarial:** Sometimes creates BadCamMesh as child, sometimes as `set_property mesh`

**Implications:**
- Single gauntlet runs are snapshots, not definitive measurements
- Running 3x and taking mean ± stddev gives a truer picture
- "Regressions" in a single run may be sampling noise, not code bugs
- This is a qwen3 limitation — temp 0.2 should be more deterministic

### Mitigation Strategies

1. **Run gauntlet 3x and report mean ± stddev per prompt**
2. **Add deterministic pre-passes** (like the delete/rename pre-pass) for more prompt patterns
3. **Use inference providers with lower temperature floors** (some cap at 0.1 or 0.05)
4. **Accept non-determinism as a feature** — the pipeline should be robust to varied LLM output

---

## Code Quality Observations

### 1. `.pyc` Caching Is a Persistent Pain Point

Multiple sessions hit "my code change didn't take effect" because Python bytecode was cached. Clearing `__pycache__` before every service restart is now muscle memory. A startup script that auto-clears would help.

### 2. Indentation Bugs Are Hard to Spot

The compilation-block-inside-`if inferred:` bug went undetected until the gauntlet ran G8 (which has no systems → `inferred` empty → function returned `None`). Python's significant whitespace makes these bugs invisible in code review. A linter or `pyflakes` check for unreachable code after `if` blocks might catch these.

### 3. `_re` Scope Is Confusing

`import re as _re` inside a method body means `_re` is only available in that method's scope. B3, semantic checks, and other class methods hit `NameError: name '_re' is not defined`. Solution: import `re` at module level or use a local import at each usage site.

### 4. Architecture_compiler Is Getting Large

The `compile()` method in `architecture_compiler.py` now handles: entity creation, system+script+attach, rename/remove markers, signal connections, semantic validation, and host-node creation. This is ~400 lines in one method. Consider extracting:
- Signal connection logic into a `_compile_connections()` method
- Semantic validation into a `_validate_semantics()` method
- Host-node creation into a `_create_host_for_system()` method

---

## Gauntlet Improvement Ideas

### 1. Multi-Run Mode

Add `--runs 3` flag to `run_gauntlet()` that runs the set N times and reports mean ± stddev per prompt.

### 2. Coverage Model Refinement

The current coverage model is: `checks_passed / total_checks * 100`. This is binary per-check. Consider:
- **Weighted checks:** nodes might be more important than signals
- **Partial credit:** 5/25 nodes = 0% in binary, but 20% in partial credit
- **Saturation curves:** Some checks should saturate (e.g., nodes beyond min_nodes don't add value)

### 3. spatial:assets Check Fix — ✅ FIXED 2026-06-16

**This prediction was correct.** The `spatial:assets` check only counted MeshInstance3Ds that were
positioned *directly*. The layout/SpatialCompiler path positions the furniture **container**
(`Counter`) and parents the mesh (`CounterMesh`) under it at local origin — so a correctly-built
kitchen scored **0/3** and spatial-v1 sat at 67% (0F/4P) despite 30/30 ops and 0 errors. **Fixed**
in `gauntlet.py:_add_spatial_checks`: a placed asset is now a positioned node that *is, or is the
parent of,* a MeshInstance3D (back-compatible with the arch path's directly-positioned meshes).
Re-measure pending to confirm ~100%.

### 4. Historical Trend Dashboard

The gauntlet results are JSON files in `data/gauntlet/`. A simple script that plots coverage over time (per-prompt and aggregate) would make progress visible. Could be a `--trend` CLI flag.

---

## Future Work Ideas

### High Priority
- **Run gauntlet 3x** to measure LLM non-determinism variance
- **Auto-create stub for unscripted targets** (reverse host-node, fixes G5 residual)
- **Add position to PROPERTY_ALLOWLIST** (consolidate validation)

### Medium Priority
- **Extract compile() sub-methods** (code organization)
- **Fix spatial:assets measurement gap** (layout path coverage)
- **Ghost fabricated-parent detection** (G8 hardening)

### Low Priority
- **Multi-run gauntlet mode** (--runs N flag)
- **Coverage model refinement** (partial credit, weighted checks)
- **Historical trend dashboard** (progress visualization)
- **Pyflakes/linter integration** (catch indentation bugs, unused imports)

---

## Things That Went Well

1. **Slice-by-slice progress tracking** made the session manageable. Each slice had a clear goal, clear before/after, and its own documentation.
2. **Full artifact capture for debugging** (debug_g5.py, debug_g8.py) was essential for root-causing LLM-influenced failures.
3. **Code-reviewer on every change** caught the Ghost gap, the `_re` scope issue, the indentation bug, and the live-scene script-overwrite concern.
4. **Validator + compiler dual layer** emerged naturally from the fixes and is a solid architectural pattern.
5. **Connection guard hierarchy (B1→B2→B3)** is self-documenting and easy to extend.
