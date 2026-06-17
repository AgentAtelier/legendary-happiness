# Spatial Vertical Slice — Roadmap (build-time authoring)

Fresh agent: read `STAGE-1-HANDOFF.md` §0–2 first (hard constraints, how to run).
The full design catalog is `SPATIAL-GENERATION-ARCHITECTURE.md` (10 strategies).
**This roadmap is the FIRST thin slice only** — we earn the other 9 engines later,
each when a concrete level needs it. Do this AFTER Stage 2.1 behavior reliability
lands (see `STAGE-2.1-HANDOFF.md`).

## Decisions locked (from the design discussion)
- **Build-time authoring first.** LLM-in-the-loop: "build me a kitchen" while
  designing; output is baked into the scene. (Runtime/seeded procgen — WFC,
  Voronoi, BSP — comes later, deterministic, no LLM.)
- **The workhorse layer:** Layout Patterns + Slots, with ARCS (Anchor-Relative)
  as the fallback for custom adjacencies. (Strategies #1 + #2 in the catalog.)
- **One room type to start.** Prove the whole chain on a kitchen (or whatever's
  cheapest to asset) before authoring more patterns.
- **No time estimates.** Solo-dev-with-AI pace is unknown; gate on the gauntlet,
  not a calendar.

## The core axiom (why this architecture)
**The LLM is a topologist, not a geometer.** It never outputs a `Vector3`. It
outputs *semantic intent* — a pattern choice, slot→asset assignments, relative
anchors. A **deterministic Python engine** resolves those into absolute
transforms. (The gauntlet already shows the LLM nails topology and simple grids
but would fail at dense, collision-free, "feels-right" placement — which is
exactly what the engine owns.)

## Non-negotiable integration boundary
- **DevForge-only; Odysseus + godot-ai stay vanilla.** New code lives in
  `devforge_review_package/devforge/spatial/`.
- **The spatial engine's ONLY output is the existing op schema** (`add_node`,
  `set_property` position/rotation, `add_child_scene`/scene instance) that flows
  into the proven `batch_execute` pipeline. Godot never knows an AI designed the
  room — it just sees ops. This is what makes it composable with everything else.

---

## Step 0 — Greybox the Asset Lexicon (NO art pipeline needed yet)
Every strategy rests on an **Asset Lexicon**: things with known footprints. There
are **zero `.glb`/`.tscn` assets on disk today — and that does NOT block us.** The
spatial engine's job is *placement*, not meshes. So the initial lexicon is
**primitive greybox placeholders**, exactly like a level designer blocks out a
level before art exists.

- Each lexicon entry is a **primitive**, not a model: a `MeshInstance3D` with a
  Box/Cylinder/Capsule mesh, a color, and a *defined* footprint. Author it by
  hand as JSON — no scanning, no `.glb`:
  ```json
  {
    "fridge_box":  {"primitive":"box",      "size":[0.9,1.8,0.7], "color":[0.8,0.9,1.0],
                    "category":["appliance","cold_storage"], "footprint":{"width":0.9,"depth":0.7}, "height":1.8},
    "stove_box":   {"primitive":"box",      "size":[0.8,0.9,0.7], "color":[0.3,0.3,0.3],
                    "category":["appliance","heat_source"],  "footprint":{"width":0.8,"depth":0.7}, "height":0.9},
    "table_box":   {"primitive":"box",      "size":[1.6,0.9,0.9], "color":[0.6,0.4,0.2],
                    "category":["island","table"],            "footprint":{"width":1.6,"depth":0.9}, "height":0.9},
    "barrel_cyl":  {"primitive":"cylinder", "size":[0.5,1.0,0.5], "color":[0.5,0.3,0.1],
                    "category":["clutter","storage"],         "footprint":{"width":0.5,"depth":0.5}, "height":1.0}
  }
  ```
- `devforge/spatial/lexicon.py` loads this JSON and validates footprints. For a
  greybox entry the compiler emits the ops DevForge **already produces at 100%**:
  `add_node MeshInstance3D` + `set_property mesh` (Box/Cylinder per `primitive`) +
  `set_property position` (the resolved Vector3) + optional `color`. No new
  executor surface — it rides the existing Phase-4 props pipeline.
- **Migration to real art is a one-field change.** When `.glb`/`.tscn` assets
  arrive (Kenney/Synty CC0 kits are the cheap path), add a `scene_path` to the
  lexicon entry; the compiler emits an `add_child_scene`/instance op at the same
  resolved transform instead of a primitive. **The placement math never changes.**

*Gate:* a greybox lexicon with ≥~8 kitchen-category entries (counter, fridge,
stove, table, shelf, chair, cabinet, sink — as labeled boxes) loads and validates.
This is hand-authorable in minutes and unblocks the entire engine. The art
pipeline is a SEPARATE, later concern — do not let it gate the placement engine.

## Step 1 — The workhorse: Patterns + Slots + ARCS + Spatial Compiler
Mirror `SPATIAL-GENERATION-ARCHITECTURE.md` §3:
- `spatial/patterns/*.yaml` — room topologies with semantic **slots** defined as
  ARCS (anchor + offset), reusable across room sizes. Author **3**: Rectangle
  Room, L-Shape Room, Corridor.
- `spatial/anchors.py` — `AnchorResolver`: resolves named anchors (walls, room
  center) and **chained** anchors (relative to a previously placed object) into
  absolute `Vector3`, accounting for bounding boxes.
- `spatial/compiler.py` — `SpatialCompiler.compile_layout(llm_json)`: load
  pattern → build room shell → fill slots (validate asset fits slot → resolve
  position/rotation → register as anchor for chaining → emit ops) → process ARCS
  overrides → run a **collision-nudge** safety pass → return `batch_execute` ops.
- **LLM boundary:** a strict, GBNF-constrained JSON the model must emit, given
  the user prompt + pattern list + lexicon summary:
  `{pattern, dimensions, slot_fills:{slot_id:asset_id}, arcs_overrides:[{asset,anchor,offset}]}`.
  The LLM picks the pattern and maps assets to slots by *semantic fit* — it never
  emits coordinates. Wire this as a new DevForge path (a `layout` intent / a new
  planner mode beside `arch`/`ops`, behind a flag), reusing the validator +
  executor unchanged.

## Step 2 — Prove it, gated by the gauntlet
- Add a **`spatial-v1.json` gauntlet set** (in `hub/data/gauntlet/sets/`) with
  prompts like "build a kitchen", "build an L-shaped kitchen with the stove next
  to the fridge", "a long corridor". Extend the gauntlet's coverage metrics to
  score spatial quality: **no asset-asset overlap** (AABB check on the built
  transforms), all requested slots filled, assets within room bounds, plausible
  facing. (Add a `spatial` check type to `gauntlet.py`'s `_measure`.)
- *Acceptance:* "build me a kitchen" → a structurally sound, **non-clipping** room
  from real assets, emitted as ordinary `batch_execute` ops; `spatial-v1` ≥80%
  coverage on qwen3; chain probe still green; 318 DevForge tests pass.

## Architecture rules (carry forward, non-negotiable)
1. The LLM never outputs `Vector3` — only pattern/slot/anchor intent.
2. The compiler is **deterministic** — same JSON + lexicon → identical ops.
3. Everything validates against the lexicon — no phantom assets, bounding-box
   violations raise `SlotViolation`.
4. Fallbacks are **structural**: Pattern → ARCS → collision-nudge. Degrade
   gracefully, never hard-fail.
5. Output is only the existing `batch_execute` op schema.

## What we are NOT building yet (defer until a level demands it)
Semantic Spatial Primitives, WFC, Shape Grammars, BSP, Voronoi, L-Systems,
Force-Directed, standalone Constraint Solver. They're catalogued in
`SPATIAL-GENERATION-ARCHITECTURE.md`; build each only when a concrete need
appears, and only behind the same op-schema boundary.

## Note on the bigger picture
This "LLM declares intent → deterministic engine does the work" pattern is the
*same* architecture as DevForge's script templates and (eventually) system
generation. The spatial compiler is one engine on that bus; keep that boundary
clean so systems-gen and spatial-gen compose. (Climate/weather systems are a
separate, deferred track — "cool idea, not necessity" per the current call.)
