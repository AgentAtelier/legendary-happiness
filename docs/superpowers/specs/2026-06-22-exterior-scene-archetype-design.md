# Exterior Scene Archetype — co-located biome + linked room (design)

**Date:** 2026-06-22
**Status:** Design — pending user review → `writing-plans`
**Owner:** orchestrator (live verification) + delegated implementation

## 1. Goal & scope

Generate a single deterministic Godot scene that is a **bounded outdoor biome** (terrain + open sky +
procedural flora) with the **existing room placed on it as a building** the player can walk into and
out of. One prompt yields *both* an interior theme and an exterior biome. This is **Approach A**:
everything co-located in one scene — no streaming, no scene-swap.

**Why this, why now.** It generalizes the engine from a *room generator* into a *space generator*:
rooms and exterior biomes become sibling archetypes on the same Brief/spine, which is the core "general
embodied-3D engine" thesis. It also gives an immediate, felt sense of a connected world (step out of
the cabin into the clearing) rather than a box.

**Hard constraints (unchanged from the rest of Forge):**
- **Pure-generative, no authored assets** — terrain, flora meshes, materials all synthesized from code.
- **Deterministic** — identical spec → byte-identical build (the gate enforces this).
- **Single 16 GB GPU, build-time** — bounded scene; GPU instancing for flora.
- **Python builds, Godot lives** — all decisions/baking at build time; Godot renders/loops.

**Non-goals (YAGNI — explicitly NOT in this spec):** streaming/chunking; multiple buildings; a weather
system (day/night already exists); a traversable landscape between locations (ladder rung 6);
interior↔exterior *scene-swap* (it is one co-located scene); LOD beyond MultiMesh; broadleaf-tree
realism (start with forgiving forms — conifers, shrubs, noise-displaced rocks).

## 2. Guiding principle for LLM use

> The LLM produces **structured intent captured into the seeded spec**; deterministic code does all
> **realization**. Same spec → byte-identical build.

The LLM lives in the **Interpretation** layer only (biome recipe, place naming/lore), never the
numeric/geometry layer (terrain heights, scatter positions, mesh vertices, roof angles). Every LLM
field is **validated + clamped to safe ranges**, with a **deterministic fallback + a Build-Report
line** — exactly how the codebase already handles material/age/soul. This is what makes LLM use here an
extension of a proven pattern, not new risk.

## 3. Architecture & data flow

```
prompt
  └─► Interpreter (LLM, json_schema)
        → Brief{ theme_tag, scale, key_features, characters[].soul,
                 exterior:{ enabled, structure, biome_recipe }, place_names }
        ├─► RoomPlanner(brief)        → interior manifest (props, NPCs)     [UNCHANGED]
        └─► ExteriorPlanner(brief,seed)→ ExteriorPlan{ terrain, building_pad,
                                          scatter_placements, biome, names }  [NEW]
  └─► asset foundry (Blender): bakes prop GLBs + terrain GLB + flora GLBs
  └─► scene_compiler(exterior mode): fuses interior + exterior → one .tscn
  └─► Build Report (+ exterior legibility lines)
```

**Backward compatibility:** `exterior.enabled == false` (the default) bypasses `ExteriorPlanner` and the
exterior emit path entirely → today's pure-interior build, byte-identical. Every new code path is gated
on `enabled`.

## 4. Brief extension

```jsonc
"exterior": {
  "enabled": false,                       // default → backward compatible
  "structure": "cabin|tower|tent|ruin|hut",
  "biome_recipe": {                        // LLM intent, clamped to BIOME_TABLE ranges (§6.1)
    "base_biome": "<tag from BIOME_TABLE>",// the safety floor + fallback
    "flora_mix": [ {"category": "<flora cat>", "weight": 0.0} ],
    "ground_palette_hint": "<material tag>",
    "density": "low|medium|high",
    "atmosphere_mood": ["<adjective>", ...]
  }
},
"place_names": {                           // LLM flavor, text-only (§6.2)
  "scene_name": "<short place name>",
  "landmark_lore": [ {"landmark_id": "<id>", "line": "<one-line history>"} ]
}
```
The interpreter emits these **in the same `json_schema` call** that already produces the Brief — ~one
extra structured response per build, build-time only.

## 5. Components (each an isolated, testable unit)

| Module | Responsibility | Key interface | Determinism |
|---|---|---|---|
| `biome_table.py` | Static data: per-biome terrain/flora/ground/atmosphere params (mirrors `brief.THEME_TABLE`) | `BIOME_TABLE: list[dict]`; `resolve_biome(brief) -> BiomeParams` | pure data |
| `biome_recipe.py` | Parse+validate the LLM `biome_recipe`; clamp to the resolved base-biome ranges; fallback to pure table | `validate_biome_recipe(raw, base) -> (recipe, decisions)` | pure |
| `terrain_field.py` | **Shared** deterministic heightfield (seeded value/FBM noise, numpy). Used by BOTH the planner (height queries) and the Blender builder (mesh displacement) so they never diverge | `height_at(field, x, z) -> y`; `slope_at(field, x, z) -> float`; `make_field(params, seed) -> Field` | pure, seeded |
| `blender/_build_terrain_geometry` | Displace a subdivided plane via `terrain_field` → terrain GLB + ground material | `(params, seed) -> mesh` | seeded |
| `blender/_build_{tree,shrub,rock}_geometry` | Parametric flora meshes (branching conifer, shrub clump, noise-displaced rock); registered `kind="flora"` in `category_registry` | `(params) -> mesh` | seeded |
| `scatter.py` | Distribute flora on the field by density + slope/altitude masks; exclude building footprint + door corridor | `scatter(field, biome, seed, exclusions) -> [FloraPlacement]` | pure, seeded |
| `exterior_planner.py` | Orchestrate: choose building pad, flatten terrain under it, compute exclusions, scatter, assemble `ExteriorPlan` | `plan_exterior(brief, seed) -> ExteriorPlan` | pure, seeded |
| `scene_compiler` (exterior path) | Emit one `.tscn`: terrain MeshInstance + ground mat, `WorldEnvironment` (open sky + biome atmosphere + existing day/night), flora as `MultiMeshInstance3D`, the building (room shell + roof + door cut) seated on the pad, interior props/NPCs, player spawn, door threshold node | `compile_exterior(ext_plan, interior_manifest, ...) -> tscn_text` | deterministic |

`FloraPlacement = {category, x, y, z, yaw, scale}` (y from `height_at`). `ExteriorPlan` carries
`terrain_params`, `building_pad{center, footprint_poly, pad_height}`, `scatter_placements`, `biome`,
`names`.

## 6. LLM foldings (detail)

### 6.1 Biome-as-recipe (YES #1)
- The interpreter emits `biome_recipe` (§4). Post-parse, `validate_biome_recipe`:
  1. resolves `base_biome` against `BIOME_TABLE` (unknown → nearest/`"*"` generic grassland + a
     `exterior.biome_fallback` Decision Point);
  2. keeps only `flora_mix` categories present in the base biome's allowed flora set; renormalizes
     weights; clamps `density` to the enum; ignores unknown `ground_palette_hint` (→ table default).
- The deterministic `ExteriorPlanner`/`scatter` consume the **validated** recipe, with the table as the
  floor. Result: "a bioluminescent fungal swamp at dusk" composes a tailored flora/palette/atmosphere
  within safe ranges instead of snapping to one of N fixed biomes. The recipe is part of the parsed
  Brief (the spec) → determinism preserved.

### 6.2 Place naming + micro-lore (YES #2)
- The interpreter emits `place_names` (§4): a `scene_name` and `landmark_lore`. In THIS spec the only
  realized landmark is **the building** (`landmark_id="building"`); the `landmark_lore` list is an array
  so it is forward-compatible with future POI clusters (ruins/cairns), which are NOT built here. Text
  only; captured in the spec.
- **Surfacing:** (a) Build-Report lines ("Place: *Hollowpine Rest*"; landmark lore); (b) in-world
  **examine** text via the existing `examine_validator` + dialogue UI (deterministic length/validation +
  canned fallback). No geometry, no determinism risk.
- Down-payment on the deferred POI-vignette backlog; does outsized work for the *worldbuilding feeling*.

## 7. The room↔exterior link (the symbolic part)

The room's **existing shell IS the building exterior.** We add only:
- a generated **roof** (pitch/flat per `structure`),
- a **door opening** cut into one wall (replace a wall segment with a framed gap), and
- seat the footprint on a **flattened terrain pad** (so it is flush, never floating/clipping).

The player **spawns outside, facing the building's door**, so the first thing seen is the biome + the
structure (maximizing the felt "I'm in a world" payoff). One scene, **no loading**: the player walks
through the door gap between exterior and interior. Interior keeps its lights; exterior uses the sun;
the doorway is the light/occlusion boundary. A **door-clearance + spawn→door→interior reachability**
guard (reusing the existing C-0 door-clearance concept) guarantees passage; flora exclusion keeps the
entrance clear.

## 8. Determinism, performance, guards

- **Determinism:** all noise/scatter/placement seeded from the spec; `terrain_field` is the single
  shared heightfield so planner queries and Blender displacement never diverge. Byte-identical builds
  (gate requirement). LLM fields are captured into the spec, so they too are deterministic per spec.
- **Performance:** bounded terrain (~40×40 m); flora via `MultiMeshInstance3D` GPU instancing with a
  per-biome instance budget; one scene on the single GPU.
- **Guards (each = a deterministic check + a Build-Report line):** pad-flush (building not floating);
  door reachability; biome↔theme coherence; no flora inside footprint/entrance corridor; poly/lexicon
  gate on terrain + flora GLBs.
- **Fallbacks:** biome unresolved → generic grassland; flora generator failure → rocks only; invalid
  biome_recipe → pure table. Every fallback emits a Decision Point so the report *says* it downgraded.

## 9. Build Report additions (Legibility pillar)
New lines: biome understood + recipe applied (or "fell back to table"); place name; landmarks + lore;
flora scattered (counts per category); structure built; any "couldn't" downgrades.

## 10. Testing

- **Unit (no Blender/LLM):** `resolve_biome`; `validate_biome_recipe` (clamp/fallback/renormalize);
  `terrain_field` determinism (same seed → identical heights) + planner/Blender field parity;
  `scatter` determinism + exclusion zones (nothing in footprint/door corridor); pad-flush math;
  spawn→door→interior reachability oracle; Brief `exterior`/`place_names` validation.
- **Blender build:** terrain + tree/shrub/rock GLBs generate and pass the gate (watertight/poly/lexicon).
- **Godot smoke:** headless-load the exterior scene with 0 `SCRIPT ERROR|Parse Error|Failed to load`;
  `probe_playthrough.gd` walks outside → through the door → inside.
- **V (visual-eval):** Qwen3-VL on exterior screenshots — reads as a coherent outdoor place; building
  sits on the ground (no floating/clipping); flora not floating; biome matches the interior theme. A
  brand-new archetype is exactly what V exists to gate.
- **Live (orchestrator):** "a hunter's cabin in a snowy clearing," run-twice — coherent biome+interior,
  recipe/naming sane across ≥9B models, walk-in works. (Stub-LLM unit tests cover the deterministic
  side; the live run is flagged for the orchestrator.)

## 11. Risks & open questions
- **Flora fidelity is the top risk** — pure-procedural plants can look like garbage. Mitigation: start
  with forgiving forms (conifers, shrubs, noise-displaced rocks), let V gate them, defer broadleaf.
- **Field parity** between the pure-Python planner sampler and the Blender displacement must be exact —
  hence one shared `terrain_field` module, covered by a parity test.
- **Door cut in the existing shell** — the room shell generator must be extended without regressing the
  pure-interior path; the cut + roof are gated on `exterior.enabled`.
- **Open:** exact terrain extent and per-biome instance budgets are tuning values, settled during
  implementation against the perf budget and V.
