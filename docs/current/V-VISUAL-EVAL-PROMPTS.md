# V — VLM Visual-Eval Loop — Delegation Prompts

> **For the CLI AI:** implement task-by-task, TDD red→green, one commit per task. Spec:
> `V-VISUAL-EVAL-DESIGN.md`. Two genuinely-new infra pieces (screenshot capture, VLM serving) carry
> risk — **spike them first within their task** and confirm the mechanism before building on it.

**Goal:** a walk-away batch that renders props + scenes to images, runs a local VLM (Qwen3-VL-8B) +
a CLIP aesthetic scorer over them, and emits visual signals + a report + a regen worklist — so visual
QA leaves the human's hands. Designed to VLM strengths: structured checks + ranking/regression, never
raw absolute verdicts.

## Global Constraints (verbatim)

- **Testing split:** **[CLI]** runs the fast gates (`pytest tests/ -q` + `pytest
  tests/test_godot_smoke.py -q`, green) per task with the **VLM/CLIP mocked**, then hands off.
  **[ORCH]** runs the *real* VLM/CLIP batches (time-intensive) and calibrates thresholds — do NOT run it.
- The **VLM is never unit-tested** (it's the judge). V's own code is tested with mocked model output.
- Reuse the existing **hub model-swap** + **json_schema** machinery for Qwen3-VL. Claude never judges
  images. Never touch `addons/godot_ai`.

## Model roster (from the spec)

- **Qwen3-VL-8B** — primary, on our llama.cpp+hub stack (needs the model GGUF + an `mmproj`/mtmd vision
  projector); json_schema-constrained structured checks. [llama.cpp Qwen3-VL support since Oct 2025.]
- **CLIP aesthetic predictor** — standalone PyTorch, the "looks good?" score (ranking only).
- **MolmoPoint-8B** — DEFERRED (no GGUF; separate runtime). Do not build against it now.

---

## Task 1 [CLI] — Screenshot harness (the new render infra)

**Files:** `foundry/visual/screenshot.py` + a Godot capture script/scene under `godot_template/`;
`foundry/tests/`.

**Spike first:** Godot `--headless` does NOT render. Get a real context — run Godot non-headless with an
offscreen `SubViewport` capture to PNG, or via a virtual display (xvfb). Confirm a PNG is produced before
building further.

**Build:** `capture_scene(build_dir, out_dir, angles) -> list[png_path]` (fixed camera angles for a scene)
and `capture_prop(glb_path, out_dir) -> list[png_path]` (turntable, 2–3 angles for a single prop GLB).
Deterministic given a fixed scene+seed.

**Tests:**
- [ ] `capture_scene` / `capture_prop` on a fixture build produce non-empty PNG file(s).
- [ ] Commit: `feat(foundry): visual screenshot harness (V task 1)`.

## Task 2 [CLI] — Qwen3-VL runner (VLM serving + structured checks)

**Files:** `foundry/visual/vlm.py`; `foundry/tests/`.

**Spike first:** confirm the hub/llama server can serve Qwen3-VL with an `mmproj` and accept an image +
prompt, returning json_schema-constrained output. (Mirror the existing FoundryLLM swap + json_schema path.)

**Build:** `check_image(png_path, schema, prompt) -> dict` → swaps/uses Qwen3-VL, sends image + prompt,
parses the json_schema result. Two schemas:
- **prop schema:** `{textured: bool, material_reads_right: bool, has_holes_or_deformity: bool,
  floating_bits: bool, notes: str}`.
- **scene schema:** `{floater: bool, clipping: bool, ceiling_visible: bool, npcs_on_floor: bool,
  composition_ok: bool, theme_coherent: bool, notes: str}`.

**Tests (VLM mocked):**
- [ ] `check_image` parses a mocked json_schema response into the typed dict; malformed → safe default + a flag.
- [ ] Commit: `feat(foundry): Qwen3-VL structured visual checks (V task 2)`.

## Task 3 [CLI] — CLIP aesthetic scorer

**Files:** `foundry/visual/aesthetic.py`; `foundry/tests/`.

**Build:** `aesthetic_score(png_path) -> float` using a CLIP backbone + the small LAION aesthetic head.
Deterministic. Lazy-load the model; degrade gracefully (return None + flag) if the model isn't present.

**Tests:**
- [ ] On a fixture image returns a float in range (or None-with-flag if model absent); deterministic for a
  fixed image (mock the model in CI).
- [ ] Commit: `feat(foundry): CLIP aesthetic scorer (V task 3)`.

## Task 4 [CLI] — Visual signals + report + baseline/regression

**Files:** `foundry/eval/visual.py`, `foundry/visual/report.py`; `foundry/tests/`.

**Build:** `compute_visual_signals(checks, aesthetic) -> dict` (e.g. `no_floaters`, `material_reads`,
`composition_ok`, `aesthetic_score`); `render_visual_report(items) -> {md,json}` ranked **worst-first**
with flagged items; baseline storage (`visual_baseline.json`) + `regression_delta(current, baseline)` →
better/worse/regressed per item. Mirror `eval/signals.py` + the build-report pattern.

**Tests (canned inputs):**
- [ ] signals computed correctly from canned checks; a regressed aesthetic vs baseline flags "regressed";
  report has all sections + worst-first order.
- [ ] Commit: `feat(foundry): visual signals + report + regression (V task 4)`.

## Task 5 [CLI] — Batch driver (prop catalog + scene regression)

**Files:** `foundry/visual/batch.py` (CLI entry, e.g. `python -m foundry visual-eval`); `foundry/tests/`.

**Build:** one session that: (A) iterates the prop library → capture → check + score → catalog report
(worst-first); (B) renders a golden scene set (+ sampled new) → check + score → regression diff vs
baseline. Loads Qwen3-VL once (amortized). Flags → regen worklist (`visual_worklist.json`).

**Tests (VLM/CLIP mocked):**
- [ ] batch orchestration over a fixture catalog + scene set produces a catalog report, a regression diff,
  and a worklist — all from mocked model outputs.
- [ ] Commit: `feat(foundry): visual-eval batch driver + regen worklist (V task 5)`.

## Task 6 [CLI] — (LAST, optional) closed auto-reroll

**Only after the checks have earned trust in [ORCH] runs.** A flagged item triggers a re-generation with a
new seed / targeted fix, re-checked once. Gated behind a flag; off by default.
- [ ] Test: a worklist item with auto-reroll on → a re-generate call is issued (mocked) and the item re-checked.
- [ ] Commit: `feat(foundry): closed visual auto-reroll (V task 6, opt-in)`.

---

## [ORCH] Verification — orchestrator only

After handoff: the orchestrator runs the **real** batch — swap in Qwen3-VL (+ CLIP), render the prop
catalog + a scene set, produce the first real `visual_report`, and **calibrate thresholds** (what
aesthetic score / which structured flags actually correlate with "reads as slop"). Then hand the report
to the **user** to confirm the VLM's calls match their eye before we trust the gate. Iterate prompts/
thresholds from that.
