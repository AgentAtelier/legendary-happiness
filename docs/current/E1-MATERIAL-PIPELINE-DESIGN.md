# E1 — Procedural PBR Material Pipeline (Design)

**Date:** 2026-06-21. **Status:** approved (brainstormed). Sub-project of **E (visual fidelity)**.
**Informed by:** 4 deep-research reports (`VISUAL-RESEARCH-PROMPTS.md` outputs) — convergent on order,
split on bake-vs-shader and GI. **Decisions captured below.**

---

## 1. Goal & governing principle

Build a procedural material pipeline whose **design ceiling is AAA-grade PBR**, delivered
incrementally. The acceptance criterion is **"does not read as AI slop"** — the existential wall:
players and tool-users dismiss on sight, before they experience the depth underneath. So no shortcut
may structurally cap fidelity, even though we climb toward it over iterations ("not all-in this week").

**Two locked architectural decisions (with rationale):**
- **Author materials in Blender, bake to GLB; Godot renders.** Chosen over Godot runtime shaders for a
  *strategic* reason: it keeps all asset authoring in Blender — preserving the "standalone Blender asset
  generator" offramp and leveraging Blender's vast PBR/baking documentation — and it is the purest form
  of *"Python builds the world, Godot lives it"* (the asset is fully finished in the Blender stage).
  The technical cost (baking needs UVs; per-asset texture files) is handled in §4/§5.
- **Visual quality verification is deferred to V** (the VLM visual-eval loop, its own sub-project). E1
  ships with deterministic structural tests; quality is eyeballed manually until V exists.

## 2. Scope

**In (E1):** the bake pipeline + a layered procedural material library for the **4 core classes**
(wood / stone / iron / fabric) + integration so **every prop AND the room shell** (floor/wall/ceiling)
gets baked PBR + Godot import wiring. Reuses the fix-A interior lighting/post-processing.

**Out (later sub-projects):**
- **E2** — second-generation prop *geometry* (bevels, subsurf, baseboards/trim, greeble via `bpy`).
- **V** — the VLM visual-eval loop (screenshot harness + local VLM checks + regression). Separate brainstorm.
- Additional material classes (plaster, brass, leather, ceramic…) — added after the 4 core prove out.
- Runtime Godot shaders / triplanar-in-Godot — explicitly not taken (we bake in Blender).

## 3. Architecture (4 parts)

```
generate mesh (bpy)
   └─► [Material Library] seeded node-graph builder (wood|stone|iron|fabric)
          └─► [Bake Pipeline] triangulate → Smart UV unwrap → bake {albedo,roughness,metallic,normal,AO}
                 └─► pack into GLB (glTF PBR: baseColor / metallicRoughness / normal / occlusion)
                        └─► Godot auto-imports PBR → StandardMaterial3D  (fix-A lighting/post renders it)
   Room shell (floor/wall/ceiling) ─► same Material Library (tiling) ─► baked materials
```

1. **Material Library** (`materials.py` extended, or a new `pbr_materials.py`): each class is a
   deterministic function `build_<class>_material(seed) -> bpy material` constructing a **layered**
   Principled-BSDF node graph (base + detail + normal-from-noise + cavity-AO). "Layered" is what makes
   AAA reachable — not a single flat noise.
2. **Bake Pipeline** (`bake_pbr.py`): mesh-agnostic. Triangulate → Smart UV → assign material → bake the
   full map set at resolution → return texture paths for GLB packing.
3. **Room shell**: `scene_compiler.py`'s flat floor/wall/ceiling `StandardMaterial3D` boxes are replaced
   by meshes carrying baked tiling materials from the library (granite/plaster floor, etc.).
4. **Godot**: nothing new to author — GLB PBR auto-imports; set normal-map import flag + texture repeat;
   reuse fix-A `OmniLight` rig + ACES/SSAO/bloom.

## 4. The 4 core material classes (starting parameters)

Layered node graphs; values are the *starting palette* (from research report 1 + our `MATERIAL_PALETTE`),
to be tuned toward the AAA ceiling. Map from today's palette: oak/walnut→**wood**, granite→**stone**,
wrought_iron→**iron**, linen→**fabric**.

| Class | Base albedo | Roughness | Metallic | Normal intensity | Detail layers |
|-------|-------------|-----------|----------|------------------|---------------|
| **wood** | `#5c4033` | 0.55–0.70 | 0.0 | low | directional grain (Wave node) + plank variation + edge wear |
| **stone** | `#6e7275` | 0.75–0.90 | 0.0 | high | Voronoi cells + fractal cracks + cavity AO |
| **iron** | `#b3b7b9` | 0.40–0.55 | 1.0 | medium | anisotropic scratch streaks + smudge noise |
| **fabric** | `#c2b280` | 0.85–0.92 | 0.0 | micro | orthogonal sine-wave weave (tight) + fuzz normal |

Each class: full set → albedo, roughness, metallic, **normal (noise→Bump→bake)**, AO. Per-instance
variation via a seed-derived Mapping-node coordinate offset.

## 5. Determinism & testing

**Determinism hazards (handle explicitly — from the research):**
- **n-gons → non-deterministic triangulation.** Apply a **Triangulate modifier** before UV/bake.
- **Blender noise nodes have no seed port.** Use a **Mapping node coordinate offset** derived from the
  seed as the pseudo-random seed (stable, unique per instance).
- **Bake bleed.** Set a **bake margin** (e.g. 16 px) to stop low-mip seam color bleed.
- Fixed `random.seed`, sorted iteration, normal bake in **OpenGL +Y** (Godot-native), non-color space for
  normal/roughness/metallic/AO maps. Same (class, seed) ⇒ stable GLB.

**Tests (deterministic, headless-friendly — [CLI] runs these):**
- Each `build_<class>_material(seed)` constructs a valid node graph without error.
- The bake pipeline on a unit mesh yields a GLB carrying the full PBR set (baseColor/metallicRoughness/
  normal/occlusion present).
- Determinism: same (class, seed) → identical baked-texture hash.
- Godot smoke gate still loads the PBR GLBs (no import/material errors).

**Quality verification:** deferred to **V**. Until then, the **orchestrator** generates a build and
**the user eyeballs** a couple of screenshots for the slop-wall judgment (the headless gate can't see).

## 6. Interfaces & integration points

- `materials.py` `MATERIAL_PALETTE` (5 materials) → mapped to the 4 classes; `compiler.py:34` material
  validation unchanged.
- Wherever the asset generators build the flat Principled-BSDF material → swap in the library call +
  bake step before GLB export.
- `scene_compiler.py` floor/wall/ceiling sub-resources → baked-material meshes.
- Reuse fix-A lighting/post (no change).

## 7. Connection to the wider plan

E1 is the foundation the rest of E sits on: **E2** (geometry) gives these materials richer surfaces;
**V** (visual-eval) becomes the instrument that judges and regression-guards E1/E2 toward the AAA
ceiling. The material library is built to extend (more classes) without re-architecting.
