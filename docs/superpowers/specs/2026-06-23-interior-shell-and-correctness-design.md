# Interior Correctness + Shell/Roof — Design Spec

**Date:** 2026-06-23
**Thread:** #1 (visual correctness) + #2 (scene shell/roof), from the post-4-model-run decomposition.
**Goal:** Make the interior `quest` scene look and behave like a real room: props rest on the
floor, NPCs don't walk through furniture, and the room shell is proper architecture
(stone walls, timber floor, **king-post truss roof**) with non-distorted, good-looking
materials — replacing the flat `BoxMesh` shell wearing low-quality stretched textures.

End artifact: this spec → implementation plan → CLI-AI prompts.

---

## Context / why

After the 4-model comparison, the 27B interior build showed: floating props, NPCs clipping
through objects, a flat featureless ceiling, and "horrible" walls/floor/ceiling. Root causes
were diagnosed directly in code:

- **Floating:** props get fixed `Transform3D` Y with no per-asset base offset
  (`scene_compiler.py`); a GLB whose origin isn't at its base floats.
- **Clipping:** the `NavigationMesh` is a flat 2-triangle quad over the floor (minus a 1.2 m
  wall margin) that ignores props entirely, so agents path straight through furniture.
- **Stretched/distorted textures:** the shell is `BoxMesh` with `uv1_scale = Vector3(10,10,10)`
  and **no triplanar** — a square 512² texture mapped `[0,1]` per face then tiled ×10 becomes
  non-square tiles on non-square walls (e.g. ~2.7:1 stretch on an 8×3 m wall), varying per wall.
- **Low-quality texture image:** `build_shell_textures.py` produces a **single-octave**
  Voronoi(8)+Noise(12) run through a 3-stop ramp between two near-grey colors
  (`(0.45,0.45,0.47)`→`(0.30,0.30,0.32)`): ~0.15 luminance spread, zero saturation, no mortar
  joints/cracks/structure. Normal strength `0.2` ≈ no relief. Floor/wall/ceiling are all the
  same `rough_granite` (brightened), so a study can't have a timber floor.

## Locked decisions (from brainstorm)

- **Shell generated as a Blender GLB** (Approach A), not inline `BoxMesh` and not hybrid.
- **Interior ceiling = king-post truss** (reads as a pitched roof from inside). Exterior
  pitched roof is a later thread.
- **Lighting/brightness is OUT** of this thread (separate thread). Scene stays dim until then.
- **NPC clipping fix = runtime obstacle avoidance** (`NavigationObstacle3D`), not navmesh
  carving (carving is the future, level-design-branch approach).

---

## Architecture & module boundaries

```
foundry/blender/build_room_shell.py   # Blender: geometry (walls/floor/king-post truss) +
                                      #   two material slots (stone, timber), exports one GLB
foundry/blender/shell_materials.py    # Blender: procedural stone + timber node graphs +
                                      #   PBR texture bake (albedo/normal/orm). Replaces the
                                      #   weak stone-only graph in build_shell_textures.py.
foundry/room_shell.py                 # Orchestration: content-addressed cache keyed on
                                      #   (w, d, wall_height, theme, gen_version); calls Blender
                                      #   on miss; returns GLB path. Blender-unavailable → None.
foundry/scene_compiler.py            # Consumes the shell GLB (instances it, applies triplanar
                                      #   materials per slot); keeps StaticBody/CollisionShape +
                                      #   NavigationRegion wiring AROUND it; FALLS BACK to the
                                      #   existing inline box shell when room_shell returns None.
```

Each unit has one purpose and a narrow interface:
- `build_room_shell.py`: `main()` invoked as `blender --background --python build_room_shell.py
  -- <out_glb> <w> <d> <wall_height> <theme> <seed>`. Pure geometry+material → GLB. No knowledge
  of Godot or caching.
- `shell_materials.py`: functions that, given a Blender mesh + a surface kind (`stone`/`timber`)
  + palette + seed, build the node graph and bake the texture set. Reusable by both shell and
  (future) other architecture.
- `room_shell.py`: `ensure_room_shell(w, d, wall_height, theme, seed) -> Path | None`. Owns the
  cache dir + key + Blender subprocess + timeout. The ONLY module `scene_compiler` talks to.
- `scene_compiler.py`: unchanged collision/nav contract; swaps the *visual* shell source.

---

## Components

### C1 — `build_room_shell.py` (geometry)

Parameterized by `w` (span, X), `d` (length, Z), `wall_height` (plate height), `theme`, `seed`.
Generates a single GLB containing:

- **Floor**: a `w × d` slab at y∈[−t, 0], material slot **timber**.
- **4 walls**: thickness `wall_t`, from y=0 to `wall_height`, material slot **stone**.
- **King-post truss roof** (material slot **timber** for beams, **stone**/boards for roof planes):
  - Trusses repeated along Z every ~1.5–2.0 m (count derived from `d`, ≥2).
  - Each truss = two **rafters** (wall plate → ridge apex), a horizontal **tie-beam** at plate
    height spanning `w`, a vertical **king-post** (tie-beam midpoint → ridge).
  - **Ridge beam** along Z connecting apexes. Apex height = `wall_height + w * 0.4` (≈30° pitch).
  - **Roof planes**: boarded surfaces over the rafters on both slopes so the room is enclosed
    (no open sky), undersides visible from within.
  - Beams beveled (small chamfer) for quality; beam cross-section ~0.12–0.18 m.
- **Determinism**: seeded; identical params → identical mesh. No wall-clock, no unseeded RNG.
- **Material slots**: exactly two named materials (`stone`, `timber`) so the consumer can apply
  one triplanar `StandardMaterial3D` per slot. Beams/floor/roof-boards = timber; walls = stone.
- **Export**: glTF binary (`.glb`), Y-up, meters, origin at room center on the floor (y=0 at
  floor top) so the consumer instances it at the room origin with no offset.

### C2 — `shell_materials.py` + texture set (kills "low-quality image")

Replace the single-octave grey generator. For each surface kind:

- **Stone (walls)**: multi-octave noise (≥3 octaves) + a **mortar/block structure** (e.g. a brick
  or ashlar Voronoi with darkened joints), real desaturated-but-present color and **contrast**
  (luminance spread ≥ ~0.35), large-scale variation so tiles don't read as uniform mush.
- **Timber (floor/beams)**: directional wood grain (stretched noise along the plank axis) +
  plank seams + tonal variation between planks.
- **Resolution**: 1024² minimum (2048² if bake time allows). Tiling is world-space (see C4), so
  texel density is set there, not by oversize textures.
- **Normal map**: real relief — stone joints recessed, plank seams grooved. Bump strength tuned
  up materially from 0.2 (target visible relief under grazing light).
- **ORM**: AO from a clean bake (raise `cycles.samples` above 1 for the AO pass to avoid noise),
  roughness/metallic per palette.
- Output PNG set per surface kind: `shell_stone_{albedo,normal,orm}.png`,
  `shell_timber_{albedo,normal,orm}.png`. Generated once, cached with the GLB (keyed by
  `gen_version`), copied into the build's `assets/` by scaffold.
- **Scaffold update:** `scaffold.py::_ensure_shell_textures` currently hardcodes the old
  `shell_{floor,wall,ceiling}_*` names — update its copy list to the new `shell_{stone,timber}_*`
  names (and source them from the room-shell cache dir). The old stone-only
  `build_shell_textures.py` is superseded by `shell_materials.py` and removed.

### C3 — `room_shell.py` (orchestration + cache + fallback)

- `ensure_room_shell(w, d, wall_height, theme, seed) -> Path | None`.
- **Cache**: content-addressed dir (e.g. `~/.cache/forge/room_shell/<hash>/`) keyed on
  `(round(w,2), round(d,2), round(wall_height,2), theme, gen_version)`. Hit → return cached GLB.
- **Miss**: run Blender subprocess (bounded timeout, e.g. 180 s) to build GLB + textures into the
  cache dir. On success return path; on failure/timeout return `None` (logged).
- **Blender unavailable** (no binary): return `None` immediately (no raise).
- Never mutates tracked repo files. Mirrors the existing asset/hunyuan cache pattern.

### C4 — `scene_compiler.py` integration

- Replace the inline `floor_vis_mesh`/`wall_*_mesh`/`ceiling_mesh` BoxMeshes + the stretched
  `uv1_scale` materials with: instance the shell GLB at room origin; assign **two triplanar
  world-space `StandardMaterial3D`s** (stone, timber) referencing the C2 texture sets.
  - `uv1_triplanar = true`, `uv1_world_triplanar = true`, `uv1_scale` chosen for ~0.5–1.0 m tile
    in world space (consistent on walls, floor, and angled beams; no aspect distortion).
- **Keep unchanged**: the `Floor`/`Wall*` `StaticBody3D` + `CollisionShape3D` colliders and the
  `NavigationRegion3D`/`NavigationMesh` (collision/nav contract is independent of the visual mesh).
  Collision can stay box-approximated to the room AABB; the truss does not need collision.
- **Fallback**: if `ensure_room_shell` returns `None`, emit the existing inline box shell exactly
  as today (so headless builds and Blender-less environments still produce a valid scene).

### C5 — Floating props fix

- For each placed prop, offset its `Transform3D` Y by `-aabb_min_y` (the asset's local AABB
  minimum Y), so the base sits at floor top (y=0). Reuse the AABB already computed for
  `collision_info` — do **not** add a second GLB load.
- Props that are explicitly surface-mounted (e.g. wall paintings) keep their existing placement;
  the rest floor-rest.

### C6 — NPC clipping fix

- For each non-decor, collidable prop, emit a child `NavigationObstacle3D` with `radius` (and
  `height`) derived from its AABB footprint, so `NavigationAgent3D` NPCs steer around it via RVO
  avoidance at runtime.
- Decor props (`"decor": True`, no collision) get no obstacle.
- Documented non-goal: this does not carve the navmesh; stationary edge-cases may still touch a
  prop. Proper footprint carving is deferred to the level-design branch (#6).

---

## Determinism & caching

- Same `(w,d,wall_height,theme,seed,gen_version)` → byte-identical GLB + textures (GPU bake is
  not bit-exact, so the **cache key is authoritative**: build once, reuse — same pattern as the
  baked-lighting/asset caches).
- Bumping `gen_version` invalidates all cached shells (use when the generator changes).

## Error handling / fallbacks

- Blender missing or shell-gen fails/timeouts → `room_shell` returns `None` →
  `scene_compiler` emits the inline box shell. A build NEVER hard-fails on the shell.
- Texture bake partial failure → treated as gen failure (fallback), logged.

## Testing strategy

- **Unit (no Blender):** `room_shell` cache key stability + hit/miss; `scene_compiler` emits the
  GLB-instanced shell when a path is provided and the **inline fallback** when `None`; C5 sets
  prop Y to `-aabb_min_y`; C6 emits a `NavigationObstacle3D` per collidable prop and none for decor.
- **Blender-gated:** `build_room_shell.py` produces a GLB with the expected two material slots and
  a truss node count derived from `d` (run only where Blender is available).
- **Godot headless smoke:** the scaffolded scene loads with the shell GLB without script/parse
  errors (existing smoke harness; remember probes don't catch everything — headless-load the build).
- **Visual (human-in-loop):** orchestrator renders screenshots; user walks the build and notes
  stretch/quality/placement/clipping.

## Out of scope (explicit)

- Lighting/exposure/brightness (separate thread; scene stays dim until then).
- Exterior building/terrain/pitched roof (thread #3).
- Prop (non-shell) texture quality (thread #7) — though `shell_materials.py` techniques may be
  reused there later.
- Dialogue↔target consistency (thread #4), loose-ends/lexicon (#5), level-design branch (#6).

## Open items deferred (not blocking)

- Whether collision should follow the truss (no — box room collision is sufficient; player can't
  reach the rafters).
- Exact tile size + bevel dims are tunable during implementation against screenshots.
