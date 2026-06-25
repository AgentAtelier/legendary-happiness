# World Engine — Unit 3 End-to-End: Multi-Space Godot Assembly

**Date:** 2026-06-25 · **Status:** DESIGN (implementation next; no LLM)
**Context:** `WORLD-ENGINE.md` §6 sub-project (a). Unit 3 *core* (the per-space
`space_to_compile_inputs` adapter, `world/assembly.py`) is done. This is the END-TO-END: turn a whole
`World` (multiple spaces + portals + entities) into a **walkable Godot scene**, deterministically,
reusing the proven `scene_compiler` per space. The thing that makes the machinery visible.

## Goal

`World` → a Godot project you can load and walk through: each space rendered at its world-space
footprint, connected by portals, populated with its entities. Deterministic (same world → same scene).

## Approach: per-space PackedScene + one composed world scene

Do NOT emit fresh `.tscn` for the whole world (risky/unverifiable). Reuse the proven path per space:

1. **Per-space compile.** For each `SpaceNode`: `space_to_compile_inputs(node)` (done) →
   `compile_scene(...)` → save `scenes/<space_id>.tscn` (a PackedScene). Each space is a centred room
   the existing emitter already produces correctly.
2. **Compose.** Emit a parent `world.tscn` whose root `World` Node3D instances each space PackedScene as
   a child, **translated to that space's footprint origin** (world coords). Spaces thus lay out
   spatially correct — the courtyard ends up north of the hall, the cellar below — *for free*, because
   the footprints already carry world positions.
3. **Player + spawn.** One Player/Camera at a chosen space's centre; existing player controller.

This is plain Godot scene-instancing (`[ext_resource type="PackedScene" path=...]` + an instanced node
with a `transform` at the footprint origin) — no new emission logic, just orchestration.

## The hard part: portals as walkable openings

A portal between two face-adjacent spaces needs an actual **opening** in the shared wall, or the player
hits a wall. This is the real geometry risk. Options, simplest first:
- **v1 (ship this):** at a portal's `position`, the room shell **omits the wall segment** (or carves a
  doorway-sized gap) on the shared face. The shell generator already builds 4 walls; it gains a list of
  "openings" (portal rects on each face) to skip/cut. Deterministic, no new assets.
- **v2 (later):** a doorway/arch prop at the opening; threshold transition.
- **v3 (much later, post-maturity):** scene streaming (load/unload spaces at portals) instead of one
  big scene — only when worlds outgrow a single scene's budget.

v1 keeps the whole world in one scene (fine for the first dozens of spaces) and makes portals real with
shell-level openings.

## What's pure-Python (buildable + testable NOW, no stack)

- `world/compose.py`: `compose_world(world, out_dir)` — orchestrates per-space compiles + emits the
  parent `world.tscn`. The parent-scene **string assembly** (ext_resource per space scene; instanced
  child node with the footprint-origin transform; player spawn) is deterministic and structurally
  testable: assert `world.tscn` references each space scene exactly once and places it at its footprint
  origin; assert the spawn is inside a real space; deterministic (same world → byte-identical parent).
- The **openings list** per space (deriving which wall segment each portal cuts, from portal position +
  the two footprints) — pure geometry, unit-testable against the AABB helpers.

## What's stack-gated (verify when the stack is reliable — NOT flown blind)

- **Asset resolution:** entity types → real GLBs via the asset foundry (Blender). Without assets,
  `compile_scene` drops props (the unit-3-core smoke showed the stub). A real render needs the GLBs
  built — Blender, GPU.
- **Godot LOAD + walkability:** does `world.tscn` (+ the instanced space scenes) parse, render, and let
  the player walk between spaces through the openings. Verified by the orchestrator building a real
  multi-space world and the **user opening it in Godot** (same loop as `m1_lit`), since the headless
  capture harness is parked.
- **Shell openings:** the wall-cut geometry actually lines up with the portal — visual check.

## Verification plan

1. Pure-Python: structural + geometry tests for `compose_world` and the openings (now).
2. Stack: I build a real 3-space world (hall + north courtyard + cellar) with assets → you open
   `world.tscn` in Godot → walk hall→courtyard→cellar through the portals. That's the end-to-end proof.

## Risks / open

- **Shell openings** is the genuine unknown — cutting a correct doorway in the existing 4-wall shell at
  an arbitrary portal position. v1 may start by skipping the whole shared-face wall (crude but walkable)
  and refine to a doorway-sized cut. Flagged as the thing most likely to need iteration.
- **Lighting per space** (each space bakes its own; seams at portals) — defer; the Cohesion lighting
  facet (sub-project c) owns cross-space coherence later.
- **One-scene budget** — fine for the first milestone; streaming (v3) is a post-maturity concern, and the
  architecture (per-space PackedScenes) already makes streaming a swap-in, not a rewrite.

## Sequence

1. `world/compose.py` + structural/geometry tests (pure-Python, now).
2. Shell openings (v1: skip shared-face wall) — pure-Python emission + a structural test.
3. [stack] build a real 3-space world with assets; **user verifies in Godot.**
4. Iterate openings v1→doorway-cut based on the visual.
