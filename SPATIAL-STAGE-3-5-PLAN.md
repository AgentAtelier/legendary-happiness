# Spatial Stage 3–5 — Beyond the Single Room (Planning Document)

**Date:** 2026-06-16
**Status:** Design approved; ready for implementation planning (BSP first).
**Predecessor:** `SPATIAL-SLICE-ROADMAP.md` (Phase 1 workhorse + Phase 2 collision —
**built, measured, verified**). This doc plans the post-workhorse engines.
**Driving goal (user):** *finish the house → a garden with plants around it →
"the outside" (the world).* Everything here is sequenced to walk that path.

---

## 0. Recap — the axiom and the boundary (unchanged, non-negotiable)

- **The LLM is a topologist, not a geometer.** It never emits a `Vector3`. It
  emits *structure*: a split tree, a slot→asset map, a scatter spec. A
  **deterministic Python engine** turns that into absolute transforms.
- **The only output is the existing op schema** (`add_node`, `set_property`
  position/mesh/color, `add_child_scene`). Everything flows through the proven
  `batch_execute` pipeline. Godot never knows an AI designed the building.
- **DevForge-only.** New code lives in `devforge/spatial/`. Odysseus + godot-ai
  stay vanilla. (Hard constraint from `STAGE-1-HANDOFF.md` §0.)
- **Each engine is a small, isolated unit** with one job, a defined input
  (LLM JSON), and the same output (ops). They **compose** but don't entangle.

### What already exists (reused, not rebuilt)
`SpatialCompiler.compile_layout` (shell → slot-fill → ARCS → collision-nudge),
`AnchorResolver` (named + chained anchors), `AssetLexicon` (8 greybox kitchen
assets + `greybox_ops`), 3 patterns, `layout_planner.py` + GBNF, `spatial-v1`
gauntlet (now correctly measured). The new engines **sit above or beside** this
and call it; they do not reimplement placement.

---

## 1. Decomposition & build order

Phases 3–5 are **four independent engines** (plus one the garden needs). They
compose in the layered stack but each is built and tested on its own.

| # | Engine | Serves the goal | Catalog ref | This doc |
|---|--------|-----------------|-------------|----------|
| **1** | **BSP — multi-room buildings** | **finish the house** | #8 (doc Phase 5) | **DETAILED** |
| **2** | **Outdoor Scatter** (force-directed / Poisson) | **garden + plants around the house** | #5 (clutter, outdoors) | **MEDIUM** |
| 3 | **SSP** — semantic room flow | "rooms that feel right" | #3 (doc Phase 3) | roadmap |
| 4 | **WFC** — tiled dungeons | (no dungeon need yet) | #6 (doc Phase 4) | roadmap |
| 5 | **Voronoi** — districts / town | the eventual macro "outside" | #9 (doc Phase 5) | roadmap |

**Order rationale (we deliberately invert the doc's 3→4→5 numbering):** the
build order is driven by *which level the user is building*, exactly as the
roadmap demands ("earn each engine when a level needs it"). The user is
finishing a **house** (→ BSP) and then a **garden** (→ Scatter). SSP is a fuzzy
quality layer with no hard gate; WFC has no current dungeon; Voronoi is the
far horizon. So: **BSP → Scatter → (SSP / WFC / Voronoi as levels demand).**

### How they compose (the layered stack, grounded)
```
"Build a small house"
        │
   BSP (Engine 1)  ── splits the footprint into room rectangles
        │  (per leaf: room + pattern + offset)
   SpatialCompiler.compile_layout(origin=leaf)   ←── ALREADY BUILT, reused as-is
        │  (furniture, anchors, collision-nudge)
   batch_execute ops

"Build a garden around the house"
        │
   Scatter (Engine 2) ── samples plant positions in the yard region,
        │                 keep-out = the house footprint from Engine 1
   AssetLexicon.greybox_ops (plants)  ←── reused
        │
   batch_execute ops
```

---

## 2. Engine 1 — BSP Multi-Room Buildings  ★ build first, detailed

**Goal:** "build / finish a house" → a building whose footprint is recursively
split into rooms, each room **furnished by the existing room engine**, with
interior walls + doorways between rooms. Emitted as ordinary ops.

### 2.1 The LLM boundary (topologist, GBNF-constrained)
The model emits a **split tree**: every node is either a SPLIT (axis + ratio +
two children) or a LEAF (a room to hand to the pattern engine). **No coordinates.**

```json
{
  "building": "house",
  "footprint": {"width": 12.0, "depth": 8.0},
  "tree": {
    "axis": "x", "ratio": 0.5,
    "left":  {"room": "living_room", "pattern": "rectangle_room",
              "slot_fills": {"center_table": "table", "chair_north": "chair"}},
    "right": {"axis": "z", "ratio": 0.6,
      "left":  {"room": "kitchen", "pattern": "rectangle_room",
                "slot_fills": {"north_counter_center": "stove", "east_storage": "fridge"}},
      "right": {"room": "bedroom", "pattern": "rectangle_room",
                "slot_fills": {"center_table": "table"}}}
  }
}
```
- A node is a **split** iff it has `axis` (`"x"` | `"z"`) + `ratio` (0.1–0.9) +
  `left` + `right`. Otherwise it is a **leaf** with `room` + `pattern` +
  `slot_fills`.
- The grammar is recursive but **depth-bounded** (max depth 4 → ≤16 rooms) so
  the GBNF stays finite and the LLM can't runaway-nest. (Recursion bound is a
  grammar rule, mirroring how `arch_planner` bounds entity counts.)
- The LLM picks the split structure and which pattern/assets per room by
  *semantic fit* — never a position.

### 2.2 The deterministic engine — `devforge/spatial/bsp.py`
Chosen approach: **a layer ABOVE `SpatialCompiler`, max reuse.**

```python
class BSPPartitioner:
    def __init__(self, room_compiler: SpatialCompiler): ...
    def compile_building(self, building_json: dict, root_path: str) -> DevForgePlan:
        leaves = self._partition(building_json["tree"], origin=(0,0),
                                 size=building_json["footprint"])
        steps = []
        steps += self._building_floor(footprint, root_path)         # one slab
        for leaf in leaves:                                          # per room:
            room_json = {"pattern": leaf.pattern, "dimensions": leaf.size,
                         "slot_fills": leaf.slot_fills}
            sub = self.room_compiler.compile_layout(
                      room_json, root_path, origin=leaf.origin)      # REUSE
            steps += sub.steps
        steps += self._partition_walls(leaves, root_path)           # walls+doors
        return DevForgePlan(goal="BSP building", steps=steps)
```
- **`_partition(node, origin, size)`** — recursive. At a SPLIT, divide `size`
  along `axis` by `ratio` into two sub-rects (offsetting the second child's
  origin); recurse. At a LEAF, return one `RoomRect{origin, size, pattern,
  slot_fills}`. Pure arithmetic, fully deterministic.
- **Per-room reuse** — each leaf rect calls the *existing* `compile_layout` with
  the leaf's `origin`. All furniture / anchors / collision-nudge come for free.
- **`_partition_walls(leaves)`** — for each internal split boundary, emit a thin
  greybox wall box spanning the shared edge, with a **centered doorway gap**
  (skip the middle ~1.2 m). MVP: straight walls + one door per boundary.
- **`_building_floor`** — one floor slab the size of the footprint (so rooms
  don't each z-fight a per-room floor; room patterns' own floor/ceiling are
  suppressed via a `shell=False` flag passed to `compile_layout`).

### 2.3 The ONE change to existing code (kept minimal + back-compatible)
`compile_layout` and `AnchorResolver` currently resolve anchors in the room's
own frame (origin 0,0). To place a room at a BSP leaf offset:
- `AnchorResolver(anchors, dims, origin=(0.0, 0.0))` — add `origin`; every
  resolved position adds `origin.x` / `origin.z`.
- `SpatialCompiler.compile_layout(layout_json, root_path, origin=(0,0),
  shell=True)` — thread `origin` into the resolver and the shell builder; add a
  `shell` flag so BSP can suppress per-room floors.
- **Default `origin=(0,0)`, `shell=True` → existing callers + all current tests
  unchanged.** (Verified-by-test as part of the work.)

### 2.4 Routing / integration
A new per-request planner value **`planner: "building"`** (parallel to
`"layout"`), threaded through the *already-existing* per-request planner param
(`engine.run_pipeline` → `mcp_server` → `gauntlet`). `building` routes to a
`BuildingPlanner` (LLM, building GBNF) → `BSPPartitioner`. No global mode flip.
`layout` (single room) is untouched.

### 2.5 Files
- **Create:** `devforge/spatial/bsp.py` (`BSPPartitioner`, `RoomRect`),
  `devforge/spatial/building_planner.py` (LLM call + building GBNF),
  `devforge/spatial/prompts/building_planner.gbnf`,
  `hub/data/gauntlet/sets/building-v1.json`.
- **Modify (small):** `devforge/spatial/anchors.py` (+`origin`),
  `devforge/spatial/compiler.py` (+`origin`, +`shell`),
  `engine.py` / `mcp_server.py` (route `planner="building"`).

### 2.6 Gauntlet — `building-v1`
Prompt e.g. *"build a small house with a living room, a kitchen, and a bedroom."*
New `building:*` checks in `gauntlet.py`:
- `building:rooms` — leaf-count rooms actually created (≥ requested).
- `building:no_overlap` — room rectangles don't overlap (AABB on the leaf rects).
- `building:in_bounds` — every room within the footprint.
- `building:furnished` — each room has ≥1 placed asset (reuse `spatial:assets`).
- `building:walls` — ≥1 partition wall between adjacent rooms.
**Acceptance:** "build a 3-room house" → 3 non-overlapping furnished rooms tiling
the footprint, walls + doorways between them, ordinary ops; `building-v1` ≥80%.

### 2.7 Failure modes & guards
- **Degenerate ratio** (0 or 1) → clamp to [0.1, 0.9]; a room can't be 0-width.
- **Tiny leaf** (smaller than the pattern minimum / its furniture) → emit the
  room shell but skip slots that `SlotViolation`; never hard-fail (rule #4).
- **LLM over-nests** → grammar depth bound (2.1) prevents it structurally.
- **Unknown pattern in a leaf** → fall back to `rectangle_room`, log a warning.

### 2.8 Test plan
- **Unit (`test_bsp.py`, runnable offline):** `_partition` math (ratios, offsets,
  leaf rects don't overlap and tile the footprint); `origin` offset in
  `compile_layout` (a room at origin (5,5) places furniture at +5,+5); wall
  generation count; degenerate-ratio clamp; back-compat (existing `test_spatial`
  stays green).
- **Gauntlet (human runs):** `building-v1` ≥80% on the loaded model + a
  screenshot of a built house.

---

## 3. Engine 2 — Outdoor Scatter (the garden)  ◑ medium detail, build second

**Goal:** "build a garden with plants around the house" — scatter plants in the
yard region, **avoiding the house footprint** and each other, at a natural
density. First step "toward the outside."

### 3.1 LLM boundary (counts + species + density, never positions)
```json
{"region": {"width": 20, "depth": 16},
 "keep_out": [{"x": 0, "z": 0, "width": 12, "depth": 8}],  // the house
 "scatter": [{"asset": "tree",  "count": 6,  "min_spacing": 2.5},
             {"asset": "bush",  "count": 12, "min_spacing": 1.0},
             {"asset": "flower","density": 0.4}]}
```

### 3.2 Engine — `devforge/spatial/scatter.py`
- **Poisson-disk / jittered-grid sampling** in `region`, rejecting points inside
  any `keep_out` rect (the house) and enforcing `min_spacing` (reuse the AABB
  `_nudge`). Deterministic given a seed.
- **`keep_out` is the composition seam:** BSP's building footprint is passed in,
  so the garden wraps the house with no clipping. This is how Engine 1 and 2
  compose.
- Emits greybox plant ops via the lexicon (new category, below).
- Counts vs density: `count` = exact N; `density` = N per m² of free region.

### 3.3 Lexicon extension (new outdoor category)
Add greybox plants to `asset_lexicon.json`: `tree` (tall cylinder, green),
`bush` (small sphere, green), `flower` (tiny box, color), `rock` (box, gray).
Same one-field migration path to real art (`scene_path`) — placement unchanged.

### 3.4 Gauntlet — `garden-v1` (or extend a `scatter:*` check family)
- `scatter:count` — requested plant counts placed (± density tolerance).
- `scatter:no_overlap` — no plant-plant clip (min_spacing honored).
- `scatter:keep_out` — **no plant inside the house footprint.**
- `scatter:in_region` — all within the yard bounds.
**Acceptance:** "garden with trees and bushes around the house" → plants ringing
the house, none clipping it, natural spacing; `garden-v1` ≥80%.

---

## 4. Engines 3–5 — Roadmap (earn each when a level demands it)

These are **not built now** — specced so the trail is clear and the boundaries
are reserved. Each obeys the same axiom + op-schema output.

- **SSP — Semantic Spatial Primitives (#3).** LLM emits *activity zones* +
  *workflow paths* (`storage → prep → cook`); a deterministic engine maps zones
  to bounding boxes, orders them to satisfy the workflow, then hands each zone to
  the pattern engine. **Earn it when** room *quality* ("flows well") becomes a
  felt need — i.e. when the house has enough rooms that arrangement matters.
- **WFC — Wave Function Collapse (#6).** LLM defines a tile set + adjacency
  rules; the engine collapses a grid (constraint propagation) into a legal
  layout; the pattern engine fills carved rooms. **Earn it when** a **dungeon /
  crypt** level appears (none yet).
- **Voronoi — Tessellation (#9).** LLM places semantic seed points ("market",
  "slum"); the engine computes cells → district/street borders → feeds BSP per
  building. **Earn it when** the goal reaches **town / overworld** scale — the
  far horizon of "the outside."

---

## 5. Architecture rules (carry forward — non-negotiable)
1. The LLM never outputs `Vector3` — only split trees / slot maps / scatter specs.
2. Engines are **deterministic** — same JSON (+ seed) → identical ops.
3. Everything validates against the lexicon — no phantom assets; bounding-box
   violations raise `SlotViolation` and are skipped, never crash.
4. Fallbacks are **structural** and **graceful** — a bad leaf/asset degrades
   (skip + log), it does not nuke the build.
5. Output is **only** the existing `batch_execute` op schema.
6. **DevForge-only** — Odysseus + godot-ai vanilla; `devforge/spatial/` + hub.

---

## 6. Build order & gates (human runs the tests)
1. **Engine 1 — BSP.** Implement `origin`/`shell` change + `bsp.py` +
   `building_planner` + `building-v1`. Gate: unit tests green offline; human runs
   `building-v1` ≥80% + screenshot. **Finishes the house.**
2. **Engine 2 — Scatter.** `scatter.py` + plant lexicon + `garden-v1`, composing
   the house footprint as keep-out. Gate: `garden-v1` ≥80% + screenshot.
3. **Re-confirm** `spatial-v1` + `capability-v1` unchanged (no regressions).
4. SSP / WFC / Voronoi — open, earned per §4.

Per the standing rule: **the human runs all gauntlets / scenario suites / model
swaps**; the AI builds, unit-tests offline, and hands over the exact commands.

## 7. Decisions to revisit during implementation
- Wall/doorway fidelity (straight walls + centered door for MVP; corridors,
  multiple doors, window gaps later).
- Whether building outer-perimeter walls are needed in v1 or implied by room
  edges (lean: implied for v1, perimeter walls as a fast-follow).
- Scatter sampler: Poisson-disk (even, natural) vs jittered grid (simpler) —
  pick during impl; both are deterministic with a seed.
- Whether `building` is a distinct planner mode or a capability of `layout`
  (lean: distinct mode for clean isolation).
