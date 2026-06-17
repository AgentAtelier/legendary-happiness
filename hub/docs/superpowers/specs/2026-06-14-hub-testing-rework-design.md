# Forge Hub — Testing & Look Rework (Design Spec)

**Date:** 2026-06-14
**Status:** Approved design, pending implementation plan
**Scope:** `hub/static/index.html` (frontend) + light `hub/hub.py` glue. No Odysseus / godot-ai / DevForge source changes.

## Problem

The hub's testing capability is scattered across four tabs — **Test Bench**, **Score**,
**Shootout**, **Gauntlet** — each with its own buttons, its own result rendering, and its
own scoring vocabulary (pass/fail vs coverage% vs scorecards). There is no honest progress
feedback (no time-left, weak live status), button presses give little confirmation, and the
look is inconsistent. The hub feels "all over the place."

## Goals

1. Unify the four testing surfaces into **one Testing tab** driven by a single faceted runner.
2. Unify scoring into **one model**: a 0–100 score + Pass/Partial/Fail verdict band.
3. Add honest **live feedback**: live phase, elapsed, determinate progress where countable,
   and a history-based soft ETA.
4. Add real **press confirmation** on every actionable button.
5. **Unify the look** across the whole hub.
6. **Audit** that every surface actually displays and works.

## Non-goals (YAGNI)

- No build pipeline, no framework, no npm. Stay zero-build vanilla JS + hand CSS.
- No Tailwind / HTMX migration (existing SSE already covers live updates).
- No backend pipeline rewrite. Existing endpoints stay; the frontend routes facet combos
  to the right endpoint. Backend changes limited to: a unified score/verdict helper, phase
  events on the SSE stream, and an ETA-from-history read.
- No restructuring of Overview / Models / Config / Activity / Doc tabs — they are **re-skinned
  only** by the new theme.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Tech foundation | Enhance in place — zero-build vanilla |
| Merge depth | One faceted runner (Target × Suite × Depth → one scorecard) |
| Scoring model | One 0–100 score + Pass/Partial/Fail verdict band; sub-metrics as detail |
| Progress / ETA | History-based soft ETA + live phase + determinate bar where countable |
| Testing tab layout | B — config rail left, results right |
| Visual style | "Middle ground": neon green brand accent + headline numbers, gray-green body, amber/red verdicts |
| Border color | Bright `#3f9657` |
| Nav | 9 tabs → 6: Overview · Testing · Models · Config · Activity · Doc |

## Architecture

### Component 1 — The faceted runner (Testing tab)

A single control surface replacing the four old tabs. Layout B:

- **Left config rail** (fixed): three facet selectors + Run/Stop.
  - **Target:** `Current model` · `Compare models` (multi-select picker)
  - **Suite:** `Health` · `Scenarios` · `Gauntlet`
  - **Depth:** `Fast` · `Full`
  - Run button shows the resolved plan beneath it (e.g. "G7 set · ~3m est.").
- **Right results column:**
  - Live-status strip (Component 3)
  - Scorecard (Component 2)
  - History (Component 2)

**Facet → endpoint routing** (frontend only, no new endpoints for v1):

| Target | Suite | Calls |
|---|---|---|
| Current | Health | `/api/bench/run` (+ `/api/bench/probe` for full) |
| Current | Scenarios | `/api/scenarios/run` |
| Current | Gauntlet | `/api/gauntlet/run` |
| Compare | Scenarios/Gauntlet | `/api/shootout` (existing multi-model path) |

Depth maps to each endpoint's existing fast/full flag (Health fast = quick-health no-LLM;
Scenarios fast = geometry-only; Gauntlet fast = subset of phases).

### Component 2 — Unified scorecard + history

A single render function `renderScorecard(result)` used by **all** suites and compare mode.

- **Headline:** big 0–100 number + verdict chip (Pass ≥ pass-threshold / Partial / Fail).
  - Verdict bands are a shared helper `scoreToVerdict(score)` (defaults: ≥90 Pass, ≥60 Partial, else Fail; suite may override threshold).
  - Health: `% checks passing` → score; pass/fail per check maps 100/0.
  - Scenarios / Gauntlet: coverage % is the score directly.
- **Sub-metrics row:** suite-specific named metrics rendered identically (depth, scripts,
  nodes, attached, overlap, err…). Good values green, shortfalls amber.
- **Compare mode:** N scorecards side-by-side, identical shape, sorted by score.
- **History:** one unified store keyed by suite+target; each entry a compact chip
  (label + score + verdict color). Filterable by suite/target. Backed by the existing
  per-tool history endpoints, normalized client-side into the common shape.

### Component 3 — Live status strip

Driven by the existing SSE stream (`/api/stream/{job_id}`).

- **Phase label:** backend emits coarse phases (e.g. `planning → compiling → executing ops → measuring`). Frontend shows the current phase verbatim.
- **Elapsed:** client-side ticking timer from job start.
- **Determinate bar where countable:** when the stream reports `n/total` (ops, scenarios,
  models, gauntlet phases) show a real fill; otherwise an indeterminate shimmer.
- **Soft ETA:** on Run, frontend reads median duration of the last ~5 runs of the same
  suite/target from history and shows `~Xm left · based on last N runs`, clearly an estimate.
  Suppressed when fewer than 2 prior runs exist.

### Component 4b — Logo (header)

A hand-authored inline **SVG** logo placed in the header beside the title (no external asset
file; fits zero-build). Visual language fuses the four cues:

- **DevForge** — a forge anvil / hammer silhouette as the core mark.
- **Terraform** — topographic contour lines forming the ground/terrain under the anvil.
- **Climate disaster** — a heat/storm streak (lightning or ember arc) cutting across.
- **RPG** — an angular hexagonal/shield emblem frame around the mark.

Themed to the new palette (neon-green mark, amber accent streak, on the dark pane). Sized to
sit inline at header height; scales crisply. Lives in the markup so it inherits the theme
variables and needs no build step.

### Component 4 — Press feedback + theme (global)

- **Press feedback** on every actionable button: immediate depress transition → label swaps
  to spinner/"…" → `disabled` while in-flight → green success flash or red error flash + a
  transient toast. Long-running Run becomes "Running… ▣ Stop". Destructive actions keep their
  existing confirm gate.
- **Theme:** remap the existing CSS variables to the "middle ground" palette, applied globally:
  - bg `#0a0e0a`, pane `#0e160e`, border `#3f9657`
  - brand/accent/headline `#00ff41`, body text `#b8e6c4`, dim `#6f8a76`
  - verdicts: pass `#00ff41`, partial `#e0b341`, fail `#ff5b5b`
  - monospace for data; existing structure/markup of other tabs unchanged.

## Data flow

```
User sets facets → Run
  → frontend resolves (target,suite,depth) to endpoint + flags
  → POST returns job_id
  → open SSE /api/stream/{job_id}
       ├─ phase events  → status strip phase label
       ├─ n/total events → determinate bar
       └─ (frontend) elapsed timer + ETA from history
  → completion event carries result
  → normalize → renderScorecard() → append to unified history
```

## Error handling

- Run failure (non-2xx / stream error): button error-flash + toast with the message; status
  strip shows `● failed`; no scorecard appended (or a Fail card if the run produced a partial
  result). Existing per-tool error payloads are surfaced verbatim.
- Stop: sends the existing stop/abort path; status returns to idle.
- Missing history for ETA: ETA hidden, not faked.

## Testing / acceptance

- Each suite runnable from the one tab and produces a unified scorecard.
- Compare mode renders side-by-side scorecards.
- Live strip shows phase + elapsed + determinate bar (Gauntlet phases / shootout models) +
  ETA when history exists.
- Every button shows press → in-flight → result feedback.
- All six tabs share the new theme; Overview/Models/Config/Activity/Doc still function.
- Audit note produced listing anything found broken/disconnected.
- Existing hub tests still pass (`hub/tests`).

## Audit checklist (Goal 6)

Walk each of the 6 tabs and each runner facet combo; confirm the endpoint responds, the result
renders, and controls are wired. Record findings inline and fix wiring gaps encountered.

## Open implementation notes

- Backend additions are small and additive: `scoreToVerdict`/normalize helper (can live
  frontend-side initially), phase emission on the SSE stream, ETA-from-history read.
- Keep `index.html` from growing unwieldy: factor shared pieces (scorecard render, button
  feedback, status strip) into small reusable JS helpers and a tokens-based stylesheet rather
  than per-tab duplicated markup.
