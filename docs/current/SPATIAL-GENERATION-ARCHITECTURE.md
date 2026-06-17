# DevForge Spatial Generation — From LLM Intent to Godot Vector3

> **Framing:** this is the STRATEGY CATALOG (the menu of options), not the
> committed plan. The committed first slice is `SPATIAL-SLICE-ROADMAP.md`, which
> uses only strategies #1 (Patterns + Slots) and #2 (ARCS). The other 8 are
> documented here so we can reach for them when a concrete level needs them.

**Target:** 3D open-world first-person RPG (Solo Dev)
**Stack:** Godot 4.x + DevForge + Qwen3-14B (local) / Claude (cloud)
**Core pipeline:** `add_node` → `set_property` (Vector3) → `batch_execute`

---

## 0. The Core Axiom

> **The LLM is a topologist; it is not a geometer.**

LLMs cannot reliably hallucinate absolute Cartesian coordinates (X: 4.52, Y: 0,
Z: -1.1). They ARE exceptional at topology, relationships, semantic roles, and
constraints ("next to", "against the wall", "workflow path", "social anchor").

**Therefore:** the LLM must **never** output a `Vector3`. It outputs intermediate
representations (graphs, grammars, semantic roles, anchor chains). Deterministic
Python engines resolve these into absolute transforms, compiled into the existing
`batch_execute` pipeline.

---

## 1. The Catalog: 10 Spatial Generation Strategies

### Scale 1 — Room & Furniture Layout (the 80% use case)
1. **Layout Patterns + Slots (the workhorse).** Author room topologies with named
   semantic slots; the LLM classifies the room and fills the slots with assets.
   LLM: select pattern, map assets→slots by semantic fit. Engine: look up slot
   coords, adjust for bounding boxes, emit `add_node`. Best for kitchens,
   bedrooms, tavern halls — standard architectural spaces.
2. **Anchor-Relative Coordinate System (ARCS).** LLM chains placements relative to
   named anchors (walls, doors, previously placed objects): `asset + anchor +
   offset`. Engine resolves the chain recursively into absolute coords. Best for
   variations, L-shapes, user adjacencies ("put the stove next to the fridge").
3. **Semantic Spatial Primitives (SSP).** LLM reasons about *human activity*:
   activity zones (`heat_source_work_zone`) and workflow paths (storage→prep→
   cooking). Engine maps zones to bounding boxes satisfying workflow/clearance,
   then hands off to Patterns/Slots. Best for "make the kitchen flow well", NPC
   schedules, ceremonial spaces.

### Scale 2 — Fine-Grained & Dense Clutter
4. **Constraint Solver (the safety net).** LLM outputs a relationship graph
   (`adjacent`, `inside`, `against_wall`). Engine resolves via chain resolution +
   AABB collision checks, nudging overlaps clear. Best for dense clutter ("scatter
   12 books"), resolving collisions the pattern engine missed.
5. **Force-Direction / Virtual Rubber Banding.** Objects are graph nodes with
   attractive/repulsive forces. LLM defines force weights; engine runs iterative
   relaxation until stable, non-overlapping. Best for organic clutter, campsites,
   irregular ruins.

### Scale 3 — Modular & Tile-Based
6. **Wave Function Collapse (WFC).** Tiles + adjacency rules → valid arrangements,
   no illegal borders. LLM defines tile set + adjacencies; engine collapses the
   superposition grid. Best for dungeon corridors, crypts, modular stations.
7. **Shape Grammars / Symbolic Rewriting.** LLM writes hierarchical rewrite rules;
   engine expands into a 2D occupancy grid → Vector3. Best for highly structured
   architecture (castles, palaces) needing strict modularity.

### Scale 4 — Macro & World Building
8. **BSP Partitioning.** Recursively split a bounding box. LLM specifies split
   ratios + region semantics; engine executes splits, hands leaves to room-scale
   engines. Best for multi-room buildings, castle floors, tavern interiors.
9. **Voronoi / Delaunay.** Organic cells from seed points. LLM places seeds with
   semantic tags; engine computes cells → streets/district borders. Best for city
   maps, towns, cave systems, territory partitioning.
10. **L-Systems.** Parallel string rewriting for branching structures. LLM defines
    axiom + rules; engine rewrites + interprets as turtle-graphics 3D drawing.
    Best for branching dungeons, sewers, runes, tree/root growth.

---

## 2. The Layered Stack (compose, don't pick one)
The LLM interacts only with the top; the stack falls back to lower layers as
complexity grows:

```
USER PROMPT → LLM intent classification
  → MACRO: BSP (#8) splits the bounding box
    → ZONE: SSP (#3) defines workflow zones
      → ROOM: Patterns+Slots (#1), fallback ARCS (#2)   ← the workhorse
        → TILE: WFC (#6) or Shape Grammar (#7)
          → DETAIL: Constraint/Force solver (#4/#5) + collision nudge
            → DEVFORGE COMPILER: resolve all → add_node + set_property
```

---

## 3. Implementation Spec (the first slice — see SPATIAL-SLICE-ROADMAP.md)
- **Asset Lexicon** (`spatial/lexicon.py`): scan assets, extract footprints →
  `asset_lexicon.json` (`{id:{path, category[], footprint{width,depth}, height}}`).
  Used to reject assets too large for a slot (`SlotViolation`).
- **Pattern Registry** (`spatial/patterns/*.yaml`): room topologies whose slots
  are defined as ARCS (anchor + offset), reusable across room sizes.
- **Anchor-Relative Engine** (`spatial/anchors.py`): `AnchorResolver` resolves
  named + chained anchors into absolute Vector3 accounting for bounding boxes.
- **Semantic Slot Filler (LLM boundary):** strict JSON —
  `{pattern, dimensions, slot_fills:{slot:asset}, arcs_overrides:[{asset,anchor,offset}]}`.
  The LLM never emits coordinates.
- **Spatial Compiler** (`spatial/compiler.py`): pattern → room shell → fill slots
  (validate fit → resolve position/rotation → register anchor → emit ops) → ARCS
  overrides → collision-nudge → return `batch_execute` ops.

---

## 4. Build Order (defer engines you don't need)
- **Phase 1 — Workhorse:** Lexicon + ARCS + Patterns + Compiler + 3 patterns.
- **Phase 2 — Safety net:** Constraint solver (AABB nudge) as a post-process.
- **Phase 3 — Semantic layer:** SSP (activity zones → pattern selection).
- **Phase 4 — Dungeon engine:** WFC (macro grid → Pattern fills rooms).
- **Phase 5 — World builder:** BSP (multi-room) + Voronoi (districts).

---

## 5. Architecture Rules (non-negotiable)
1. The LLM never outputs `Vector3` — only intent / slots / anchors.
2. The compiler is deterministic — same JSON + lexicon → identical ops.
3. Everything validates against the lexicon — no phantom assets, no silent
   bounding-box violations (`SlotViolation`).
4. Fallbacks are structural: Patterns → ARCS → Constraints; degrade gracefully.
5. The pipeline is unchanged — the compiler's only output is the proven
   `batch_execute` schema. Godot just sees ops.
