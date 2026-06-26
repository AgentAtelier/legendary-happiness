# Prompt-Driven Room Variety (Slice #6) — Design Spec

**Date:** 2026-06-20
**Status:** design approved (testing-grade — expected to be iterated, not final)
**Topic:** prompt → a *themed, varied room* (different props, counts, materials, size, layout)
instead of the single hardcoded 4-prop manifest every scene currently shares.

## Why

Today the `quest` command builds every scene from **one hardcoded manifest** (`__main__.py`):
the same 4 props at the same fixed positions, the same NPC, for every prompt and every model.
The only per-run variation is the dialogue + which prop is the target — both invisible unless you
talk to the NPC. That is why all 8 comparison builds looked identical. There is also no
room-composition layer at all: `forge_from_request` builds exactly one asset; nothing selects a
*set* of props or places them. #6 builds that missing layer.

This is the **hardest** item from the post-playtest review and is deliberately its own slice,
sequenced after the delegated "presentable, human-playable room" workstream (items 1–5).

## Scope (chosen: Level 1 + two named new props)

- **In:** a prompt-driven `RoomPlanner`; LLM-chosen room size; LLM-chosen prop set + counts over a
  closed grid; deterministic layout across three placement surfaces; over-capacity as an explainable
  Decision Point; generate-missing-assets-on-demand; **two new generators: `rug` and `painting`**.
- **Out (future slices):** other new prop types (anvil, forge, bed, barrel…); room height/shape
  variety (rectangular single-room only); multi-room; lighting/material/wall *rendering* (that is the
  delegated 1–5 workstream).

This is testing-grade. The model's size/count judgement and the layout heuristics will not hold up
over time; we ship it to iterate against real output rather than keep planning.

## Architecture

### 1. `RoomPlanner` — `foundry/room_planner.py` (NEW)
Mirrors `AssetPlanner`/`QuestBehaviourPlanner`: injectable LLM, single-line GBNF grammar,
`build_prompt` / `parse` / `plan`, deterministic post-validation → Decision Points. One LLM call,
closed vocabulary. The LLM picks **nouns + numbers only**; it never positions anything.

Output (validated):
```
{
  "room_size": { "w": <float 4..12>, "d": <float 4..12> },   # LLM chooses FIRST
  "props": [ { "category": <cat>, "material": <mat>, "count": <int 1..8, validator-capped> }, ... ]
}
```
- `category` ∈ `table | chair | shelf | cabinet | rug | painting` (closed).
- `material` ∈ `worn_oak | rough_granite | wrought_iron` (closed; existing palette).
- Bounds enforced deterministically (clamp + Decision Point on out-of-range), exactly like the
  asset planner's `PARAM_RANGES` and the npc-role validator.
- The LLM is told to choose a count *appropriate to the room it just sized* — density is the
  model's responsibility; the layout verifies it (below).

### 2. Deterministic layout — `foundry/room_layout.py` (NEW)
Pure Python, no LLM. Turns `(room_size, props)` into a **placed-entity manifest** with world
positions. Three placement surfaces:

- **Floor furniture** (`table/chair/shelf/cabinet`) → non-overlapping grid/ring inside the room,
  inset from the walls, keeping the player spawn (origin) and the NPC slot clear. Footprints come
  from `scene_compiler._COLLISION_SIZES`.
- **`rug`** → floor **underlay**: large, low, centered under a furniture cluster. **Overlap is
  intended** — a table sits on the rug. Tagged so the no-clip pass treats it as an underlay, not a
  collidable (see contract below).
- **`painting`** → **wall-mounted**: positioned flush against a wall at ~1.5 m height, `yaw` facing
  into the room. Walls are derived from `room_size` (same value the delegated wall renderer uses).

**Over-capacity = a Decision Point, never a silent clip.** The layout places floor furniture until
the room is full (no-overlap), then stops and emits `room.over_capacity`
("requested 18 floor props, placed 9, 9 over capacity for a {w}×{d} room"). This is the path the
deliberate over-supply stress test exercises.

`rug` and `painting` are **decor**: not pickable, not collidable, and **not eligible as the quest
target** (the `QuestBehaviourPlanner` target must remain a furniture prop the player can fetch).

### 3. Generate-on-demand — orchestration in the `quest` path
For each unique `(category, material)` in the manifest not already a GLB in `library_dir`, build it
via the existing single-asset `forge_from_request("a {material} {category}", lexicon_copy, lib)`,
gated and cached (skip if the GLB exists). **Never mutate the real `asset_lexicon.json`** — use a
`/tmp` copy per the standing rules. This is what makes rooms actually differ; it replaces the
hardcoded manifest in `_cmd_quest`.

### 4. Two new generators — Blender foundry
- **`rug`**: a thin flat panel (≈ 2–3 m × 0.02 m). Requires a **flat-prop tolerance** in `gate.py`
  (the gate currently assumes furniture-scale height) and a lexicon envelope entry.
- **`painting`**: a thin vertical panel + simple frame (≈ 0.6×0.05×0.8 m), authored to mount on a
  wall and face outward. Lexicon entry + grammar generator branch.
Both add a new generator branch to `grammar/asset_spec.gbnf` and `compiler.py`'s param ranges.

## The manifest contract (the seam with the delegated 1–5 workstream)

The manifest is the integration boundary. #6 **produces** it; the delegated compiler/renderer
**consumes** it. Both sides must implement the same extended entry shape:

```
{ "id", "category", "material", "x", "y", "z",
  "yaw": <float, default 0>,                 # wall-mount orientation
  "surface": "floor" | "underlay" | "wall",  # default "floor"
  "decor": <bool, default false> }           # decor → no collision, not pickable, not a target
```
Plus a top-level **`room_size: {w, d}`** carried into the scene/quest data.

**Coordination actions (relay to the CLI AI doing 1–5):**
- Walls **and** floor must size to `room_size`, not auto-derive from prop bounds.
- The no-clip pass (#3) must **skip `surface=="underlay"` and `decor==true`** entities (the rug is
  supposed to sit under furniture).
- `decor` entities get no collider and no `pickup` tag.

If the delegated work lands before this contract, the new fields are optional with safe defaults, so
old manifests still compile.

## Testing

- **Unit, stub LLM (no llama, no Blender):** RoomPlanner parses a themed plan → valid `room_size` +
  prop list; out-of-range size/count → clamped + Decision Point; layout places a normal plan with no
  overlaps; **over-supply plan → `room.over_capacity` Decision Point** with correct placed/dropped
  counts; rug placed as underlay (overlap allowed); painting placed on a wall with inward `yaw`;
  rug/painting excluded from quest-target eligibility.
- **Generate-on-demand:** a manifest referencing an unbuilt `(category, material)` triggers a build
  into a temp library (mock/lightweight Blender or marked live); existing GLB is reused, not rebuilt.
- **New generators:** rug + painting build, pass the (flat-tolerant) gate, load in Godot headless.
- **Godot-in-the-loop:** a scaffolded build from a generated manifest opens, instances all props,
  rug renders under furniture, painting renders on a wall, no missing-resource errors.
- **Stress test (the anticipated problem):** force counts at 2–3× room capacity; assert the layout
  stays non-overlapping for what it places and the over-capacity Decision Point fires — confirming
  over-supply is handled before it ambushes us.
- **Live, run-twice:** `quest` on 2–3 themed prompts, twice each (qwen stochastic); confirm the
  rooms visibly differ (size/props/counts/palette) and remain winnable.
- **Regression:** full foundry suite stays green; the old hardcoded manifest path is removed.

## Standing rules
All `AGENTS.md` rules apply: TDD red→green, foundry venv + determinism gate, **single-line GBNF
only**, never mutate the real `asset_lexicon.json` (use a `/tmp` copy), Godot-in-the-loop is the gate
(structural `.tscn` asserts are necessary but not sufficient), qwen is stochastic so any live claim
runs **twice**, commit-proof reporting, never patch `addons/godot_ai`.
