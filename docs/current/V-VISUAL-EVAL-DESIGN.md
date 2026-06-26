# V — VLM Visual-Eval Loop (Design)

**Date:** 2026-06-21. **Status:** approved (brainstormed). Standalone sub-project (an *offramp* — a
procedural-asset visual-QA tool has value on its own). **Informed by** the 2025 VLM-QA research +
local-model feasibility checks (below).

---

## 1. Goal & governing principle

V is the **instrument that lets us judge whether generated visuals escape the AI-slop wall** — the
existential bar from the E brainstorm. It moves visual QA off the user (and off Claude, who must NOT be
the visual judge) onto **dedicated vision models**, run as a **walk-away batch** so the user can leave
and return to a report. It also feeds the orchestrator (Claude) **structured visual data** it can reason
about without looking at images.

**Design to the models' proven strengths (research-backed):**
- VLM judges **rank/compare reliably but score absolutely poorly** → use thresholds, ranking, and
  **regression-vs-baseline**, never a raw absolute verdict as a hard gate.
- Off-the-shelf VLMs catch **~50% of hard visual glitches** → V is a strong *net + worklist*, not an
  oracle; **the user stays the final arbiter** of the slop wall.
- **One strong judge beats many weak ones** → a small *specialist* set (each model on the job it's best
  at), not an ensemble voting on the same question.

## 2. Model roster (feasibility-locked)

| Model | Job | Runtime | Status |
|-------|-----|---------|--------|
| **Qwen3-VL-8B** | structured glitch checks + composition/theme coherence | **our llama.cpp + hub swap** (mtmd/mmproj); json_schema-constrained | ✅ primary |
| **CLIP aesthetic predictor** | raw "looks good?" score for ranking/regression | tiny standalone PyTorch | ✅ secondary |
| **MolmoPoint-8B** | precise pointing/counting (collision/clutter localization) | **separate runtime** (transformers/vLLM) | ⏸ deferred — add only if Qwen3-VL's spatial precision is insufficient |

Qwen3-VL runs on the exact stack we already have ([llama.cpp Qwen3-VL support since Oct 2025]) and does
point/box grounding itself, so it covers most of Molmo's intended job. CLIP aesthetic is deterministic
and cheap. Molmo is a known upgrade path, not a day-1 dependency.

## 3. Scope

**In (V, full loop):** screenshot harness + Qwen3-VL structured checks + CLIP aesthetic + **two batch
jobs** (prop-catalog QA, scene regression) + visual signals + `visual_report` + a **regen worklist**.
**Closed auto-reroll** is the *last* increment (after the checks prove trustworthy).
**Out:** MolmoPoint (deferred), per-build automatic eval (batch only — see §5), Claude judging images.

## 4. Architecture

```
[Screenshot harness] render props + scenes → PNGs (real GPU context, not --headless)
        │
        ├─► [Qwen3-VL-8B] (hub-swapped, json_schema)  → structured checks (per asset / per scene)
        │        prop: textured? reads-as-material? holes/deformity? floating bits?
        │        scene: floater? clipping? ceiling visible? NPCs on floor? composition/theme coherence?
        ├─► [CLIP aesthetic]  → aesthetic score (per asset / per scene)  [ranking, not gate]
        │
        └─► foundry/eval/visual.py  → visual signals + regression deltas vs baseline
                 └─► visual_report.{md,json}  (worst-first ranking, flagged items, regressions)
                        └─► regen worklist  → (later) closed auto-reroll
```

- **Screenshot harness** (`foundry/visual/screenshot.py` + a Godot capture scene/script): renders a prop
  GLB (turntable, 2–3 angles) or a scene (fixed camera angles) to PNG. Needs a real render context — run
  Godot non-`--headless` with an offscreen viewport capture, or via a virtual display (xvfb). This is the
  one genuinely new infra piece.
- **VLM runner** (`foundry/visual/vlm.py`): swap Qwen3-VL via the hub (mmproj/mtmd), send PNG + a
  json_schema-constrained prompt, parse structured results. Reuses the model-swap + json_schema machinery.
- **Aesthetic scorer** (`foundry/visual/aesthetic.py`): CLIP + the small aesthetic head → a float per image.
- **Eval + report** (`foundry/eval/visual.py`, `foundry/visual/report.py`): visual signals parallel to
  `eval/signals.py`; a `visual_report` mirroring the build report; a stored **baseline** for regression.

## 5. Batch flow (walk-away)

Triggered by the orchestrator/user on cadence (e.g. every Nth scene-creation, or "I'm stepping away").
One VLM-loaded session does both jobs back-to-back:
- **(A) Prop-catalog QA** — iterate the generated prop library (esp. new props): render → Qwen3-VL checks
  + CLIP score → per-asset pass/fail + score. Output ranked **worst-first** so the ugliest get fixed first.
- **(B) Scene regression** — render a golden scene set (+ sampled new scenes) → checks + score → diff
  against the stored baseline → **better/worse/regressed** flags. Update baseline on demand.

Cost is amortized (one swap, whole catalog). The deterministic per-build gates (headless load + structural
geometry/material tests) remain the fast first line; V is the periodic visual-quality + regression layer.

## 6. Determinism & testing

- **Determinism:** never gate on a raw VLM verdict (fuzzy). Structured checks use **json_schema + low
  temperature**; decisions come from **thresholds + ranking + regression deltas**. CLIP scoring is
  deterministic (fixed model, fixed image). Golden baselines + fixed camera angles make regression
  reproducible. Screenshots are deterministic given a fixed scene + seed.
- **Testing (V's own code, [CLI], deterministic — VLM mocked):** screenshot harness produces a PNG;
  `vlm.py` parses a mocked json_schema response into signals; `eval/visual.py` computes signals +
  regression deltas from canned inputs; report renders all sections; worklist derives from flagged items.
  The **VLM itself is not unit-tested** (it's the judge) — its reliability is governed by thresholds and
  the human-in-the-loop. **[ORCH]** runs the real VLM batches (time-intensive, orchestrator's job).

## 7. Connection to the wider plan

V is the measurement instrument the consolidation phase needs: it judges **E1** material output (catalog
QA) and guards **E2** + every future scene against visual regression. It is the visual half of "the
orchestrator owns time-intensive verification." Built to extend: add MolmoPoint (separate runtime) for
spatial precision, and the closed auto-reroll, once the structured checks earn trust.
