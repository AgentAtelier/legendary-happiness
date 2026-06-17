# Multi-Model Testing Harness + Suite Streamline — Work-Division Plan

**Date:** 2026-06-16
**Status:** Planned (by Claude). Implementation handed to the other AI.
**Why this doc:** all 6 spatial engines are built; per `SPATIAL-GENERATION-ARCHITECTURE.md`
§5 the testing harness is the capstone. This plan streamlines the suite, builds a
multi-model harness, and adds a result-analysis phase.

---

## 0. Division of labor (firm)
To save tokens on Claude's side and time on the other AI's:

| Workstream | PLAN (Claude — done in this doc) | IMPLEMENT (other AI) | TEST/ANALYZE (Claude) |
|---|---|---|---|
| WS1 Streamline suite | which tests to add/fix/cut + criteria | write the code | confirm signal post-sweep |
| WS2 Harness + hub view | the 5 tests, 4 models, ×10, the readable view spec | write the code | — |
| WS2.5 Analysis | define the questions + format | (Claude does it) | **Phase 2.5 — Claude** |

**Rules carried forward:** DevForge-only for engine code; Odysseus + godot-ai vanilla.
The **human kicks off the long unattended sweep** (it's hours); Claude analyzes the
output. The other AI must keep the **full** DevForge suite green (currently 569
tests; a 151-subset run hid a real failure — see WS1).

**Model lineup (qwen only — ignore gemma/cydonia):**
`qwen3-5-4b` (4B, fits 9.8G) · `qwen3-5-9b-q8-0` (9B, 10.8G) ·
`qwen3-14b-q6-k` (14B, 13.5G) · `qwen3-6-27b` (27B, tight 14.5G). All fit; the 27B
needs the transactional swap (pre-flight). Swap order small→big is cheapest.

---

## WS1 — Streamline the test suite  (other AI implements)

**Goal:** every engine has parity unit coverage; the full suite is green; low-signal
tests that add noise are cut. *Add what's missing, fix what's broken, cut what's noise.*

### 1a. ADD — Voronoi unit tests (the only engine with none)
Create `test_voronoi.py` + `test_voronoi_planner.py`, **mirroring `test_wfc.py` /
`test_wfc_planner.py`** (which are the reference pattern). Cover, at minimum:
- engine: seed determinism (same seed → identical plan), district tessellation
  (every cell assigned to nearest seed), road detection on boundaries, building
  placement per district, the 7 district types, **no district-plane overlap**
  (the bug just fixed — lock it with a regression test), in-bounds positions.
- planner: grammar loads, prompt contains schema + region/districts, response
  parsing (think-tags/fences/prose/defaults), `plan()` error wrapping.
- **Acceptance:** ≥30 tests, all green; parity with WFC's coverage shape.

### 1b. FIX — the stale test the WFC skip-heuristic broke
`test_wfc_planner.py::TestPlanMethod::test_plan_returns_parsed` now FAILS: it uses
`prompt="dungeon"`, which the new skip-heuristic intercepts (returns a default,
never calls `llm_fn`). Fix: change that test to a **non-keyword** prompt (e.g.
`"a winding underground complex"`) so it exercises the LLM path, AND add explicit
skip-heuristic tests (keyword → default, no `llm_fn` call; non-keyword → `llm_fn`
called). **Acceptance:** full `pytest devforge/tests/ -q` green (no subset).

### 1c. CUT/MERGE — the obvious noise (do only these now; deeper pruning is Phase 2.5)
Cut only what is *demonstrably* low-signal today; the data-driven pruning happens
after the sweep (Claude, Phase 2.5). Do now:
- **`capability-v1 / G2_breadth`** — flagged repeatedly: the binary coverage model
  flips it full↔partial with identical 24 nodes. It measures the coverage model's
  noise, not capability. **Remove from `capability-v1`** (or convert to a
  count-only assertion that can't flip on non-determinism).
- **Scenario editing duplicates** — `node_delete`/`node_rename` vs
  `delete_existing`/`delete_existing_bare`/`rename_existing` overlap heavily. Keep
  the `*_existing` trio (realistic: edit pre-existing nodes); **drop the bare
  same-batch `node_delete`/`node_rename`** (B2 same-batch is the degenerate case).
- **Geometry scenarios** (`cube_create`/`sphere_create`/`light_create`/`camera_create`)
  — keep **one** (`cube_create`) as a smoke check; the pipeline is mature, the other
  three are redundant low-signal. (Confirm with the user before deleting if unsure —
  Claude's lean: keep cube + camera, drop sphere + light.)
- **Do NOT cut** spatial/ssp kitchen overlap yet — they test different layers
  (raw pattern engine vs archetype). Claude will decide post-sweep if one is noise.
- **Acceptance:** full suite green; a one-line note in the PR of what was cut + why.

---

## WS2 — The multi-model harness  (other AI implements)

**Goal:** sweep the **5 discriminating tests** across the **4 qwen models**, **×10
runs each**, and render the result so the user can read it at a glance.

### 2a. The 5 tests (Claude's pick — lean on model-discriminating, LLM-heavy work)
Deterministic engines (WFC, Voronoi) barely vary by model — the LLM only picks a
couple of numbers — so they waste sweep budget. The 5 are chosen to *separate
models*:
1. `capability-v1 / G7_integration` — the richest single LLM scene build (nesting +
   props + scripts + signals at once). The top discriminator.
2. `capability-v1 / G5_scripts_signals` — signal wiring; historically the most
   model-sensitive (non-determinism lives here).
3. `capability-v1 / G8_adversarial` — graceful partial-build + reject; tests robustness.
4. `building-v1 / B1_small_house` — BSP split-tree; the most LLM-involved *spatial*
   engine (and the user's house goal).
5. `spatial-v1 / S4_adjacency` — ARCS slot-fill; LLM maps assets to anchors/slots.
*(WFC + Voronoi get ONE correctness run per model in WS1's suite, not the ×10 sweep.)*

> **LOCKED (user, 2026-06-16):** the 5 above stand as-is — keep `G8_adversarial`
> for maximum model-discrimination. **A spatial-breadth sweep is deferred to item
> (3) (the compound building+scatter planner)**, where there's a real spatial flow
> worth sweeping. Do NOT add WFC/Voronoi/garden to this harness's 5.

### 2b. The sweep mechanism
- Extend the gauntlet with a **`--runs N`** mode (run a prompt/set N times, collect
  per-run coverage + latency + truncation). A `mean ± stddev` already has a home in
  `/api/runs/stability` — route through it.
- A **multi-model driver**: for each of the 4 aliases → transactional swap (reuse
  `forge_ops.swap_model` + pre-flight) → run the 5 tests ×10 → record → next model.
  Small→big swap order. One hub endpoint `POST /api/harness/run` that streams
  progress (reuse the SSE job pattern + `_job_lock`).
- **Persist** one harness artifact: `{model, test_id, runs:[{coverage, latency_ms,
  truncated}], mean, stddev}` per (model, test). 5×4 = 20 cells × 10 runs = 200 runs.
- **Acceptance:** one click → unattended sweep → a single JSON artifact + the view below.

### 2c. Hub readability (the "make results readable for me" piece)
A **model × test matrix** as the headline (this is what the user reads):
```
                  qwen3-5-4b   qwen3-5-9b   qwen3-14b   qwen3-6-27b
G7_integration      62 ±8        78 ±5       91 ±3        100 ±0   ★
G5_scripts          40 ±15       55 ±12      75 ±8        100 ±0   ★
G8_adversarial      ...
B1_small_house      ...
S4_adjacency        ...
  ─────────────────────────────────────────────────────────────
  avg / best        ...          ...         ...          ★ best
```
- Each cell: **mean coverage ± σ**, color-banded (green ≥90 / amber 60–89 / red <60),
  σ shown (high σ = unreliable, the key signal the user wants).
- **★** the best model per row + the best overall.
- A second row strip: **median latency** per model (speed/cost tradeoff).
- Keep it ONE screen, no scrolling, monospace numbers aligned. This replaces reading
  raw JSON. **Acceptance:** the user can name the best + most-reliable model in 5s.

---

## Phase 2.5 — Analysis & interpretation  (Claude does this, after the sweep)

Once the human runs the sweep and pastes the artifact, **Claude** produces a written
analysis answering:
1. **Best model per capability** — and the overall recommendation for "build mode".
2. **Reliability** — which models have low σ (trustworthy) vs high σ (flaky); does
   the 27B's reliability justify its tight VRAM + slower speed vs the 14B?
3. **The cost/quality knee** — is the 9B "good enough" for iteration, reserving the
   27B for final builds? Where's the diminishing return (4B→9B→14B→27B)?
4. **Noise verdict (feeds WS1)** — which of the 5 tests actually *discriminated*
   models (high between-model variance) vs which were flat (low signal → candidates
   to cut from the routine suite). This is the data-driven noise pruning deferred
   from WS1c.
5. **Truncation/thinking** — does the thinking-config hurt the smaller models more?
**Deliverable:** a `HARNESS-ANALYSIS-<date>.md` + concrete config recommendations.

---

## Sequence & handoffs
1. Other AI: **WS1** (add Voronoi tests, fix the stale test, do the safe cuts) →
   full suite green. Hand the human nothing (offline).
2. Other AI: **WS2** (harness + hub view). Hand the human: run the sweep.
3. Human: kick off the unattended sweep (hours), paste the artifact.
4. Claude: **Phase 2.5** analysis.

Deferred (acknowledged, not now): the compound `building+scatter` planner (#3),
bsp planner-test gap + engine enhancements (#4).
