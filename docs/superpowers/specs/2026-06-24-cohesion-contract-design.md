# The Cohesion Contract — Design Spec

**Date:** 2026-06-24
**Status:** DESIGNED — parked in the futurelog, **implementation deferred until Milestone M1 is done**.
**Origin:** the "tweak-forever" problem (every scene needs manual lighting/parameter tuning) +
the instinct to put all anti-AI-slop visual measures in one place.

## The problem

Generated parameters (lighting brightness, terrain slope, contrast, …) rarely land "good enough"
on the first try, so a human tweaks every scene. A fixed global target would fix that but produce
**slop** — every scene the same. The real goal is **coherent AND different**: a dim dungeon must
read differently from a sunlit market, while both share one craft/quality language.

## Core idea

**Centralize the *contract* (policy/values), distribute the *mechanisms* (enforcers).**

Putting all anti-slop *mechanisms* in one module would recreate the `scene_compiler` god-file the
audit flagged — they run at different pipeline stages (materials at build, geometry at import,
lighting at scene, NPR/grade at render, auto-correct post-render). What *should* be centralized is
the **policy**: the single source of truth for "what a Forge scene looks like."

> **The Cohesion Contract** = one spec object, derived from the Brief, carrying every anti-slop
> *facet*. Every enforcer stays small and stage-local but **reads from this one contract.**

This resolves coherent-vs-different structurally: **one spec shape (coherence), parameterized by
the Brief's intent (difference).** A dungeon and a market are two instances of the same contract —
same craft, different mood.

## The contract shape

```python
CohesionSpec = {
    "intent":     { "mood": str, "key": "dark"|"dim"|"neutral"|"bright",
                    "temp": "warm"|"cool"|"neutral", ... },   # from the Brief; LLM-fillable,
                                                              # enrichable over time
    "palette":    { "roles": {...}, "classes": {...} },       # COLOR facet — CP-1/CP-2 (BUILT)
    "atmosphere": { "luminance_band": (lo, hi),               # ATMOSPHERE facet — THIS spec's
                    "contrast_band": (lo, hi),                #   first build
                    "warmth_band":  (lo, hi),
                    "fog_band":     (lo, hi) },
    "geometry":   { "scale_rules": ..., "silhouette_rules": ... },  # CP-3 facet (later)
    "style":      { "npr_mode": ..., "post_grade": ... },     # CP-4 facet (later)
}
```

- `build_cohesion_spec(brief, seed) -> CohesionSpec` is the **single derivation point**.
  `palette.build_palette` becomes the palette facet (refactor, no behavior change); the atmosphere
  facet derives intent-relative **target bands** from the Brief's mood/key.
- **Enforcers read the spec, never hardcode policy:** `scene_compiler` reads `palette` (materials) +
  `atmosphere` (lighting params/exposure); the auto-corrector reads `atmosphere` bands; future
  geometry/style enforcers read their facets.

## First facet — Atmosphere / Lighting

The thing causing pain now. Three pieces:

1. **Intent → bands (the authored policy, small).** A `MOOD_BANDS` table maps each mood/key
   archetype to target bands, e.g. `dark` → `luminance (0.10, 0.20)`, `bright` → `(0.45, 0.62)`,
   `dim/dusk` → `(0.22, 0.34)`; plus contrast/warmth/fog bands. **This is the entire authoring
   burden — a handful of bands, not a value-per-scene database.** The Brief's mood (already inferred
   by the interpreter) selects the band. (Start with archetypes; the LLM can enrich the intent
   toward "oppressive, cold, single shaft" later — the contract is the home for both.)

2. **Planner aims for the band.** `lighting_planner` already carries mood/key; it now reads the
   spec's atmosphere bands and generates energies/exposure/fog aiming for them (so most scenes are
   close before any correction).

3. **The corrector ENFORCES the band (measurable-first).** After the build, render a **cheap tier-0
   probe** (realtime, low-res, no bake), measure **mean luminance** (+ % blown). If outside the
   *intent* band, correct — for luminance the corrector is **auto-exposure**: `exposure *=
   band_mid / measured` (clamped). **Exposure is a post-tonemap multiplier, so this needs NO rebake**
   — build once, probe once, set the exposure value. The dungeon stays in its dark band, the market
   in its bright band; only the *overshoot* is removed. (Light-energy hotspot fixes + contrast/
   warmth correctors are later refinements; brightness is the first and biggest win.)

**The general enforcer pattern** (reused per measurable axis): `(metric, band-from-spec, corrector)`.
Plan-data metrics (slope angle, density) correct **pre-render for free**; render-dependent metrics
(luminance, contrast) use the one cheap probe.

## The VLM — subjective residual only

The existing `visual/batch.py` loop (capture → `vlm.check_image` structured judgment + aesthetic
score → worklist → reroll) stays as the **subjective backstop**: it judges what metrics can't ("does
this read as a coherent dusk keep?") and flags for regeneration. It is *not* the primary critic —
GPU-swap + capture-dependent — so it runs sparingly on the final render, not in a tuning loop.

## Why this beats the alternatives

- vs **per-scene value database**: you author ~a dozen mood bands, not values per situation; the
  Brief's mood generalizes them to infinite scenes.
- vs **VLM-tunes-everything**: the measurable majority (bright/dark/steep/contrast) is fixed cheaply
  and deterministically; the VLM handles only the small subjective residual.
- vs **one mechanism monolith**: the contract centralizes *policy*; enforcers stay stage-local, so
  we don't rebuild a god-module.

## Architecture / units

```
foundry/cohesion.py        # build_cohesion_spec(brief, seed) -> CohesionSpec; MOOD_BANDS table
foundry/palette.py         # refactored to BE the palette facet (build_palette → spec["palette"])
foundry/quality/           # the enforcer framework: metric + band + corrector registry
  metrics.py               #   luminance(image), contrast(image), slope_angle(plan), ...
  correctors.py            #   exposure_for_luminance(measured, band) -> exposure, ...
  autocorrect.py           #   driver: probe → measure → correct → apply (no rebake for exposure)
scene_compiler / lighting_planner  # read spec facets (enforcers)
visual/batch.py            # existing VLM subjective gate (residual)
```

## Determinism & testing (for when built)

- `build_cohesion_spec` deterministic (Brief + seed). The probe→measure→correct is deterministic
  (software render, fixed scene, pure corrector).
- Tests: corrector math (luminance ratio → exposure, clamped, lands mid-band); mood→band selection
  (dark intent → dark band, not normalized up); a too-bright scene → corrected *into its intent
  band*; a dark-intent scene **stays dark**; spec facets consumed by enforcers.

## Scope / sequencing

- **Build facet-by-facet.** Color facet = CP-1/CP-2 (done). **Atmosphere/lighting facet = first new
  build** (intent-bands + brightness auto-exposure). Geometry (CP-3) and style (CP-4) are later
  facets that plug into the same spec.
- **Deferred:** all implementation, parked in the futurelog until M1 is complete. Richer LLM intent,
  contrast/warmth/fog correctors, geometry/style facets are post-first-facet.

## Out of scope

- The mechanisms staying distributed is deliberate — do NOT consolidate enforcers into one module.
- Per-scene human tweaking (the thing this replaces).
