# Asset Quality Bump — "Kill the Procedural Tell" (Hard-Surface)

**Date:** 2026-06-18
**Branch:** `feat/foundry-quality-bump` (off `feat/foundry-name-by-material`)
**Scope:** Hard-surface foundry assets only. Organic forms are the *next* slice (a method brainstorm), explicitly not here.

## Goal

Make foundry hard-surface assets read as **handcrafted**, not generated, by fixing the three
highest-consensus "tells" identified by four independent technical-art reviews:

1. **Stripey wood** — procedural grain reads as parallel corduroy, not natural wood.
2. **CAD-perfect silhouette** — geometry is too symmetrical and clean to read as a physical object.
3. **Ungrounded surfaces** — no ambient occlusion, so forms float instead of sitting in their own crevices.

**Hard constraint: no engine-contract change.** Assets still ship as one textured GLB instanced via
`node_create(scene_path=...)`. In particular, ambient occlusion is baked **into the baseColor texture**,
*not* into vertex colors — because Godot only honours glTF vertex colors when
`vertex_color_use_as_albedo` is set on a `StandardMaterial3D`, and Blender's glTF vertex-color export is
historically version-dependent. Baking into baseColor sidesteps both. (Confirmed against the Godot 4.7
release, which makes no glTF/vertex-color changes.)

## Why these three (and not the bigger swings)

The four reviews converged hard on exactly these three as the cheap, high-impact levers. The bigger ideas
they raised are deliberately **banked, not in scope**:

- Baking stylized lighting *into* the albedo — changes the engine lighting contract; a real decision, not a freebie.
- `AreaLight3D` (Godot 4.7) soft lights — a *scene/presentation* lever, not a foundry change.
- The "blind art-director" CLIP critic loop (render → score vs reference bank → mutate) — its own slice; touches the llama stack.
- Trim sheets / kit-of-parts assembly — larger architectural shifts.

## Architecture

Three independently committable TDD tasks, in order. Each ends with `pytest` green and (for the visible
ones) an eyes-on check on the live RPG table. The deterministic **gate** (`foundry/gate.py`:
watertight on position-welded topology, poly budget ≤ 2000, bounds within the lexicon envelope +15% tol)
is the guardrail every task must keep satisfied.

### Task 1 — Wood shader: object-space, warped, stepped

**File:** `foundry/blender/build_asset.py` → `apply_material()`

The current node graph is `Wave(BANDS, direction X, distortion 1.5) → ColorRamp(LINEAR) → EMIT bake` on
default (Generated) coordinates. That is the corduroy source: axis-aligned bands with a smooth gradient.
Replace with the reviewers' consensus recipe:

- Drive the wave from **object space**: `TexCoord(Object) → Mapping → Wave.Vector`, with an anisotropic
  Mapping scale so grain runs along the asset's long axis (e.g. scale ≈ `(1, 1, 8)`).
- **Warp the coordinate before it is measured**: `Noise Texture → Vector Math(Multiply, small factor)`
  added into the Mapping vector feeding the wave. This is the actual anti-stripe move — it bends parallel
  bands into flowing grain.
- Raise the Wave `Distortion` and `Detail`.
- Switch the ColorRamp interpolation from `LINEAR` to **`CONSTANT`** with 3–4 discrete stops — the stepped,
  painted-band read that makes stylized wood look hand-finished rather than digital.
- Offset the Mapping `Location` by the **per-asset seed** (from Task 2) so two same-material assets are
  not pixel-identical.

**Tests:** build a table → build passes the gate; the baked texture is non-uniform (pixel variance above a
threshold) and not a single axis-aligned periodic pattern. The aesthetic verdict is an eyes-on check on the
live table, *not* a unit assertion — do not encode taste as a brittle pixel equality.

### Task 2 — Entropy `age` knob: break the CAD silhouette

**Files:** `foundry/compiler.py`, `foundry/grammar/asset_spec.gbnf`, `foundry/planner.py`,
`foundry/blender/build_asset.py`

`age` is a **first-class top-level spec field** (peer of `material`). It cannot live inside `params`,
because `compile_spec` rebuilds `params` from `PARAM_RANGES[generator]` only and would silently drop it.

- **Range and floor:** `age ∈ [0.15, 1.0]`. The non-zero floor (0.15) guarantees every asset gets a baseline
  of imperfection even when the request says nothing about wear — this is the "always slightly imperfect"
  guarantee, achieved without a second mechanism.
- **Compiler** (`compiler.py`): validate `age` is a number in `[0.15, 1.0]`; default to `0.15` if missing;
  include it in the compiled-spec output.
- **Grammar** (`asset_spec.gbnf`): add `"age": number` to `root` as a **single-line** addition (multi-line
  `|` alternations silently disable GBNF — keep it one line; `normalize_gbnf` already guards this).
- **Planner** (`planner.py`): clamp `age` to `[0.15, 1.0]`, default `0.15`; add wear vocabulary to the prompt
  ("old / battered / rustic / weathered" → high; "new / fine / polished / pristine" → low).
- **Deterministic seed:** derive a seed from the spec (e.g. a stable hash of `asset_id` + `material`) and use
  a **seeded** RNG for all deformation. The build must be reproducible — the gate and the test-suite depend
  on determinism. Two identical specs must produce byte-identical meshes.
- **New `apply_entropy(mesh, age, seed)`** in `build_asset.py`: bounded deformations whose magnitude scales
  with `age` — leg taper, slight per-leg splay/lean, tabletop sag (centre vertices down), a small global
  twist, and sub-millimetre per-vertex displacement along normals. **Cap every magnitude** so the result
  stays well inside the gate's +15% bounds tolerance and stays watertight on the welded mesh.
- **Call order:** `build_geometry → apply_entropy → apply_bevel → assign_uvs → apply_material`. Deform the
  base geometry *before* bevelling so bevel loops are not pinched.

**Tests:** `age` out of range clamps to `[0.15, 1.0]`; missing `age` defaults to `0.15`; the same spec
produces an identical mesh across two builds (determinism); a deformed mesh still passes the gate
(watertight + bounds); `age=0.15` vs `age=1.0` produce a measurably different vertex spread.

### Task 3 — Ambient occlusion baked into baseColor: ground the asset

**File:** `foundry/blender/build_asset.py` → `apply_material()`

Reuse the existing EMIT-bake path exactly — only the colour feeding it changes:

- Add a `ShaderNodeAmbientOcclusion` node (small `Distance`, e.g. 0.2 m).
- `MixRGB(MULTIPLY)` the ColorRamp colour by the AO output, and feed *that* into the EMIT node that is baked
  (and into the Principled Base Color for the live shader). The single baked baseColorTexture now carries
  albedo × AO. No vertex colors, no engine flag.
- **Optional, same bake, cheap:** `NewGeometry.Pointiness → subtle edge darken/lighten` for stylized edge
  wear. Deferred unless it drops in trivially — not required for the task to land.

**Tests:** for a known mesh, the baked texture has lower pixel means in occluded regions (e.g. under the
tabletop / leg-to-top junction) than on open faces; build still passes the gate.

## Cross-cutting requirements

- **Determinism:** all randomness is seeded from the spec; reproducibility is asserted. No wall-clock or
  unseeded RNG anywhere in the build path.
- **The gate is the guardrail:** every task keeps assets watertight and in-bounds. Entropy magnitudes are
  capped to respect it.
- **No engine-contract change:** still one textured GLB via `node_create`. Close out with a live-verify on
  the RPG table.
- **Scope discipline:** hard-surface only. No organic work, no lighting-into-albedo, no critic loop, no
  refactors beyond what these three tasks require.

## Test command

```
cd foundry && .venv/bin/python -m pytest tests/ -q
```

Live build/render tests additionally need llama on `:8002` and Blender (installed). Run `python -m foundry`
from the **repo root**, never from inside `foundry/`.

## Out of scope (banked for later)

Organic assets (Geometry-Nodes method brainstorm — the next slice), baked-lighting-into-albedo, `AreaLight3D`
scene lighting, the CLIP critic loop, trim sheets / kit-of-parts. None of these are touched here.
