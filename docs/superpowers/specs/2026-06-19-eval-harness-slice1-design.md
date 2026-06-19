# Autonomous Eval Harness — Slice 1 (capture + objective signals + stratified sampler + friction lens)

**Date:** 2026-06-19
**Branch:** `feat/foundry-eval-harness` (off `main`, which now holds the full foundry program at `0e8eecc`)
**Premise:** local/free/deterministic; qwen is good enough. No model in this slice (CLIP judge is a later additive layer). Human visual review does NOT scale, so we **sample** it.

## Goal

Run natural-language requests through the *whole* foundry chain **unsupervised** and turn the outcomes into **data**: what broke, what the pipeline assumed, and a small, statistically-chosen set of assets a human should actually eyeball. This is slice 1 of a layered program — it builds the **core + the cheapest signal layer + the sampler + the first report lens**, and everything later (quality heuristics, regression lens, journey lens, CLIP judge) slots into the same core.

## Architecture (one pipeline, pluggable) — lives in `foundry/eval/`

```
corpus (NL requests)
   │
   ▼
run_corpus ─────────────► list[RunRecord]         # CORE: drive chain, capture everything
   │                          │
   │                          ▼
   │                   compute_signals             # LAYER 1: objective flags (free, 100% coverage)
   │                          │
   │                          ▼
   │                   stratify_and_sample          # SAMPLER: probe set + population scaffold (seeded)
   │                          │
   ▼                          ▼
   └──────────────►   build_friction_report         # LENS 1: aggregate + the probe set, JSON + text
```

### Core — capture (`foundry/eval/harness.py`)

- `RunRecord` (dataclass): `request`, `spec` (or None), `decisions` (list of to_dict'd Decision Points), `gate_passed` (bool|None), `gate_reasons` (list), `built` (bool), `error` (str|None), `glb_path` (str|None), `seconds` (float).
- `run_corpus(requests, llm, lexicon_path, library_dir, *, build=True, plan=AssetPlanner().plan, forge=runner.forge) -> list[RunRecord]`:
  - For each request: call `plan(request, llm)` → `(spec, decisions)`; if `build`, write the spec to a temp file and call `forge(spec_path, lexicon_path, library_dir)` → capture gate/glb; on ANY exception, capture it in `error` and continue (a failure is a *signal*, never a crash).
  - `llm`, `plan`, and `forge` are **injectable** so tests pass fakes and need neither llama nor Blender. `build=False` skips forge entirely (fast planner-only signal runs).
- Persist records as **JSONL** (one record per line) via a `records_to_jsonl` / `record_to_dict` helper.

### Layer 1 — objective signals (`foundry/eval/signals.py`)

- `compute_signals(record) -> set[str]` — pure function returning signal tags:
  - `"build_error"` if `record.error`.
  - `"gate_rejected"` if `gate_passed is False`.
  - `"decision_fired"` if any Decision Point present (and expose their codes for aggregation).
  - `"size_mismatch"` — deterministic keyword rule: the request contains a size word (`tall/high → height`, `small/low → low`, `large/wide → width`, etc.) but the spec's corresponding dimension sits at the opposite end of its `PARAM_RANGES` band.
  - `"material_mismatch"` — defensive regression check: a material keyword in the request disagrees with the resolved material (should never fire post-pre-pass; catches regressions).
  - A record with no tags is **`"clean"`**.

### Sampler (`foundry/eval/sampler.py`) — the scale enabler

- `stratify_and_sample(records, signals_fn=compute_signals, *, seed, problem_cap=None, clean_baseline_n) -> SampleResult`:
  - Partition records into strata by their signals (a record can belong to multiple problem strata; `clean` is its own stratum).
  - Select **all problem-stratum records** (optionally capped per stratum at `problem_cap`) **PLUS a seeded-random baseline of `clean_baseline_n`** drawn from the `clean` stratum — the baseline is what catches false-negatives (assets automation thought were fine).
  - Deterministic given `seed` (seeded `random.Random`).
  - `SampleResult`: `probes` (selected record indices/ids + why-selected), `stratum_sizes` (full population counts per stratum), `seed`.
- `estimate_clean_rate(clean_verdicts, clean_size) -> dict` — pure: given human pass/fail verdicts on the sampled clean probes, project a clean-stratum quality rate (sampled pass-rate × population, with the sample/population sizes) so the report can state "projected quality." (Verdicts are supplied later by a human; this slice just provides + tests the estimator.)

### Lens 1 — friction report (`foundry/eval/report.py` + `foundry/eval/__main__.py`)

- `build_friction_report(records, sample) -> tuple[dict, str]`: a machine `dict` and a human-readable text/markdown digest containing: total runs; signal counts; Decision-Point frequencies by code; gate-reject-reason histogram; mismatch examples; build-error list; and **the probe set** ("eyeball these N — each line says why it was picked").
- CLI `python -m foundry.eval run <corpus_file> <lexicon> <out_dir> [--no-build] [--seed N] [--baseline N]`:
  - Loads the corpus, runs `run_corpus` (live `FoundryLLM`), writes `capture.jsonl`, `report.md`, `report.json`, `probes.json`.
  - Follow the existing `foundry/__main__.py` sys.path-insertion pattern so bare imports (`from planner import …`) resolve under `python -m foundry.eval`.

### Corpus (`foundry/eval/corpus/seed_requests.txt`)

- A hand-curated seed set (~50 lines, one request per line) covering: each generator (table/chair/shelf/cabinet) × material phrasings (explicit family "wooden/stone/metal", specific "oak/walnut/granite/wrought-iron", **no material**, ambiguous) × wear words (old/battered/new/pristine/none) × a few adversarial/odd phrasings. qwen-augmented corpus is a later slice.

## Testability (no llama / no Blender in tests)

- `run_corpus`, `compute_signals`, `stratify_and_sample`, `estimate_clean_rate`, `build_friction_report` are all **pure or injectable**. Tests pass a FAKE `llm` (and either `build=False` or a fake `forge`) to produce deterministic `RunRecord`s, then assert signals/sampling/report behaviour on synthetic data. The live full run is exercised by hand afterward, not in CI.

## Tests

- **capture:** `run_corpus` with a fake llm + `build=False` yields one RunRecord per request; an exception in plan/forge is captured in `error`, not raised; JSONL round-trips.
- **signals:** synthetic records produce the right tags — a gate-rejected record → `gate_rejected`; a record with a Decision Point → `decision_fired`; "a tall cabinet" whose spec height is at the low end → `size_mismatch`; a flag-free record → `clean`.
- **sampler:** deterministic given a seed; selects all problem-stratum records; includes exactly `clean_baseline_n` random clean records; `stratum_sizes` reflects the full population; same seed → same probes.
- **estimator:** `estimate_clean_rate` projects correctly from synthetic verdicts.
- **report:** `build_friction_report` dict has the expected keys (signal counts, decision-code frequencies, gate-reason histogram, probes); the text digest is non-empty and lists the probes with reasons.

## Out of scope (later additive slices)

Deterministic quality heuristics layer; regression lens (expected-outcomes + scorer); journey-simulation lens (sequenced sessions + session coherence); local CLIP/perceptual judge; qwen-augmented corpus; a UI over the reports. All slot into this same core.
