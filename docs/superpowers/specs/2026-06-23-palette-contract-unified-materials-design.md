# Palette Contract + Unified Material System — Design Spec (CP‑1 + CP‑2)

**Date:** 2026-06-23
**Thread:** First sub-project of the hybrid coherence stack (the unified material / art-direction
layer). Establishes the palette *contract* and the *scene-assembly* material system that consumes it.

**Goal:** Kill "palette anarchy" slop and make heterogeneous geometry (procedural shell, props,
exterior flora, future neural) cohere by binding **color at scene-assembly** from a harmonized
per-scene palette, applied as **one shared material per material-class** (neutral structure texture
× palette tint, triplanar). One asset, any palette; recolor without re-baking.

End artifact: this spec → implementation plan → CLI-AI sprint.

---

## Context / why

- A `MATERIAL_PALETTE` (13 materials, `family` + colors + roughness/metallic) exists, but **colors
  are authored independently per material and baked into each GLB at build time** (`build_asset.py`).
  `worn_oak` is always `(0.6,0.4,0.22)` regardless of scene → no shared color harmony (the
  "palette anarchy" slop the external surveys flagged as a top, cheap-to-fix offender).
- The interior shell (`shell_materials.py`) bakes *pre-colored* stone/timber separately; props bake
  their own colors; nothing guarantees a coherent scene-level color story.

## Locked decisions (from brainstorm)

- **Render target = Hybrid** (PBR base, stylized roof later). This sub-project is the PBR base layer;
  the NPR roof is CP‑4.
- **Color binding = scene-assembly (tag + palette).** GLBs carry geometry + a material-class tag per
  surface; the compiler applies a per-class material colored from the scene palette. Recolor without
  re-baking; procedural + neural cohere by wearing the same palette.
- **Palette source = anchor + harmony rules.** Theme/biome contributes anchors + mood; a
  deterministic harmony function expands them into role colors.
- **Per-class textures are NEUTRAL** (grayscale structure); the palette supplies hue at assembly.

## Architecture

```
foundry/palette.py            # CP-1: build_palette(theme, seed) -> Palette  (anchors+mood → harmony)
foundry/material_classes.py   # CP-1: class taxonomy {stone,wood,foliage,rock,metal,fabric,soil,...}
                              #        each class -> {role, roughness, metallic, class_texture_id}
foundry/blender/class_materials.py  # CP-2: bake ONE neutral structure+normal+roughness set per class
                              #        (generalizes shell_materials; no color)
scene_compiler.py / exterior_compiler.py  # CP-2 consumer: per surface, read class tag -> emit/reuse
                              #        a StandardMaterial3D (neutral class texture, albedo tinted by
                              #        palette role, triplanar) and material_override it (strip incoming)
```

Each unit has one purpose: `palette` decides *colors* (engine-agnostic), `material_classes` is the
*taxonomy* + per-class params, `class_materials` produces *neutral surface detail*, the compiler does
*assembly-time binding*.

### Data model

```python
RGB = tuple[float, float, float]
Palette = {
    "roles": { "base": RGB, "shadow": RGB, "midtone": RGB, "highlight": RGB,
               "accent": RGB, "foliage": RGB, "sky": RGB },
    "classes": { "stone": {"role": "base", "roughness": 0.9, "metallic": 0.0,
                           "texture": "stone"},
                 "wood":  {"role": "midtone", "roughness": 0.7, "metallic": 0.0, "texture": "wood"},
                 "foliage": {...}, "rock": {...}, "metal": {...}, "fabric": {...}, "soil": {...} },
    "theme": str, "seed": int,
}
```

---

## Components

### C1 — `foundry/palette.py` (CP‑1: palette from anchors + harmony)

`build_palette(theme: str, seed: int = 0, anchors: dict | None = None) -> Palette`. Deterministic.

- **Anchors + mood** come from a small theme/biome table (extend the existing `THEME_TABLE`/
  `biome_table` with `anchors` = 1–3 RGB + `mood` = {`warm|cool|neutral`, `saturation`, `key` =
  `dark|mid|bright`}). Unknown theme → a generic neutral anchor set.
- **Harmony function** derives role colors from the anchors in HSV: `base` from the primary anchor;
  `shadow` = base darkened + slightly desaturated; `midtone`/`highlight` = value steps; `accent` =
  analogous/complementary hue shift; `foliage`/`sky` = mood-tinted bands. Value spread set by `key`
  (dusk/dark → compressed, lower). Seed perturbs hue/value within bounded ranges (so two seeds vary
  but stay on-mood).
- **Determinism:** same `(theme, seed, anchors)` → identical Palette. No wall-clock, no unseeded RNG.

### C2 — `foundry/material_classes.py` (CP‑1: taxonomy)

- `CLASSES`: the canonical material-class set: `stone, wood, foliage, rock, metal, fabric, soil`
  (extensible). Each maps to `{role, roughness, metallic, texture}` defaults.
- `class_for(material_id_or_family: str) -> str`: maps the existing `MATERIAL_PALETTE` families
  (wood/stone/metal/fabric/…) and prop categories to a class. Unknown → `"stone"` (neutral default).
- This is the bridge from the *old* per-material world to the *new* class world.

### C3 — `foundry/blender/class_materials.py` (CP‑2: neutral class textures)

- `blender --background --python class_materials.py -- <out_dir> [res]` bakes, per class, a NEUTRAL
  set: `class_<name>_{albedo,normal,orm}.png` where albedo is **grayscale structure** (value
  variation only, hue-neutral), so the palette tint at assembly fully controls color.
- Reuse `shell_materials.py`'s stone/timber node graphs for the `stone`/`wood` classes (desaturated
  to neutral); add `foliage`, `rock`, `soil` generators as the exterior needs them (v1 ships at least
  `stone`, `wood`; `foliage`/`rock`/`soil` may land with the exterior thread).
- 1024², triplanar-tileable, strong normals. Cached per class (palette-independent). `shell_materials`
  is superseded by this (its callers move to the class textures).

### C4 — Assembly-time application (`scene_compiler` / `exterior_compiler`)

- New `compile_scene(..., palette: Palette | None = None)`. When a palette is given:
  - For each placed surface, determine its **class**: from the GLB surface's material name if it is a
    known class tag, else `class_for(category/material_id)`.
  - Emit **one deduped `StandardMaterial3D` per class** present in the scene:
    - `albedo_texture` = `res://assets/class_<name>_albedo.png` (neutral),
    - `albedo_color = Color(*palette["roles"][class.role])` (multiply-tints the neutral structure),
    - `normal_texture` = class normal, `roughness`/`metallic` from the class,
    - `uv1_triplanar = true`, `uv1_world_triplanar = true` (UV-independent; neural-safe),
    - referenced as **ext_resource** textures (per the prior shell-texture fix — never
      CompressedTexture2D `load_path`).
  - Apply via `material_override` on each surface, **stripping** the GLB's shipped materials.
  - When `palette is None`, keep current behavior (back-compat).
- The shell (already overrides stone/timber children) becomes a consumer of the class materials.

### C5 — Migration / tagging

- **Procedural generators emit class tags:** `build_room_shell` surfaces `stone`/`timber` →
  map to `stone`/`wood`; `build_asset` tags by `family`.
- **Existing prop GLBs need no re-bake:** the compiler overrides them by `class_for(category)` →
  palette material. Their baked colors are discarded by the override.
- **`shell_materials.py` → `class_materials.py`:** move the stone/timber graphs over (neutralized);
  update `scaffold`/compiler to copy `class_<name>_*` instead of `shell_{stone,timber}_*`.
- Lighting untouched: the GI bake still grounds the palette materials.

---

## Determinism & caching

- `build_palette` deterministic; the Palette (its hash) joins the scene cache key so a recolor is a
  cache miss but a relayout is not.
- Class textures cached per class (palette-independent) — baked once, reused across all scenes/palettes.

## Error handling / fallbacks

- Unknown theme → generic neutral anchors. Unknown surface class → `stone` default. Missing class
  texture → flat palette color (albedo_color only, no texture) so a scene still renders.
- `palette=None` → existing pre-palette behavior (no regression for callers not yet passing a palette).

## Testing strategy

- **Unit (no Blender):** `build_palette` determinism; role relationships (`shadow` value < `base`
  value; value spread compresses for `key="dark"`; `accent` hue differs from `base`). `class_for`
  maps known families/categories correctly and defaults safely. `compile_scene(palette=…)` emits
  **one** triplanar material per class, albedo_color = the role color, textures as ext_resource, and
  applies `material_override` (incoming stripped); `palette=None` unchanged.
- **Blender-gated:** `class_materials.py` bakes neutral sets; albedo is near-grayscale (low mean
  saturation) so tinting controls hue.
- **Visual (orchestrator):** render ONE scene under TWO palettes (e.g., warm-dusk vs cold-stone) to
  prove recolorability and coherence; confirm props/shell share the color story.

## Out of scope (later CPs)

- NPR/stylized shader + post-process LUT/quantize/outline (CP‑4).
- Scale/silhouette geometry normalization + neural surface classification + retopo/re-UV (CP‑3).
- Per-class `foliage/rock/soil` generators may be deferred to the exterior thread if not needed for
  the interior showcase.

## Open items (tunable during implementation)

- Exact harmony math (hue offsets, value steps) — tuned against the two-palette render.
- Whether triplanar is always-on or only for surfaces with bad/missing UVs (default: always-on for
  consistency; revisit if small props show projection artifacts).
- The full role set may grow (e.g., `metal_accent`, `trim`) as classes are added.
