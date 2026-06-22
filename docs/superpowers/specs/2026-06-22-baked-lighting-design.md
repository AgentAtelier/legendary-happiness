# Automated baked lighting — design spec

**Date:** 2026-06-22
**Status:** Design (direction approved in brainstorm) → spec review → `writing-plans`
**Goal:** Generate high-quality global illumination for our scenes **offline, headless, on the
RX 6800**, owning the bake ourselves in Blender — instead of Godot's editor-bound lightmapper or
expensive runtime GI (SDFGI). Lighting becomes a **user-selectable tier**, never a hardcoded tradeoff.

## 1. Why (spike findings)
A headless feasibility spike settled the approach:
- `LightmapGI.bake()` is **editor-only, not scriptable**; `--headless` has **no RenderingDevice**
  (dummy rasterizer); no `xvfb`. → Godot's lightmapper is a **dead end for automation**.
- **Blender Cycles bakes on the GPU via HIP** (`HIP → AMD Radeon RX 6800`, `bpy.ops.object.bake`
  available), headless and scriptable. → We **own the lightmapper in Blender** — the exact "Python/
  Blender builds, Godot lives" pattern, fully deterministic and under our control.
- Today our scenes have **no real GI** (flat ambient + SSAO) — a big part of the washed-out look.

## 2. The tier ladder (user-selectable — the core principle)
Baked-vs-realtime is a fundamental aesthetic + performance tradeoff, so the pipeline **exposes it**
(`brief.lighting_tier` / build-config), it does not choose for the user. One ladder, three rungs:

| Tier | What | Bake cost | Runtime | Dynamic? |
|---|---|---|---|---|
| **0 · realtime** | directional sun + sky + SSIL/SSAO (today's path, tuned) | none | cheap | yes (day/night) |
| **1 · fast / live** | low-sample Cycles bake → **vertex-color** GI + layout-hash cache + idle-server pre-bake | seconds | ~free | direct stays realtime; indirect baked |
| **2 · beauty** | high-sample Cycles bake → **lightmap texture (UV2)** | minutes | ~free | static |

The live-vs-bake tension is resolved by the rungs + **caching**: tier 0 always works live; tier 1's
seconds-bake is content-addressed and **pre-baked by the idle server** (the one we already built), so
repeat layouts are instant; tier 2 is the offline beauty pass.

## 3. Architecture (units + interfaces)
```
compile_exterior_build(brief, seed, lighting_tier)
  tier 0 → emit_exterior_layer (realtime .tscn) — unchanged
  tier 1/2 → lighting_bake.bake_scene(scene_desc, tier) → baked artifacts → emit baked .tscn
```
- **`foundry/lighting_bake.py`** (orchestrator, foundry venv): `bake_scene(scene_desc, *, tier,
  cache_root) -> BakeResult`. Content-addresses the bake (layout + sun + sky + tier), checks the
  cache, else dispatches the Blender bake, returns the baked artifact paths. Pure orchestration —
  testable with a stub baker.
- **`foundry/blender/bake_lighting.py`** (Blender script, headless): given a `scene_desc` (GLB
  placements + sun direction/energy + sky/ambient from the biome), **assembles the scene in Blender**,
  lightmap-unwraps a **UV2** per object, sets the Cycles device to **HIP**, and bakes — **tier 1: the
  indirect/bounce contribution only** into vertex colors (the realtime sun still supplies crisp direct
  light + dynamic shadows) — **tier 2: full Combined (direct+indirect)** into a lightmap texture (fully
  static, top quality) — then exports the baked GLB(s) + lightmap textures. Deterministic (fixed
  Cycles seed + sample count).
- **Godot baked material** (emitter): tier 1 → `StandardMaterial3D` with vertex color modulating
  albedo (`vertex_color_use_as_albedo` + multiply); tier 2 → albedo × lightmap texture sampled on
  UV2. Godot only *renders* the baked result — no runtime GI.
- **Cache + idle server:** reuse `hunyuan_queue`'s content-addressed pattern — a `lighting/` cache
  keyed by the bake hash; the idle server can pre-bake predicted layouts during free GPU time.

### `scene_desc` (the bake contract)
```python
{
  "placements": [{"glb": "res://.../x.glb"|abs, "transform": [...], "static": True}, ...],
  "sun": {"direction": [x,y,z], "energy": float, "color": [r,g,b]},
  "sky": {"top": [r,g,b], "horizon": [r,g,b], "ambient_energy": float},
  "tier": 1|2,
  "texel_density": float,   # tier 2 lightmap resolution knob
  "samples": int,           # Cycles sample count (tier quality knob)
}
```

## 4. Data flow
1. `compile_exterior_build` builds the placements (it already has terrain + flora + building +
   interior manifest) + reads the biome sun/sky → assembles `scene_desc`.
2. tier 0: emit realtime as today. tier 1/2: `lighting_bake.bake_scene` → cache hit returns artifacts;
   miss dispatches `bake_lighting.py` (Blender HIP) → baked GLB/lightmap → cache.
3. Emitter writes the `.tscn` referencing the baked GLB(s) + the baked material; static geometry uses
   baked GI, dynamic objects (player/NPC) fall back to tier-0 realtime + the sky ambient.

## 5. Error handling & fallbacks
- HIP unavailable / bake fails → **fall back to tier 0** (realtime), emit a decision-point note. The
  scene always renders.
- Bake timeout (tier 2 too slow) → degrade to tier 1 samples, note it.
- UV2 unwrap failure on a mesh → that mesh stays realtime (per-object fallback), not the whole scene.

## 6. Testing
- **`lighting_bake` orchestration**: cache hit/miss, content-key determinism, tier routing, fallback
  on bake failure — unit-tested with a stub baker (no Blender).
- **`bake_lighting.py`**: a headless Blender bake of a tiny scene (floor + box + sun) produces a
  lightmap/vertex-colored GLB with **visible directional shading + contact shadow** (assert bake
  changed vertex colors / non-uniform lightmap); deterministic (two runs → identical output).
- **Godot side**: headless-load a baked scene (0 errors); a V visual check comparing tier-0 vs tier-2
  (baked should show real contact shadows / bounce).
- Full `pytest tests/` + the Godot smoke gate green.

## 7. Workstreams (→ implementation plan)
1. `lighting_bake.py` orchestrator + cache + tier routing + fallbacks (foundry, tested).
2. `bake_lighting.py` Blender HIP bake (scene assembly + UV2 + Cycles bake + export).
3. Godot baked-material emission in the exterior emitter + the `lighting_tier` Brief field.
4. Idle-server pre-bake hook + V visual verification.

## 8. Out of scope (YAGNI)
- Dynamic time-of-day on baked tiers (tier 0 owns dynamic lighting).
- Lightmap atlasing across the whole scene into one texture (per-object UV2 first; atlas later only
  if texture count bites).
- Baking specular/reflection probes (diffuse GI first).
