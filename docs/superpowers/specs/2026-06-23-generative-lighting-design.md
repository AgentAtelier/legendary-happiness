# Generative Lighting — Design Spec

**Date:** 2026-06-23
**Thread:** Lighting (post interior-shell). Makes the enclosed interior readable *and* atmospheric
via scene-motivated light sources, a proper realtime rig, and the (already-built but disconnected)
Cycles baked-GI tiers.

**Goal:** A deterministic lighting planner derives motivated light sources (hearth, wall torches,
candle/lantern points, windows) from the Brief + room + manifest; those feed (a) shell window
openings, (b) the realtime Godot light rig (tier-0 floor), and (c) the Cycles GI bake (quality
tier). The "dusk stone keep" reads as atmospheric but navigable instead of near-black.

End artifact: this spec → implementation plan → CLI-AI sprint.

---

## Context / why

The king-post truss shell now **encloses** the room, blocking the sun, so the interior is lit only
by 2 weak `OmniLight3D`s (energy 1.2) + dark ambient (0.4) + dark fog + an aggressive filmic
tonemap → near-black. Separately, the Phase-1 baked-GI system (`foundry/lighting_bake.py`,
`foundry/blender/bake_lighting.py`, 3 tiers, content-addressed cache, degrades to tier 0) is built
but **not wired** into the quest/scene pipeline (no references in `scene_compiler`/`scaffold`).
`bake_lighting.py` currently models only **sun + sky** — no interior emitters.

## Locked decisions (from brainstorm)

- **Full generative lighting**: motivated light *sources* + realtime rig + baked-GI tier.
- **Interior + windows**: hearth, wall torches, candle/lantern points, AND window openings in the
  shell with dusk/moonlight shafts.
- **A dedicated deterministic `lighting_planner`** is the single source of truth; the LLM influences
  only via the Brief. Lights are not LLM-emitted.
- **Build-order change**: the lighting plan is computed **before** the shell, because windows in the
  plan drive shell openings.

## Architecture & build order

```
Brief + room_size + manifest
   → lighting_planner.plan_lighting(...) -> LightingPlan
        ├─→ build_room_shell(..., windows=plan.windows)      # cuts wall openings
        ├─→ scene_compiler: realtime light nodes + Environment (tier-0 floor)
        └─→ lighting_bake.bake_scene(scene_desc)             # GI quality tier
```

```
foundry/lighting_planner.py   # NEW: LightingPlan + plan_lighting(brief, room_size, manifest, seed)
foundry/blender/build_room_shell.py  # +windows param: cut openings, cache key includes windows
foundry/scene_compiler.py     # emit plan's lights + Environment; build scene_desc; call bake; apply
foundry/blender/bake_lighting.py     # +interior emitters (hearth/torch/candle) from scene_desc
foundry/lighting_bake.py      # bake_key += interior lights so the cache invalidates on them
```

Each unit has one purpose: the planner decides *what* lights exist (engine-agnostic data); the shell
consumes window geometry; the compiler renders the realtime rig + orchestrates the bake; the baker
renders GI in Cycles.

---

## Components

### C1 — `foundry/lighting_planner.py`

`plan_lighting(brief: dict, room_size: dict, manifest: list, seed: int = 0) -> LightingPlan`.
Deterministic (seeded; sorted iteration; no wall-clock). `LightingPlan` is a dataclass/dict:

```python
LightSource = {"type": "hearth"|"torch"|"candle", "pos": (x,y,z),
               "color": (r,g,b), "energy": float, "range": float, "flicker": bool}
Window      = {"wall": "N"|"S"|"E"|"W", "center": float, "width": float,
               "height": float, "sill": float}
LightingPlan = {"sources": [LightSource...], "windows": [Window...],
                "sun": {"color":(r,g,b), "energy":float, "direction":(x,y,z)},
                "sky": {"top":(r,g,b), "ambient_energy":float},
                "environment": {"ambient_color":(r,g,b), "ambient_energy":float,
                                "fog_color":(r,g,b), "fog_energy":float,
                                "tonemap":int, "exposure":float}}
```

Placement rules (defaults, all params with sensible values):
- **hearth**: 1, on the wall with the most clear span; warm `(1.0,0.6,0.3)`, energy ~6, range ~6,
  `flicker=True`, at ~0.5 m height against the wall.
- **torches**: along walls every ~3.5 m at ~2.2 m height (count from perimeter, min 2); warm
  `(1.0,0.7,0.4)`, energy ~3, range ~4, `flicker=True`.
- **candles**: on up to N (~3) table/shelf tops (top of each entity's AABB, from manifest); small
  `(1.0,0.8,0.5)`, energy ~1.2, range ~1.5.
- **windows**: 1–2, on the wall(s) without the hearth; `width~1.2`, `height~1.4`, `sill~1.2`.
- **sun/sky/environment**: dusk — cool sun `(0.5,0.6,0.85)` low energy for window shafts; ambient
  raised to a readable floor (~0.6, warm-tinted), fog lightened, tonemap/exposure eased.
  Mood scales with `brief` ("dusk"/"night"/"day"); numbers tuned by orchestrator screenshots.

### C2 — `build_room_shell.py` window openings

Add `windows: list[Window] = ()` kwarg. For each window, cut a rectangular opening in that wall:
build the wall as 4 framing segments around the opening (top/bottom/left/right), or boolean-subtract
a box. The opening matches the `Window` rect (wall, center, width, height, sill). `room_shell` cache
key + `build_room_shell` signature include `windows` so geometry invalidates when they change.
`GEN_VERSION` bumped.

### C3 — `scene_compiler.py` realtime rig (tier 0)

Replace the hardcoded dim lighting with emission from `LightingPlan`:
- Each `LightSource` → an `OmniLight3D` at `pos` with `color`/`energy`/`range`.
- `sun` → the `DirectionalLight3D` (cool dusk shaft through windows).
- `environment` → the `Environment` sub-resource (ambient color/energy, fog, tonemap, exposure)
  replacing the current `(0.1,0.1,0.14)/0.4` values.
- Optional: a small reusable GDScript that gently flickers lights with `flicker=True` (realtime
  only; never baked). Emissive hearth quad on the shell wall behind the hearth light.
This is the always-on floor: if the bake is disabled/unavailable, the scene still looks lit.

### C4 — Bake wiring (`scene_compiler`/`scaffold`)

Build a `scene_desc` from the plan + manifest + shell and call `lighting_bake.bake_scene`:
- `scene_desc = {"tier": tier, "samples": …, "placements": [...], "sun": plan["sun"],
   "sky": plan["sky"], "interior_lights": plan["sources"]}` (placements = the GLB instances +
   transforms already known to the compiler).
- Apply artifacts: tier 1 → per-vertex indirect colors written to each mesh's **render-active**
  color attribute (COLOR_0 gotcha: `render_color_index` + `export_vertex_color="ACTIVE"`, prune
  stray color attrs); tier 2 → lightmap (LightmapGI / applied textures).
- **Tier**: default tier 2 for the showcase, selectable; tier 0 (realtime only) when Blender is
  unavailable or the bake fails — `bake_scene` already degrades to tier 0.

### C5 — `bake_lighting.py` interior emitters + `bake_key`

`bake_lighting.py` currently adds only sun + sky. Extend it to read `desc["interior_lights"]` and
add a Blender `POINT` (or small `AREA`) lamp per source at its `pos` with `color`/`energy`, so the
Cycles GI bake includes hearth/torch/candle bounce — not just window daylight. Update
`lighting_bake.bake_key` to hash `interior_lights` (positions/colors/energies) so the cache
invalidates when interior lighting changes. Keep the existing tier routing + UV2 unwrap.

---

## Determinism & caching

- `plan_lighting` is deterministic for a given `(brief, room_size, manifest, seed)`.
- Bake is content-addressed (now including interior lights); GPU bake isn't bit-exact, so the
  **cache key is authoritative** — bake once, reuse.
- Shell-with-windows cache keyed on window geometry (`GEN_VERSION` bumped).

## Error handling / fallbacks

- Blender missing or bake fails → tier-0 realtime (already built-in; the realtime rig now looks good
  on its own, so this is an acceptable floor).
- Empty/odd manifest → planner still emits hearth + torches + environment (candles/windows optional).
- Window opening that would breach a wall edge → planner clamps to a safe inset.

## Testing strategy

- **Unit (no Blender):** `plan_lighting` is deterministic and emits expected sources — hearth count
  =1, torch count scales with perimeter, candles only on table/shelf tops present in the manifest,
  windows avoid the hearth wall, environment ambient is above a readable floor. `scene_compiler`
  emits one light node per source + the brighter `Environment`. `scene_desc` includes
  `interior_lights`. `bake_key` changes when an interior light changes.
- **Blender-gated:** `build_room_shell(windows=…)` produces a GLB with wall openings (bbox hole
  present); `bake_lighting.py` runs with `interior_lights` and writes artifacts.
- **Visual (orchestrator):** screenshots of the lit scene (realtime tier 0 and baked tier 2) for the
  user's verdict — atmospheric but readable, warm interior + cool window shafts.

## Out of scope

- Dynamic time-of-day, volumetric god-rays beyond Godot fog, per-NPC dynamic lights, animated bake.
- Exterior scene lighting (exterior thread), prop texture quality (separate thread).

## Open items (tunable during implementation)

- Exact energies/ambient/exposure for "readable dusk" — tuned against screenshots.
- Window count/size per room shape; whether to add glass panes vs open openings.
- Whether torch/hearth flicker ships in v1 (realtime only) or is deferred.
