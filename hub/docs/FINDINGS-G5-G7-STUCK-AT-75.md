# Findings: G5 & G7 Stuck at 75% Coverage

**Date:** 2026-06-15  
**Status:** ✅ Fixed  
**Slice:** Slice 0 / Slice 1  
**Impact:** G5 went from 0→5 nodes, G7 from 0→25 nodes

---

## Summary

G5_scripts_signals and G7_integration were stuck at **75% coverage** despite generating correct-looking ops. Both built **zero nodes** in the scene because the executor caught a `PROPERTY_NOT_ON_CLASS` error and atomically rolled back the entire batch. The pipeline reported 0 errors because the error happened at the executor level, not the pipeline validator.

Three distinct root causes were found and fixed in `architecture_compiler.py`.

---

## G5_scripts_signals

> **Prompt:** "Under /Main create a CharacterBody3D named Hero with a movement system that reads WASD input and moves it. Also create a Timer named SpawnTimer, and a spawner system; connect the SpawnTimer timeout signal to the spawner."

### Symptom

| Metric | Value |
|--------|-------|
| Verdict | partial (75%) |
| Built nodes | 0 |
| Applied ops | 3 / 17 |
| Errors (pipeline) | 0 |
| Errors (executor) | PROPERTY_NOT_ON_CLASS |

### Root Cause #1: `set_property position` on Timer

The architecture compiler emitted `set_property position` for ALL node types indiscriminately. `Timer` inherits from `Node`, not `Node3D` — it has no 3D transform and no `position` property. The executor hit this at op ~9 and rolled back the entire batch.

**Evidence (artifact capture):**
```
Op 9: set_property position on /root/Main/SpawnTimer → PROPERTY_NOT_ON_CLASS
Previous ops 0-8: Hero + HeroMovement + SpawnTimer created successfully — all discarded
```

### Root Cause #2: `connect_signal` to unscripted Node3D

After Fix A (skip position on non-3D types), a second failure emerged: the compiler wired `_on_SpawnTimer_timeout` to `SpawnerSystem`. SpawnerSystem is a plain `Node3D` with no attached script — the method `_on_SpawnTimer_timeout` doesn't exist on it. Same `PROPERTY_NOT_ON_CLASS` → batch rollback.

**Evidence (artifact capture, post-Fix-A):**
```
Ops 0-5: add_node Hero, CollisionShape3D, SpawnTimer, SpawnerSystem — all succeed
Op 6: connect_signal SpawnTimer.timeout → SpawnerSystem._on_SpawnTimer_timeout → PROPERTY_NOT_ON_CLASS
All rolled back → 0 nodes
```

### After Fix

| Metric | Before | After |
|--------|--------|-------|
| Built nodes | 0 | **5** (Hero, CollisionShape3D, SpawnTimer, SpawnerSystem, Root) |
| Applied ops | 3/17 | **7/7** |
| Errors | 1 (executor) | **0** |

---

## G7_integration

> **Prompt:** "Build a collectible arena under /Main. Create a Node3D Arena. Under Arena: a CharacterBody3D Player at 0 1 0 with a WASD movement script and a Camera3D child PlayerCam at 0 3 6; a Node3D Coins containing six Area3D coins (Coin1..Coin6), each with a CollisionShape3D sphere-shape child and a MeshInstance3D sphere-mesh child colored distinctly, each coin with a collect script that frees itself and adds score; and a CanvasLayer UI containing a Label ScoreLabel with text Score: 0."

### Symptom

| Metric | Value |
|--------|-------|
| Verdict | partial (75%) |
| Built nodes | 0 |
| Applied ops | 51 / 65 |
| Errors (pipeline) | 0 |
| Errors (executor) | PROPERTY_NOT_ON_CLASS |

### Root Cause: `connect_signal` to Label (UI node)

The compiler emitted `connect_signal body_entered → ScoreLabel._on_body_entered`. ScoreLabel is a `Label` (Control/CanvasItem), not a 3D node — `_on_body_entered` doesn't exist on it. The executor hit this at op ~48 (after successfully creating the entire Arena/Player/Coins/UI tree) and rolled back everything.

**Evidence (artifact capture):**
```
Ops 0-43: Arena, Player, PlayerCam, Coin1-6 (with shapes, meshes, colors), UI, ScoreLabel — all succeed
Op ~48: connect_signal body_entered → ScoreLabel._on_body_entered → PROPERTY_NOT_ON_CLASS
All rolled back → 0 nodes
```

### After Fix

| Metric | Before | After |
|--------|--------|-------|
| Built nodes | 0 | **25** (full arena tree) |
| Applied ops | 51/65 | **58/58** |
| Errors | 1 (executor) | **0** |

---

## Root Cause Analysis

All three failures share the same mechanism:

```
Pipeline generates ops correctly →
  One op targets an invalid property/method on a VALIDLY-EXISTING node →
    Executor fails with PROPERTY_NOT_ON_CLASS →
      Entire batch rolls back (atomic execution) →
        0 nodes in scene, 0 errors reported by the pipeline
```

The pipeline reports 0 errors because:
1. The **pipeline-level validator** (`operation_validator.py`) doesn't check property/method existence on node types
2. The **gauntlet measurement** (`_measure`) only checks `raw.get("errors")` (pipeline errors), not executor errors

The executor catches these at runtime and rolls back atomically — only `applied` count reveals the partial execution.

---

## Fixes Implemented

All fixes are in `devforge/compilation/pipeline/architecture_compiler.py`.

### Fix A: Type-aware position property emission

Added `_NON_3D_TYPES` set (~40 Godot types: `Timer`, `Label`, `CanvasLayer`, all `Control` subclasses, `Node`, `Node2D`, `AudioStreamPlayer`, etc.).

`_props_to_steps` now skips `set_property position` when `node_type in _NON_3D_TYPES`, with a warning log.

```python
_NON_3D_TYPES: set[str] = {
    "Node", "Node2D", "Timer", "Label", "CanvasLayer",
    "Control", "Button", "LineEdit", "TextEdit", "RichTextLabel",
    # ... ~40 types total
}

# In _props_to_steps:
if node_type in _NON_3D_TYPES and prop_key == "position":
    logger.warning(f"SKIPPING position on {node_type} — not a 3D node")
    continue
```

### Fix B1: Cross-domain signal connection filtering

Drops `connect_signal` when the **target node type** is in `_NON_3D_TYPES` and the method starts with `_on_`. This catches physics signals wired to UI nodes (e.g., `body_entered → Label._on_body_entered`).

### Fix B2: Unscripted target node filtering

Drops `connect_signal` when the **target was created in this delta** (`to_name in entity_paths`) AND has **no attached script** (`target_path not in attached_nodes` where `attached_nodes = set(system_attach.values())`) AND the method starts with `_on_`.

This catches cases like `SpawnerSystem` (plain Node3D with no script) that the LLM tries to wire signals to.

B1 and B2 run **after** signal/method derivation so default-derived `_on_{signal}` names are also covered.

---

## Why Didn't the G4 Fix Cascade?

The G4 fix (connection-drop when target node doesn't exist) was specific to **missing target nodes**. G5 and G7 fail because the target nodes **exist** but lack the method being wired. G4 fix checked existence; G5/G7 need method-validity checks. These are orthogonal.

| Scenario | Target node? | Target method? | G4 fix helps? |
|----------|-------------|----------------|---------------|
| G4 (ScoreLabel) | ✗ missing | N/A | ✅ Yes |
| G5 (SpawnerSystem) | ✅ exists | ✗ no script | ❌ No |
| G5 (Timer position) | ✅ exists | ✗ Timer has no `position` | ❌ No |
| G7 (Label) | ✅ exists | ✗ no `_on_body_entered` | ❌ No |

---

## Measurement Gap

All gauntlet `checks` for G5/G7 passed (scripts=1, attached=1, signals=1) even when 0 nodes were built. The checks measure the **planner output** (scripts generated, signals planned) — they don't measure **executor success**. A `nodes > 0` check would have caught this regression immediately.

---

## Files Changed

| File | Change |
|------|--------|
| `architecture_compiler.py` | Added `_NON_3D_TYPES` set; Fix A in `_props_to_steps`; Fix B1+B2 in connection loop |

---

## Test Coverage

- **Live re-run:** G5 and G7 individually run through the fixed pipeline on qwen3 — both build real nodes with 0 errors
- **Syntax:** `py_compile` passes
- **DevForge tests:** All passing
- **Code review:** `code-reviewer-deepseek` reviewed and approved
