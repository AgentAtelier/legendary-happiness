# Baked Lighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (or subagent-driven-development) to implement task-by-task. Steps use `- [ ]` tracking.

**Goal:** Generate GI for scenes offline via Blender Cycles (HIP), exposed as user-selectable tiers, with the realtime path as fallback.

**Architecture:** A pure-Python orchestrator (`lighting_bake.py`) content-addresses + routes the bake and owns fallbacks; a headless Blender script (`bake_lighting.py`) does the GPU Cycles bake; the exterior emitter gains a baked-material path + a `lighting_tier` field. Cache reuses the `hunyuan_queue` content-key pattern.

**Tech Stack:** Python 3 (foundry venv, trimesh), Blender (Cycles/HIP), Godot 4.7.

## Global Constraints
- Deterministic: fixed Cycles seed + sample count → byte-identical bake for identical `scene_desc`.
- Fallback to tier 0 (realtime) on any bake failure — the scene must always render.
- No new tracked build artifacts; never mutate `asset_lexicon.json`.
- Full `pytest tests/` + the Godot smoke gate must stay green (paste literal result).

---

### Task 1: `lighting_bake.py` orchestrator (foundry, pure-Python)

**Files:** Create `foundry/lighting_bake.py`; Test `foundry/tests/test_lighting_bake.py`

**Interfaces:**
- Produces: `bake_key(scene_desc) -> str`; `bake_scene(scene_desc, *, baker=<callable>, cache_root=None) -> dict` returning `{"tier", "status": "cached"|"baked"|"fallback", "artifacts": [...]}`.
- `baker(scene_desc, out_dir) -> list[str]` is injected (real one calls Blender; tests pass a stub).

- [ ] **Step 1:** Write failing tests: key determinism + varies by sun/tier; tier-0 short-circuits (no bake, status "realtime"); cache hit returns "cached" without calling baker; miss calls baker → "baked" + artifacts cached; baker raising → status "fallback" (tier 0).
- [ ] **Step 2:** Run — expect fail (module missing).
- [ ] **Step 3:** Implement: `bake_key` = `hunyuan_postprocess.content_cache_key`-style hash of `{placements-signature, sun, sky, tier, samples}`; `bake_scene` checks `cache_root/lighting/<key>/`, else calls `baker`, copies artifacts into the cache, catches exceptions → fallback dict.
- [ ] **Step 4:** Run — expect pass.
- [ ] **Step 5:** Commit `feat(lighting): bake orchestrator — content-addressed cache + tier routing + fallback`.

### Task 2: `bake_lighting.py` Blender HIP bake

**Files:** Create `foundry/blender/bake_lighting.py`; Test `foundry/tests/test_bake_lighting.py` (skipif no blender)

**Interfaces:**
- CLI: `blender -b --python bake_lighting.py -- <scene_desc.json> <out_dir> <tier>`.
- Consumes the `scene_desc` (placements/sun/sky/tier/samples); writes a baked GLB (tier 1 vertex colors) or GLB + lightmap PNG (tier 2 UV2).

- [ ] **Step 1:** Write failing test: bake a tiny scene_desc (a floor plane + a box + a sun) at tier 1; assert the output GLB exists and its **vertex colors are non-uniform** (bake produced shading/contact darkening, not a flat fill); a second run is byte-identical (determinism).
- [ ] **Step 2:** Run — expect fail.
- [ ] **Step 3:** Implement: enable HIP (`prefs.compute_device_type='HIP'`, devices on); import/place GLBs (or build primitives from the desc for the test), add a Sun + a World sky from the desc; per object: lightmap UV2 unwrap (`uv.lightmap_pack`/smart_project into a 2nd layer); set Cycles seed + samples; tier 1 → bake `DIFFUSE` with **direct off, indirect on** to a Color Attribute (vertex colors); tier 2 → bake `COMBINED` to an image (UV2) + save PNG; export GLB.
- [ ] **Step 4:** Run — expect pass.
- [ ] **Step 5:** Commit `feat(lighting): Blender Cycles HIP bake — indirect→vertex (t1), combined→lightmap (t2)`.

### Task 3: Godot baked-material emission + `lighting_tier` field

**Files:** Modify `foundry/exterior_compiler.py`, `foundry/brief.py`; Test `foundry/tests/test_exterior_compiler.py`, `foundry/tests/test_brief_exterior.py`

**Interfaces:**
- Consumes Task 1's `bake_scene`. `compile_exterior_build(..., lighting_tier=0)`; brief carries `lighting_tier` (0/1/2, default 0).

- [ ] **Step 1:** Write failing tests: brief validate normalizes `lighting_tier` (default 0, clamp to {0,1,2}); `compile_exterior_build(brief, seed, lighting_tier=0)` still emits the realtime scene (unchanged); with a stub bake returning a baked GLB, tier 1 emits a node referencing the baked GLB + a `vertex_color_use_as_albedo`-style material.
- [ ] **Step 2:** Run — expect fail.
- [ ] **Step 3:** Implement: add `lighting_tier` to `brief.minimal`/schema/`validate_brief`; in `compile_exterior_build`, tier 0 = current path; tier 1/2 = assemble `scene_desc` from the placements + biome sun/sky, call `lighting_bake.bake_scene`, emit the baked GLB refs + baked material (tier 1 vertex-color material; tier 2 lightmap UV2 material); fallback tier → realtime.
- [ ] **Step 4:** Run — expect pass.
- [ ] **Step 5:** Commit `feat(lighting): lighting_tier brief field + baked-material emission in exterior build`.

### Task 4: Idle-server pre-bake hook + V verification

**Files:** Modify `foundry/hunyuan_worker.py` or add `foundry/lighting_prebake.py`; Test as appropriate

- [ ] **Step 1:** Write failing test: a lighting job spec enqueued via `hunyuan_queue` is drained by a `bake` infer-fn that writes the lighting cache (reuse the worker/queue with a lighting job type).
- [ ] **Step 2-4:** Implement a thin lighting-job path so the idle server pre-bakes queued layouts; verify cache populated.
- [ ] **Step 5:** Commit. Then a manual V visual check: render tier-0 vs tier-2 of one scene, confirm baked shows real contact shadows/bounce.

## Self-Review
- Spec coverage: Task 1↔§3 orchestrator+cache+fallback; Task 2↔§3 bake_lighting; Task 3↔§3 emitter+tier field; Task 4↔§7.4 idle pre-bake + §6 V check. ✓
- Types consistent: `bake_scene`/`bake_key`/`scene_desc` keys match the spec's §3 contract. ✓
- No placeholders; each code step names the concrete Blender/Godot operation.
