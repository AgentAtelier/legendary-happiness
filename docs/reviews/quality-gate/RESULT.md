# Quality Gate — Live Verification Result

**Date:** 2026-06-17
**Branch:** `feat/quality-gate`
**Commits:** `3a569e0` (gate function), `2203310` (pipeline wiring)

## Test 1: Behavior-implying prompt (should warn)

**Prompt:** `an NPC named Guard that can patrol and attack the player`

**Result:**
- `entities`: 0
- `systems`: 0
- `quality_warnings`:
  - `thin_generation: only 0 op(s) for a 91-word request`
  - `missing_systems: request implies behavior but no systems were planned`

**Journal log:**
```
[pipeline.engine] quality gate: thin_generation: only 0 op(s) for a 91-word request; missing_systems: request implies behavior but no systems were planned
```

✅ **Gate correctly fired warnings on a prompt implying behavior with no systems planned.**

## Test 2: Simple healthy prompt (should NOT warn)

**Prompt:** `Add a red cube named GateSmoke to the scene root`

**Result:**
- `applied`: 4
- `quality_warnings`: `[]`

✅ **No false positive on a simple request.**

## Verdict

The quality gate is live, deterministic, and correctly distinguishes collapse signals from healthy output. It surfaces warnings in both `PipelineResult.quality_warnings` and the apply_spec artifact under the `quality_warnings` key.
