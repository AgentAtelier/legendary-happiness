# G4_children Investigation — LLM Hallucination on Gauntlet Prompt

**Date:** 2026-06-15  
**Model:** qwen3-14b-q6-k (chatml template)  
**Gauntlet set:** capability-v1  
**Verdict:** broke (0/10 nodes, 60% coverage)

---

## The failure

G4's prompt asks for a simple scene:

> *"Under /Main create a Node3D named Pickups. Under it create three Area3D nodes named
> P1, P2, P3. Each Area3D must have a CollisionShape3D child with a sphere shape AND a
> MeshInstance3D child with a sphere mesh, each colored differently."*

The execution produced **24 operations, 0 nodes built**, with three errors:

```
Op 24 (connect_signal): target '/root/Main/ScoreLabel' not found
Op 25 (connect_signal): target '/root/Main/ScoreLabel' not found
Op 26 (connect_signal): target '/root/Main/ScoreLabel' not found
```

`ScoreLabel` appears nowhere in G4's prompt. It's from **G7_integration** (the collectible
arena prompt, which runs 3 prompts LATER in the same set).

---

## Hypothesis testing

### Hypothesis A: Stale scene (leftover nodes from previous prompts)

**Tested by:** Code review of `_probe_scene_reset()` in `bench.py`.

**Result: REJECTED.** The gauntlet bounce-reloads the probe scene between every prompt:
1. Writes fresh `probe.tscn` + `probe_bounce.tscn` to disk
2. Opens a throwaway scene first, THEN the probe — forces Godot to actually reload from
   disk (scene_open on an already-active scene is a no-op)
3. Deletes all non-baseline direct children of root
4. Has a safety guard that ABORTS if the active scene isn't the disposable probe scene

The probe-root health check (chain-health) confirms the scene is clean before every run.

### Hypothesis B: B2 same-batch create-then-edit bug

B2 is about create-then-delete/rename in the same `apply_spec` batch. G4's errors are
`connect_signal` to a node that was never created in the prompt.

**Result: REJECTED.** This is a different class of bug — the node shouldn't have been
referenced at all, not just missing in the batch.

### Hypothesis C: Context leak (prior prompts bleeding through DevForge)

The gauntlet runs prompts sequentially, each via a fresh `apply_spec` call. The LLM sees
only: system prompt + current scene tree + user prompt.

**Result: REJECTED.** The scene tree is clean (Main/Camera3D/DirectionalLight3D only).
ScoreLabel doesn't exist in the scene and isn't mentioned in the system prompt.

### Hypothesis D: LLM over-generalization (hallucination)

**Result: ACCEPTED.** The model sees "colored Area3D nodes with collision shapes" and
infers a **collectible object** game pattern. It then auto-generates:
- A scoring UI label (ScoreLabel) — not requested
- Signal connections to wire up scoring — not requested
- A delete for ScriptedCube (which also doesn't exist — context from prior DevForge runs
  that leaked into the model's generation, not the scene)

This is a known LLM behavior: qwen3-14b, when given a game-dev prompt that resembles a
common pattern (collectibles), over-fills the plan with pattern-completion. At low
temperature (0.2 in the persona) it shouldn't do this, but the gauntlet doesn't use the
Odysseus persona's temperature settings.

---

## Plugin logs note

The `plugin_logs` captured for G4 contain MCP traffic from outside G4's execution window
— they show `batch_execute` commands for TestCube, ScriptedCube, WallFront/WallBack, etc.
These are NOT from G4 — they're residual plugin traffic from scene cleanup between prompts.

**Lesson:** `logs_read(plugin, 15)` captures the last 15 plugin messages, which span
multiple operations. For per-prompt isolation, the capture should use a larger window
and filter by timestamp or use the editor's log buffer more carefully.

---

## Fix options (not yet applied)

| Option | Effort | Risk |
|--------|--------|------|
| **Fix the prompt:** Add "Do NOT create any scoring UI, labels, or signal connections" to G4's prompt in `capability-v1.json` | Trivial | None — prompt-only change |
| **Temperature:** Force temperature=0.2 for gauntlet runs (matching the persona) | Small | May affect other gauntlet prompts |
| **Planner guard:** Add a post-plan validation step that rejects operations targeting nodes not in the delta or scene | Medium | Could reject valid operations (e.g. attaching scripts to existing nodes) |
| **Grammar constraint:** Limit planner output to `add_node` + `set_property` only for non-scripting prompts | Medium | Too restrictive — legitimate prompts need script attachment |
| **Context budget:** Lower `DEVFORGE_CONTEXT_TOKEN_BUDGET` from 6000 for gauntlet runs | Small | May degrade legitimate complex-prompt quality |

**Recommendation:** Fix the prompt (option 1) as the immediate mitigation. The grammar
constraint (option 4) is worth considering as a configurable opt-in for simple
create-only prompts, but shouldn't be a blanket change.
