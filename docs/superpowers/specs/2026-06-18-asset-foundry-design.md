# Asset Foundry — Design Spec

**Date:** 2026-06-18 · **Status:** approved design, pre-implementation · **Owner:** Forge

> **What this is:** the durable north-star design for how Forge produces real game
> assets. **What this is NOT:** an implementation plan. The first slice (§8) gets its
> own plan via `writing-plans`; later slices get theirs.

## 1. Objective function (read this first)

This project is not optimizing for "ship an open-world RPG cheaply with a small team."
If it were, the answer is trivial and known: use Unreal, buy an asset library. The
objective is **a novel, well-crafted system that someone who knows this space looks at
and says "huh — that's interesting."** Merit by being new/different and well-done.

That frame matters because it changes which advice is gold and which is risk-aversion.
External reviewers (optimizing for cheap shipping) converge on "don't generate, buy a
kit, let the LLM only place it." We **reject** that as the backbone — it abandons the
thesis. We **keep** their technical gold (below). The same reviewers would have told us
the *current* project (LLM builds Godot games) was too hard — and Phase C just proved
the load-bearing claim: **an LLM as art director over deterministic generation produces
coherent results.** The foundry is the asset-level proof of that same idea.

## 2. Where we are

- The live pipeline turns a prompt into a Godot scene: `ArchitecturePlanner` (LLM,
  GBNF-constrained delta) → `ArchitectureCompiler` (deterministic ops) → Godot. Phase C
  added `scale`/`rotation`; scenes read as coherent *layouts of primitives*.
- `engine/devforge/spatial/asset_lexicon.json` is a greybox kitchen lexicon: each entry
  (`table`, `chair`, …) has an empty `"path": ""`, a `footprint`, a `height`, and a
  `greybox` primitive. `lexicon.py::AssetLexicon.greybox_ops()` emits a `MeshInstance3D`
  box. The spatial compiler (`spatial/compiler.py`) already **decouples placement
  (footprint/height math) from the asset (`path`)**.
- We have real placement engines: `bsp.py`, `wfc.py`, `voronoi.py`, `scatter_planner.py`,
  `layout_planner.py`. **Placement is largely solved.** The open problem is *what fills
  `path`* — the asset itself — at handcrafted-stylized-PBR quality without "AI slop."

## 3. Core principle

The same move that beat scene-slop, one level down: **the LLM never authors geometry.**
It is an **art director** that *selects from a closed style vocabulary and fills
high-level parameters*; deterministic systems do every precise geometric, UV, material,
and topological operation. "Topologist, not geometer" — and crucially, **consistency is
enforced by construction (a closed grammar), not judged after the fact.**

## 4. Architecture

Two pipelines. The foundry is a **standalone offline tool**, decoupled from the realtime
request path; it produces a library the live pipeline consumes via the lexicon.

```
        LIVE PIPELINE (unchanged, 100% local, realtime)
  prompt ▶ ArchitecturePlanner ▶ ArchitectureCompiler ▶ Godot
                                           │ consumes assets via
                                           ▼
                                  asset_lexicon.json  ◀── `path` filled by foundry ──┐
                                  + placement engines (WFC/BSP/Voronoi/scatter)       │
                                                                                      │
        OFFLINE FOUNDRY (standalone tool, escalating model ladder)                    │
  asset request ─▶ AssetPlanner ─▶ AssetCompiler ─▶ Blender(headless) ─▶ Gate ─▶ Library
   (semantic +      (LLM fills      (params →        (GeoNodes build,    (validators   │
    style intent)   params under    GeoNodes node    UV/material/LOD,    + perceptual) │
                    a closed         inputs)         export .glb/.tscn)                │
                    grammar)                                                           │
                         ▲                                                             │
                         └────────────── escalate on gate-proven failure ─────────────┘
```

### Components (responsibility · interface)

- **AssetPlanner** — LLM, GBNF-constrained. Emits an **asset-spec**: a generator id +
  parameter values + style-vocabulary selections. *Never* raw vertices, *never* part
  transforms. Mirrors `ArchitecturePlanner`. Out: validated `AssetSpec` JSON.
- **Closed Style Grammar** — the anti-slop mechanism, enforced by the compiler. A finite,
  versioned vocabulary: **material palette** (e.g. 12 base materials × weathering variants,
  referenced by id — the LLM may not invent colors/shaders), **proportion families**
  (e.g. "chunky 1:0.6", "slender"), **edge/wear vocabulary** (chamfer/round/chip + moss/
  stain intensities), **metric grid** (snap to 0.25 m), shared **trim-sheet/atlas** for
  UVs. Specs referencing anything outside the grammar are rejected. *Consistency by
  construction.* Lives as data (`style_grammar.json`), not code.
- **AssetCompiler** — deterministic. Validates the asset-spec against the grammar, resolves
  the generator, and produces the **Geometry-Nodes input set** (scalars/vectors/booleans/
  material ids) for a Blender build. Mirrors `ArchitectureCompiler`. *It does the relative
  geometry reasoning the LLM must not* (this is what dissolves the "assembly is geometry"
  objection — the LLM picks `seat_height`, the generator/compiler computes leg positions).
- **Geometry-Nodes generators** — hand-authored, robust, parameterized Blender Geometry
  Node trees. **Tier 1 (default):** a toolkit covering hard-surface props/furniture/
  architecture. **Tier 2 (hero/important):** bespoke generators with richer detail. Both
  feed the same Blender runner → gate → library. GeoNodes (not raw `bpy`) guarantees
  manifold output and insulates us from `bpy` API churn; the LLM/compiler supplies *inputs*,
  never mesh code.
- **Blender headless runner** — loads the generator, applies the input set, bakes UVs to
  the atlas, assigns the palette material, generates LODs, exports `.glb`/`.tscn`. The only
  tool in the stack that does the full mesh→UV→material→LOD→export chain headless (the real
  reason for Blender — *not* "the LLM writes bpy well," which it doesn't; it fills params).
- **The Gate** — layered, **no VLM taste-judge**. (a) **Deterministic validators**
  (asset-class-aware): manifold/structural checks, polygon budget, **bounds vs the lexicon's
  `footprint`/`height`** (free ground-truth oracle), UV-overlap, material-from-palette.
  Note class-awareness: a campfire's logs *should* intersect — intersection is not a
  universal fail. (b) **Perceptual style-distance**: render canonical angles, compute
  CLIP/perceptual distance to reference style images; flag outliers. (c) **Batched human
  spot-check** (offline, amortized): thumbs on a contact sheet. A vision model may do cheap
  *denotation* ("does this render contain a 4-legged chair") but **never** scores "is this
  beautiful."
- **Library + lexicon integration** — accepted assets land in a content library; the
  foundry writes their path into the lexicon entry's `path`. **Open dependency (must be
  resolved in slice 1):** there is currently *no op to instance a `.glb`/`.tscn` into the
  live scene* — `greybox_ops()` only builds a `MeshInstance3D`. Per fork policy we **cannot
  patch godot-ai** to add an op, so the instancing path must use existing godot-ai
  capabilities (e.g. write a `.tscn`/`.glb` into the project and reference it via supported
  node/scene ops) or be adapted entirely DevForge-side. This is the one genuinely uncertain
  seam.
- **Model escalation ladder** — behind AssetPlanner: current local stack (qwen 4B/27B)
  default → heavier-local → cloud, escalated **per-asset-class only when the gate proves
  the local model can't pass** within N repairs. The gate is both quality control and the
  escalation trigger; failures map where the local ceiling actually is. Foundry is offline,
  so cost is amortized (generate once, reuse many).

## 5. Explicitly out of scope / later tiers

These are **deferred with a different method, not surrendered.** The boring furniture
proves the spine first.

- **Characters / NPCs / creatures** — parametric primitive assembly cannot do rigging,
  weight-painting, or stylized anatomy. Later tier: CC0/base-mesh + parametric clothing/
  equipment kitbash; the LLM parameterizes equipment, not anatomy.
- **Foliage** — needs leaf cards, wind shaders, cross-fade LODs. Later tier: dedicated
  foliage tooling + a few hero tree types instanced via `MultiMeshInstance3D`, the LLM
  driving scatter (which our `scatter_planner` already does).
- **Photoreal** — out of target; would force external black-box AI-3D back in.

## 6. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| **Parameter space is mostly garbage** — 95% of a generator's param combos look broken; the LLM doesn't know the good 5%; repair loop spins. | Generators expose *narrow, known-good* parameter ranges only; LLM mutates/recombines from a seed set of validated specs, never free-invents. The grammar is the guardrail. |
| **Generator authoring is real artist/tech-artist work** (the honest reviewer point). | Start with **one** generator (slice 1). Each generator is a deliberate investment; we climb only as each proves out. The AI's leverage is composition/variation/consistency, not mesh synthesis — we don't pretend otherwise. |
| **Instancing op doesn't exist + fork policy forbids patching godot-ai.** | Resolve in slice 1 using existing ops / DevForge-side adaptation; if genuinely blocked, that's a finding worth surfacing early, not late. |
| **VRAM** (16 GB AMD/ROCm) running LLM + Blender + perceptual model. | Foundry is offline/serial; stage steps (generate → free → render → free). CLIP is tiny. Heavy/cloud models are the escalation rung precisely because local headroom is thin. |
| **Procedural sterility** (clean but lifeless). | Edge/wear vocabulary + procedural noise/asymmetry baked into generators *by default*; materials do the "crafted" work (stylized PBR is ~80% material). |

## 7. Decomposition into slices

Each slice is a working, testable vertical (project convention).

1. **Spine prover** (§8) — one Tier-1 GeoNodes generator end-to-end into a live scene.
2. **Closed style grammar v1** — material palette + proportion families + grid as enforced
   data; compiler rejects non-compliant specs; one shared atlas.
3. **AssetPlanner + GBNF** — LLM fills the generator's params under the grammar (replaces
   the slice-1 hand-written spec).
4. **Perceptual gate** — CLIP/perceptual style-distance + contact-sheet human spot-check.
5. **Toolkit breadth** — N Tier-1 generators across a coherent kit; library + placement at
   scale through the existing spatial engines.
6. **Tier-2 bespoke generator** — one hero asset; escalation-ladder wiring.
7. **(Later) organics track** — characters/foliage via their own methods (§5).

## 8. Slice 1 — the spine prover (detailed; this is what we plan & build next)

**Goal:** prove the whole foundry spine on the simplest real asset, end-to-end into a live
Godot scene — deliberately the *easy* asset, to prove the plumbing before the artistry.

**Asset:** `table` (already in the lexicon with `footprint` 1.5×1.0, `height` 0.75). A
tabletop + 4 legs is the minimal non-trivial furniture and a clean first GeoNodes generator.

**End-to-end path the slice must demonstrate:**
1. A hand-authored **table Geometry-Nodes generator** (`.blend`) with a few narrow params
   (top thickness, leg radius, leg inset) and one palette material (e.g. `worn_oak`).
2. A **hand-written asset-spec** for the table (no LLM yet — slice 3 adds the planner): the
   generator id + param values + material id.
3. An **AssetCompiler** path that turns the spec into the GeoNodes input set.
4. A **Blender headless run** that builds, UV-bakes, assigns the material, exports
   `table.glb` (+/or `.tscn`).
5. **Deterministic gate**: manifold check, polygon budget, **bounds within the lexicon's
   table footprint/height**, material-from-palette. Reject → fail loud.
6. **Lexicon integration**: write the exported path into the `table` entry's `path`.
7. **Live-pipeline consumption**: the spatial compiler instances the real table instead of
   the greybox box. **Resolve the instancing-op dependency here** (existing godot-ai ops /
   DevForge-side; no godot-ai patch).
8. **Verify by eye**: screenshot the scene (reuse the C framing harness); a real table
   stands where a brown box used to.

**Done criteria:** a prompt that places a table yields a *generated, gated, stylized table*
in the live scene, verified by screenshot; `scripts/check.sh` green; TDD throughout.

**Explicitly deferred by slice 1:** the LLM planner (hand-spec for now), the full style
grammar (one material is fine), perceptual/CLIP gate (deterministic only), escalation
ladder, Tier-2, multiple generators, characters/foliage.

## 9. Why this over the alternatives (one paragraph)

External AI text-to-3D (Meshy/TRELLIS/Hunyuan): black-box meshes, retopo tax, style drift
= the slop we reject — and 24 GB+ CUDA models are off the table on 16 GB AMD/ROCm anyway.
Curated-kit-only: abandons the generative thesis; it's the buy-a-library path. Godot-native
procedural: under-tooled for UV/material/LOD. Freeform LLM `bpy`: high variance/slop. Our
path keeps the LLM a topologist, makes consistency structural, and uses Blender for what
only Blender does headless — while leaning on placement engines we already built.

## 10. Conventions

Slice-based vertical delivery; TDD; `scripts/check.sh` green; files ≤500 lines; engine
imports `devforge.`-absolute, hub imports bare; **fork policy: never patch godot-ai** —
adapt DevForge or use config. The foundry is a standalone offline module, not wired into
the realtime request path.
