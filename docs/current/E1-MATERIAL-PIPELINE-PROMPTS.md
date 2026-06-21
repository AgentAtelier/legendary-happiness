# E1 — Procedural PBR Material Pipeline — Delegation Prompts

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task. Spec:
> `E1-MATERIAL-PIPELINE-DESIGN.md`. **This EXTENDS existing code** — `foundry/blender/build_asset.py`
> already has procedural materials (wood, `_metal_color_nodes`), UV unwrap, and `apply_roughness_bake`
> (packs a glTF metallicRoughness texture). Prior art to study: the legacy
> `legacy/archive/Worldforge-master/.../asset_factory/bake/bake_pipeline.py`. The big gaps are
> **normal maps and AO** (absent today) and **stone/fabric classes + the room shell**.

**Goal:** every prop and the room shell carry layered procedural PBR (albedo + roughness + metallic +
**normal** + AO) baked in Blender into the GLB — no grey boxes. AAA *ceiling*, incremental delivery;
"does not read as AI slop" is the bar (judged manually until **V** exists).

## Global Constraints (verbatim)

- **Testing split:** **[CLI]** runs the *fast* gates (`pytest tests/ -q` + `pytest
  tests/test_godot_smoke.py -q`, both green) per task, then hands off. **[ORCH]** does the visual +
  determinism verification (generate builds, hash determinism, user eyeballs) — do NOT run it.
- **Author in Blender, bake to GLB; Godot renders.** No Godot runtime shaders (offramp + "Python builds,
  Godot lives"). Mirror the existing `apply_roughness_bake` pattern for new bakes.
- **Determinism hazards (handle explicitly):** apply a **Triangulate modifier** before UV/bake (n-gons →
  non-deterministic triangulation); Blender noise nodes have **no seed port** → derive a **Mapping-node
  coordinate offset** from the seed (the existing builders already do this — follow it); set a **bake
  margin** (≥16 px) to stop seam bleed; bake normals in **OpenGL +Y** (Godot-native); non-color space
  for normal/roughness/metallic/AO images. Same (class, seed) ⇒ identical baked-texture hash.
- glTF packing: baseColor (sRGB), metallicRoughness (linear, G=rough/B=metal — exists), **normalTexture**,
  **occlusionTexture** (can pack AO into R of the ORM image). Never touch `addons/godot_ai`.

## Material classes (map from `materials.MATERIAL_PALETTE`)

oak/walnut→**wood**, granite→**stone**, wrought_iron→**iron**, linen→**fabric**. Starting params
(tune toward AAA): wood `#5c4033` rough .55–.70 metal 0 normal-low (grain+plank+edge-wear); stone
`#6e7275` rough .75–.90 metal 0 normal-high (Voronoi cells+cracks+cavity AO); iron `#b3b7b9` rough
.40–.55 metal 1 normal-med (scratch streaks+smudge); fabric `#c2b280` rough .85–.92 metal 0 normal-micro
(sine-weave + fuzz).

---

## Task 1 [CLI] — Procedural NORMAL + AO bake (the missing maps)

**Files:** `foundry/blender/build_asset.py`; `foundry/tests/` (a build-asset bake test, stub/headless-bpy
where possible, else gate via the existing asset-build test path).

**Add** two bake helpers mirroring `apply_roughness_bake`:
- `apply_normal_bake(obj, nodes, links, bsdf, seed, ...)` — build a noise→`ShaderNodeBump`→normal subgraph
  (seed-offset Mapping for determinism), Cycles **NORMAL** bake (OpenGL +Y), non-color image, margin ≥16,
  wire as the GLB `normalTexture`. This is the "bumpy" win.
- `apply_ao_bake(obj, ...)` — Cycles **AO** bake (or cavity via geometry/pointiness), pack into the
  occlusion channel (R of the ORM image) → glTF `occlusionTexture`.
- Apply both to the **existing wood + metal** materials first.

**Tests:**
- [ ] A built wood/metal asset GLB now carries a `normalTexture` and an `occlusionTexture` (parse the GLB).
- [ ] Determinism: same (category, material, seed) → identical normal-map bytes (hash).
- [ ] Run `pytest tests/ -q` + smoke. Commit: `feat(foundry): procedural normal + AO bake (E1 task 1)`.

## Task 2 [CLI] — Stone material class (new, full PBR)

**Files:** `foundry/blender/build_asset.py` (a `_stone_color_nodes` + material assembly); tests.

**Build** a layered stone node graph: Voronoi distance cells (cobble/granite) + fractal crack noise into
albedo + roughness; high normal intensity from the same height field; cavity AO. Route granite-family
materials to it. Full set: albedo/roughness/metallic/normal/AO baked.

**Tests:**
- [ ] A granite asset builds with stone nodes; GLB carries the full PBR set; deterministic hash.
- [ ] Run gates. Commit: `feat(foundry): procedural stone PBR class (E1 task 2)`.

## Task 3 [CLI] — Fabric class + AAA detail-layering for wood & iron

**Files:** `foundry/blender/build_asset.py`; tests.

- **Fabric** (`_fabric_color_nodes`): orthogonal sine-wave weave → micro-normal + soft roughness; route
  linen. Full PBR set.
- **Upgrade wood**: add directional grain (Wave node) + plank-seam variation + subtle edge wear (so it
  reads as real wood, not flat noise). **Upgrade iron**: anisotropic scratch streaks + smudge noise.

**Tests:**
- [ ] Linen asset builds with fabric nodes + full PBR set; wood/iron graphs include the new detail nodes;
  deterministic.
- [ ] Run gates. Commit: `feat(foundry): fabric class + layered wood/iron detail (E1 task 3)`.

## Task 4 [CLI] — Room shell (floor/wall/ceiling) baked materials

**Files:** `foundry/scene_compiler.py` (the floor/wall/ceiling sub-resources, ~L80–100) + however the
shell meshes get materials; tests.

**Replace** the flat-color floor/wall/ceiling `StandardMaterial3D` boxes with the library materials
(tiling): e.g. stone/plaster floor, plaster wall, plaster ceiling, chosen per theme. Either bake small
tiling GLB material panels or assign per-theme baked textures with `uv1_scale` repeat. Keep the ceiling
lit (fix-A) and walls thick (avoid GI leaks later).

**Tests:**
- [ ] Compiled scene's floor/wall/ceiling reference real material textures (not a flat albedo color);
  headless-load clean.
- [ ] Run gates. Commit: `feat(foundry): room shell baked materials (E1 task 4)`.

## Task 5 [CLI] — Determinism hardening + Godot import + handoff

**Files:** `foundry/blender/build_asset.py` (triangulate + margins audit), Godot import config; tests.

- Ensure a **Triangulate modifier** is applied before UV/bake on every generated mesh; confirm bake margins;
  audit that every noise uses a seed-derived Mapping offset.
- Godot side: ensure imported normal maps have the **normal-map flag** + textures set to **repeat**; confirm
  glTF ORM/normal/baseColor import as a correct `StandardMaterial3D`.
- [ ] Determinism test across all 4 classes: same seed → identical GLB texture hashes.
- [ ] `pytest tests/ -q` + `pytest tests/test_godot_smoke.py -q` green. Commit:
  `feat(foundry): E1 determinism hardening + Godot PBR import`. **Then hand off — do NOT run live/visual.**

---

## [ORCH] Verification — orchestrator only

After handoff: generate builds across a few themes (≥9B), confirm (a) **determinism** (same seed → same
texture hashes), (b) each prop + the shell carry the full PBR set (parse GLBs), (c) headless-load clean.
Then hand a build to the **user** for the **slop-wall visual judgment** (lighting + materials reading as a
real room, not grey boxes) — the headless gate can't see this, and **V** (the VLM loop) is not built yet.
Iterate on material quality from that feedback.
