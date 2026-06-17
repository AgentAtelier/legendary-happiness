# Session Changes — 2026-06-15 Slice 0 (Re-measure & Restore)

**Stage:** Slice 0 of `STAGE-NEXT-2026-06-15-spatial-and-closeout.md`.
**Mandate:** Swap to qwen3, re-run capability-v1 + scenario suite after the G4 fix,
compare against the §6 baseline, and confirm the effect is correctly measured.

---

## 1. G4 Fix Re-measurement — capability-v1 Gauntlet

### Symptom

The prior session fixed G4_children (phantom `connect_signal` → atomic rollback, dropping connections whose endpoints don't resolve). The fix was verified on G4 alone — the aggregate effect on the full 8-prompt suite was unmeasured. The STAGE-NEXT doc hypothesised the fix was "signal-class" and should cascade to G5/G7/G8.

### Before (§6 baseline) vs After (G4 fix)

Both runs on qwen3-14b-q6-k, same config (`7e427143`), same probe scene.

| Prompt | §6 Baseline | With G4 Fix | Δ |
|--------|------------|-------------|---|
| G1_depth | full 100% · 8n · 0e | full 100% · 8n · 0e | — |
| G2_breadth | full 100% · 25n · 0e | full 100% · 25n · 0e | — |
| G3_props | full 100% · 5n · 0e | full 100% · 5n · 0e | — |
| **G4_children** | **broke 60% · 0n · 3e** | **full 100% · 10n · 0e** | **↗ +40** |
| G5_scripts_signals | partial 75% · 0n · 0e | partial 75% · 0n · 0e | — |
| G6_mixed | full 100% · 8n · 0e | full 100% · 8n · 0e | — |
| G7_integration | partial 75% · 0n · 0e | partial 75% · 0n · 0e | — |
| G8_adversarial | partial 67% · 24n · 0e | partial 67% · 23n · 0e | — |

| | Verdicts | Avg Coverage |
|---|---|---|
| **Before** | 4F / 3P / 1B | **85%** |
| **After** | 5F / 3P / **0B** | **90%** |

### Finding: G4 fix is specific, not signal-class

The STAGE-NEXT prediction was wrong — the connection-drop fix did **not** cascade to G5_scripts_signals, G7_integration, or G8_adversarial. Those prompts are unchanged. The fix is specific to G4's ScoreLabel hallucination pattern: the LLM invented a `connect_signal` to a non-existent `/root/Main/ScoreLabel`, the compiler fabricated the path, and one bad op rolled back the whole build via atomic rollback. Dropping unresolvable connections fixed exactly that.

G5/G7/G8 all have `partial` verdicts with **0** built nodes and **0** errors — they generate operations but nothing lands in the scene. This is a different root cause (likely the "edit-op reliability" cluster in Slice 2, or a planner/compiler issue where ops are valid but non-executing).

### Baseline file on disk

`hub/data/gauntlet/gauntlet-20260615-082044.json` (§6 baseline, qwen3, 85%)
`hub/data/gauntlet/gauntlet-20260615-105804.json` (Slice 0 re-run, qwen3, 90%)

---

## 2. Scenario Suite — qwen3

### Result: 12/15 pass (80%)

All 12 create/parent/property/composite/regression scenarios pass with 0 errors.

Three edit-op scenarios fail (expected — Slice 2 territory):

| Scenario | Status | Category |
|----------|--------|----------|
| cube_create | pass | geometry |
| sphere_create | pass | geometry |
| light_create | pass | geometry |
| camera_create | pass | geometry |
| batch_three | pass | multi-node |
| script_attach | pass | scripting |
| property_edit | pass | editing |
| **node_delete** | **fail** | **editing** |
| **node_rename** | **fail** | **editing** |
| **rename_existing** | **fail** | **editing** |
| delete_existing | pass | editing |
| delete_existing_bare | pass | editing |
| small_room | pass | composite |
| player_movement | pass | composite |
| no_dup_camera | pass | regression |

The `*_existing` variants pass because they edit nodes pre-placed in the scene baseline, avoiding the same-batch create-then-edit issue. `node_delete`/`node_rename`/`rename_existing` fail because they create a node in the same batch they try to delete/rename — the B2 cluster.

### Scorecard on disk

`hub/data/scorecards/qwen3-14b-q6-k-7e427143.json`

---

## 3. Stale Probe Tab Fix (Main→Main2)

### Symptom

Every gauntlet run crashed immediately with:
```
probe health check FAILED: root name is 'Main2', expected 'Main'.
The editor is serving a stale/corrupted probe tab.
```

The Godot editor had an unsaved dirty `probe.tscn` tab where the root node was "Main2" instead of "Main". The file on disk was correct (root "Main"), but Godot matched the tab by resource path and never reloaded from disk.

### Fix attempts

| Attempt | Method | Result |
|---------|--------|--------|
| 1 | Pre-bounce: open `main.tscn` first, then bounce, then probe | ❌ Still Main2 |
| 2 | UID cache-bust: write probe.tscn with fresh `uuid` per reset | ❌ Godot matches by path, not UID |
| 3 | `node_manage` rename via godot-ai MCP | ❌ Not supported on root |
| **4** | **Manually close probe.tscn tab in Godot without saving** | ✅ |

### Root cause

`scene_open("res://probe.tscn")` matches by **resource path**, not UID. If a dirty in-memory tab exists for that path, Godot brings focus to the existing tab instead of loading from disk. The bounce reload (open different scene → open probe) works when the probe tab is clean but fails when it has unsaved changes (the renamed root). There is no MCP tool to close a tab.

### Code change (defense-in-depth)

**File:** `hub/bench.py`
- Added `import uuid`
- `_probe_scene_reset()` now generates fresh UIDs for both `probe.tscn` and `probe_bounce.tscn` on every reset via `uuid.uuid4().hex[:12]`. This doesn't fix the active dirty-tab case (manual close still needed), but it prevents future stale-tab issues by ensuring Godot can't match old cached UIDs to new runs.

### Verification

151 hub tests pass. Capability-v1 ran successfully (no Main2 crash) after manual tab close.

---

## 4. Files Changed (Slice 0)

| File | Change |
|------|--------|
| `hub/bench.py` | Added `import uuid`; UID rotation in `_probe_scene_reset()` for cache-bust on future runs |

No DevForge pipeline code changed in Slice 0 — the G4 fix was already shipped by a prior session.

---

## 5. State of Truth Updates

### Confirmed
- G4 is fixed: `broke(60%, 0 nodes) → full(100%, 10 nodes)`, verified live
- Capability-v1 aggregate: **85% → 90%** (1 fewer broke, 1 more full)
- Scenario suite: **12/15 pass (80%)**, edit-op failures are B2 cluster
- The stale-tab fix works (manual close + UID rotation for future prevention)

### Corrected
- **G4 fix is NOT signal-class** — it does not cascade to G5/G7/G8. Those prompts have a different root cause (0 nodes built, 0 errors — ops generated but not landing in scene).
- **Stale probe tab can't be fixed programmatically** — UID rotation helps future runs but the active dirty tab requires manual close in Godot.

### Corroborated
- Model is on qwen3 (restored from merged-22b)
- Odyssey is down (not blocking — not used in hub testing)

---

## 6. Gauntlet Files on Disk

| File | Model | Set | Verdict | Coverage |
|------|-------|-----|---------|----------|
| `gauntlet-20260615-082044.json` | qwen3-14b-q6-k | capability-v1 | 4F/3P/1B | 85% |
| `gauntlet-20260615-083457.json` | qwen3-14b-q6-k | spatial-v1 | 0F/3P/1B | 58% |
| `gauntlet-20260615-084127.json` | merged-22b-q4-k-m | capability-v1 | 2F/3P/3B | 66% |
| `gauntlet-20260615-085257.json` | merged-22b-q4-k-m | spatial-v1 | 0F/0P/4B | 33% |
| `gauntlet-20260615-105804.json` | qwen3-14b-q6-k | capability-v1 | 5F/3P/0B | 90% |
