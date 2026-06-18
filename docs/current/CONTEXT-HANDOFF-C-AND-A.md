# Context Handoff — Resume C (schema/scale) then A (asset kit)

**Date:** 2026-06-18. **Purpose:** this long session is at risk of context loss.
This doc is the durable, self-contained resume point for the next two efforts:
**C** (schema/scale probe — do now) and **A** (asset-kit placement — brainstorm in
a fresh session). Read this + the linked docs and you have full fidelity.

## Where we are (all LIVE on `main`)
- **Testbench migration** complete; legacy runners deleted (ADR-005).
- **Reliability loop, slices A+B, merged + live:**
  - **A — system-owned conditioning** (`engine/devforge/reasoning/prompts/conditioning.py`,
    injected once in `run_pipeline`): a plain user prompt gets the rich framing; no
    "magic words". Toggle `DEVFORGE_PLANNER_CONDITIONING=0`.
  - **B — deterministic quality/collapse gate** (`engine/devforge/governance/quality_gate.py`):
    advisory scene-graph signals (variety collapse, monoculture, thin, missing
    systems) on `PipelineResult.quality_warnings` + the apply_spec artifact.
- **Screenshot capture works** (`hub/mcp_client.py:capture_screenshot()`,
  `/api/screenshot`): frames the editor camera on the scene root
  (`editor_screenshot` natively supports `view_target`/`coverage`/`elevation`/
  `azimuth`/`fov`). **The system finally has eyes.**
- **Executor chunking fix** live (large `apply_spec` no longer silently times out).

**Stack:** hub (FastAPI :8003) ⇄ engine/devforge (MCP :8001) ⇄ godot-ai (:8000) +
llama (:8002), all systemd user services. Config: `~/.config/forge-stack/stack.env`.
Model currently 27B (`qwen3-6-27b`); also `qwen3-5-4b`. Swap via
`hub/forge_ops.py:swap_model`.

## THE PIVOTAL INSIGHT (why C and A exist)
The screenshot revealed the truth: a prompt for *"a cozy room — table, four chairs,
rug, bookshelf, hanging lamp"* renders as **a flat red rug, a light, and a few
default-sized boxes.** Cause, confirmed in code
(`engine/devforge/compilation/pipeline/architecture_planner.py:311-318`): the prop
vocabulary is only

```
mesh:  box | sphere | capsule | plane | cylinder   (5 primitives)
shape: box | sphere | capsule | cylinder           (colliders)
color: [r,g,b]
position: [x,y,z]
text: "string"
```

**There is no `scale`, no `rotation`, no size, no material beyond color, no asset
loading.** So "a wooden table" can only be a *1-metre brown box*; "a chair" a box;
"a lamp" a bare light node. **This is the expressiveness ceiling — and it explains
why 4B ≈ 27B: both models place the same boxes.** No conditioning, gating, or model
size turns a box into furniture; the *vocabulary* is boxes. The lever is the schema
(C) and ultimately real assets (A).

## C — Schema/scale probe (DO NOW)
**Question:** does a wider prop schema make scenes visibly better AND make 4B vs 27B
**diverge** (proving the schema, not the model, was the ceiling)?

**Concrete moves (cheap, high-impact, in order):**
1. **Add `scale: [x,y,z]` and `rotation: [x,y,z]` (degrees)** to the prop schema —
   this alone lets a table be a wide flat box and a bookshelf a tall box, which
   transforms how scenes read. Optionally add `size`/material props later.
2. Three places to change together:
   - the **schema prompt** (`architecture_planner.py:311-318` props block + the `(5)`
     verify-line at :366 + add a worked example using scale).
   - the **GBNF grammar** the arch planner is constrained by (find it — the planner
     passes a grammar like the world planner did; it must *permit* the new keys or
     the model can't emit them).
   - the **compiler** that turns props into ops
     (`engine/devforge/compilation/pipeline/architecture_compiler.py`) — it must read
     `scale`/`rotation` and emit the transform set-property op.
3. **Re-run the A/B with eyes:** pick ONE fixed rich prompt (e.g. the cozy room),
   run on **4B and 27B**, `capture_screenshot()` each (framing now works), and judge
   by eye + structural metrics. Verdict: did richer vocabulary (a) make the scene
   look better, and (b) make the 27B visibly out-do the 4B? If yes → the schema was
   the ceiling, greenlight A. If still boxes-look-the-same → the ceiling is *assets*,
   go straight to A.

**Enablers already in place:** framed screenshots, system conditioning (rich
prompts), the quality gate (flags thin output), the model swap, the testbench.

## A — Asset-kit placement (BRAINSTORM in a fresh session, then plan)
**Direction:** give the planner **real meshes** (chair, table, shelf, lamp, …) to
*select and place*, instead of inventing geometry from 5 primitives. This is the
survey's "modular kit assembly" and the **asset pipeline** the owner flagged early.
**Decisions to brainstorm (don't pre-bake):**
- Asset source: a free CC0 kit (e.g. Kenney) vs. later generative assets.
- Schema: an `asset: "chair_01"` prop / a new asset-placement planner+engine vs.
  extending arch. (Engines today place primitives — `engine/devforge/spatial/*`.)
- How the planner knows the catalog (a manifest the prompt/grammar references).
- How it composes with the existing deterministic engines + world-state.
This is a genuine design effort → **brainstorming skill → spec → plan**, ideally a
new session with this doc loaded.

## Key codebase anchors
- Schema/prompt: `engine/devforge/compilation/pipeline/architecture_planner.py:280-367`.
- Compiler (props→ops): `engine/devforge/compilation/pipeline/architecture_compiler.py`.
- Pipeline + `PipelineResult`: `.../pipeline/engine.py` (`run_pipeline`; `PipelineResult` @128; conditioning injected ~348; gate ~543).
- Conditioning: `engine/devforge/reasoning/prompts/conditioning.py`.
- Quality gate: `engine/devforge/governance/quality_gate.py`.
- Screenshot: `hub/mcp_client.py:capture_screenshot` / `_extract_image_b64`.
- Spatial engines (place primitives): `engine/devforge/spatial/*`.

## Workflow & conventions (unchanged)
- **Branch → CLI-AI plan (TDD, `docs/superpowers/plans/`) → Claude reviews the
  branch → merge.** Never let a CLI AI merge; Claude is the gate.
- **Survey method** for direction calls: chat AIs (concept) + CLI AIs (codebase,
  read-only, one report file each in `docs/reviews/`).
- `scripts/check.sh` must stay green; files ≤500 lines; hub imports bare, engine
  imports `devforge.`-absolute. See `docs/current/CONVENTIONS.md`.

## Open backlog (separate track — NOT C/A)
- **`exp/richness-verdict` branch** — world-state machinery (`world_planner`,
  `_run_world_path`, scatter/voronoi occupancy), isolated/unmerged; decide its fate.
- **God-file splits** (`engine.py`, `mcp_server.py`) and **`hub.py` split** (now
  unblocked) — `docs/current/GOD-FILE-SPLIT-PLAN.md`.
- **Geometric gate v2** (overlap/clipping/floating) — follow-on to B.
- **VLM** — deferred, optional, non-gating, calibration-first (per
  `NEXT-PHASE-RECONCILED-DIRECTION.md`).

## The trail (read these to go deeper)
`docs/INDEX.md` → `docs/current/NEXT-PHASE-RECONCILED-DIRECTION.md` (the pivot),
`docs/decisions/003`–`005`, `docs/reviews/world-state-richness/RESULT.md` (the
richness experiment), `docs/reviews/visual-eval/` (the survey that chose
deterministic over VLM), `docs/superpowers/plans/2026-06-17-*` (the executed plans).
