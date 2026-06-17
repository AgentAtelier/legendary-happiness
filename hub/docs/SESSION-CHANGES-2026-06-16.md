# SESSION-CHANGES-2026-06-16 — Polish (Roadmap Slices A–D) + UI Recovery

**Date:** 2026-06-16
**Scope:** Hub UI recovery, spatial measurement fix, and the A–D polish from
`STAGE-PLAN-2026-06-15-A-to-F.md`. **All code changes verified by `py_compile`
+ the DevForge unit suite (377 passed). Live gauntlet/scenario runs are the
human's to run — see the handoff at the bottom.**

---

## 0. Hub UI recovery (pre-requisite — the panel was dead)
Three separate frontend breakages from the dead-tab cleanup, each fatal to the
whole script (a JS parse/runtime error kills every handler):
1. **~20 `let _b=$(...)` at one scope** → `let` redeclaration SyntaxError. Fixed → `var`.
2. **Dead stability-render fragment** sitting where `loadPersistentHistory()`'s
   header belonged (orphaned `} catch`). Fixed → restored the function header.
3. **`tab-models` panel deleted** but Models is a *live* tab → top-level
   `getElementById('modelsTable').addEventListener` was `null.addEventListener`,
   aborting block 1 (the swap handler). Fixed → restored the panel + guarded the listener.
- Also hardened `hub.py:api_scenarios_run` to return `400` (not an unhandled
  `500`) on a bad/empty JSON body, mirroring `api_shootout`.
- Verified: both `<script>` blocks `node --check` clean; 6 nav tabs ↔ 6 panels.

## 1. Slice A — spatial is real AND correctly measured
- **Root cause of the 67%/0-full spatial score: a measurement bug, not routing.**
  Verified from `gauntlet-20260615-231900.json`: the layout planner built a real
  greybox kitchen (`/Main/Kitchen/{Counter,Fridge,Stove,Table}`, each container +
  MeshInstance3D + CollisionShape), **30/30 ops, 0 errors**. Routing works.
- **Fix (`hub/gauntlet.py:_add_spatial_checks`):** a "placed asset" is now a
  *positioned node that is, or is the parent of, a MeshInstance3D* — was: only
  meshes positioned *directly*, which scored the layout pattern (mesh parented
  under a positioned container) as 0/3. Back-compatible with the arch path.
- **Deferred (correctly):** the *harder* placement-correctness eval (north-wall
  items actually on the north wall, etc.) is held until the re-measure confirms
  ~100% — adding stricter checks now would confound the fix's confirmation.

## 2. Slice D — position/transform validation consolidated (one source of truth)
- `position` is a **denylist** problem, not an allowlist one (the set of types
  *with* a transform is huge; the transform-less set is small). Cramming it into
  `PROPERTY_ALLOWLIST` would over-block 2D/Control.
- **`knowledge/scene/godot_node_types.py`:** added canonical
  `NODES_WITHOUT_VECTOR3_TRANSFORM` + `VECTOR3_TRANSFORM_PROPS`; taught
  `_property_matches_type` to reject transform props on transform-less nodes
  (returns `False`), pass through on spatial/unknown (`None`).
- **`compilation/pipeline/architecture_compiler.py`:** now *imports* that set as
  `_NON_3D_TYPES` (deleted the divergent local literal). The validator already
  routes `set_property` through `_property_matches_type`, so position is now
  enforced in **one** place and both layers agree.

## 3. Slice B — reverse host-node (stub for script-less signal targets)
- Mirror of the forward host-node (system→no-entity → Node3D host). When a
  connection targets a same-delta entity with **no script** (the old B2 *drop*),
  the compiler now **synthesizes a stub** defining the handler with the correct
  signature for the signal, attaches it, and lets the connection wire.
- **Bounded risk:** only stubs when the signal's handler signature is known
  (`_SIGNAL_HANDLER_ARGS`: body_entered/timeout/pressed/…); otherwise keeps the
  safe B2 drop (a wrong signature is worse than a missing wire). Helper:
  `_generate_signal_stub`. B3 re-validates the stub before the wire is emitted.
- G5 already passes on qwen3-6-27b via the forward host-node; this hardens the
  residual case independent of model.

## 4. Slice C — edit-op reliability
- **B2** is now *handled* by §3 (stub instead of drop) rather than a standalone fix.
- **Resolver** (`_resolve_node_target` punctuation-strip + token-match) is
  implemented + unit-tested but still needs **live** validation under a model.
- **B1 truncation / thinking-config A/B** is a *config experiment* for the human
  (the 27B's `llama.nothink` + `llama.chat_content` health fails point here):
  toggle `enable_thinking:false`, re-run health + edit-op scenarios, compare. Not
  applied as a default — present the data first.

## 5. Test hygiene
- Rewrote 3 stale tests (`test_compiler_skips_{mesh,color,shape}_on_light`) that
  asserted the **removed** Slice-4 compiler-skip behavior; they now assert the
  current validator-level guarantee (`test_validation_rejects_*_on_light`).
- Added Slice-B/-D unit tests (transform denylist, shared-set identity, stub gen).
- **DevForge unit suite: 377 passed, 0 failed.**

---

## HANDOFF — please run (off-clock), then paste back
DevForge code changed → restart it (clear bytecode first); hub code changed → restart it.
```bash
find /home/mrg/dev/games/Forge/devforge_review_package -name __pycache__ -type d -prune -exec rm -rf {} +
systemctl --user restart forge-devforge forge-hub
```
Then, from the hub Testing tab (current model = qwen3-6-27b):
1. **`spatial-v1`** → expect S1–S4 to flip partial→**full (~100%)**. Confirms the §1 fix.
2. **`capability-v1`** → expect **100% (8F/0P/0B)** held — watch G5/G7 for any regression from the §3 reverse host-node.
3. **edit-op scenarios** (`node_delete`, `node_rename`, `*_existing`) → confirms the resolver + B2 stub live.

> Next stages after this lands: **Spatial Generation Architecture Phase 1**
> (Lexicon/ARCS/Patterns/Compiler — partly already built), then the **×10 /
> multi-model testing harness** (`SPATIAL-GENERATION-ARCHITECTURE.md` §5).
