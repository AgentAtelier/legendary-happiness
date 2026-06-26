# Eval Harness — Slice 2 (deterministic quality-heuristics layer)

**Date:** 2026-06-19
**Branch:** `feat/foundry-eval-quality-heuristics` (off `main` @ `824e25b`, which holds eval slice 1)
**Premise:** local/free/deterministic, no model. This slice was specified by slice 1's first live run, not invented.

## Goal

The first live run (47 requests) exposed exactly three gaps in the harness — it couldn't measure the things we most wanted to know, and it over-sampled benign assumptions. This slice closes all three with deterministic rules (no model):

1. **Age-appropriateness signal** — we had to hand-extract the capture to learn the age-anchoring fix worked. Make it an automatic signal.
2. **Conflicting-cue flag** — "a stone-look wooden cabinet" silently resolved to wood with no flag. Surface conflicting material cues.
3. **Severity-weighted sampling** — 15 benign "no material named → oak" assumptions bloated the probe set to 31/47. Benign assumptions are not friction; weight the sampler so the human eyeball-set prioritizes real issues.

Everything slots into the existing `foundry/eval/` core; this is additive.

## Components

### Conflicting material cues (`foundry/material_resolver.py` + `foundry/eval/signals.py`)

- Add to `material_resolver.py`: `material_cues(request) -> list[tuple[str, str]]` — return **all** matched cues as `(keyword, family)`, single-sourced from the existing `_SPECIFIC_KW` / `_FAMILY_KW` maps (a specific keyword maps to its material's family via `MATERIAL_PALETTE`; a family keyword maps to its family). This is the multi-match counterpart of `resolve_material` (which returns only the first hit).
- In `signals.py` `compute_signals`: emit `"material_conflict"` when the cues span **more than one distinct family** (e.g. stone + wood). Two cues in the *same* family (e.g. "oak walnut") is NOT a conflict.

### Age-appropriateness (`foundry/eval/signals.py`)

- Add deterministic wear lexicons in `signals.py`:
  - `AGED_WORDS = {old, aged, ancient, antique, battered, weathered, worn, rustic, vintage, distressed, ...}`
  - `NEW_WORDS = {new, "brand-new", "brand new", pristine, polished, fresh, mint, unused, ...}`
- `compute_signals` emits `"age_mismatch"` when the request's wear class disagrees with `spec["age"]` (band split at ~0.4):
  - an AGED word but `age < 0.4`, OR
  - a NEW word but `age >= 0.4`, OR
  - NO wear word but `age >= 0.4` (the original high-lean — this catches a regression of the few-shot fix).
- Note: "vintage" is an AGED word, so "a vintage cabinet" at age 0.75 must NOT flag (it's consistent). This is the exact case the live run surfaced.

### Severity-weighted sampler (`foundry/eval/sampler.py`)

- Add `SIGNAL_SEVERITY: dict[str, str]` classifying each signal tag `"high"` or `"low"`:
  - **high:** `build_error`, `gate_rejected`, `size_mismatch`, `material_mismatch`, `material_conflict`, `age_mismatch`.
  - **low:** `decision_fired` (a mild assumption on its own).
- A record's tier = `"high"` if it has any high-severity tag, else `"low"` if it has only low-severity tags, else `"clean"`.
- Extend `stratify_and_sample` so: **all high-tier records are included; low-tier records are capped** at a new `low_severity_cap` (seeded-sampled when over the cap); the clean baseline is unchanged. This directly fixes the 31/47 bloat — real issues always surface, benign assumptions are sampled.
- Keep the function deterministic given `seed`. Preserve the existing `problem_cap`/`clean_baseline_n` behaviour and signature additively (new optional `low_severity_cap`, default e.g. 8).

### Report surfacing (`foundry/eval/report.py`)

- `build_friction_report` already aggregates all tags generically (new signals auto-appear in `signal_counts`). Add dedicated detail lists like the existing `size_mismatches`: `age_mismatches` (request + wear-class + age) and `material_conflicts` (request + competing cues + resolved). Surface these in both the dict and the text digest.

## Tests (synthetic records; no llama/Blender)

- **material_cues:** "a stone-look wooden cabinet" → cues spanning {stone, wood}; "an oak walnut table" → both wood; "a wooden table" → one (wood).
- **material_conflict signal:** fires for stone+wood; does NOT fire for oak+walnut (same family) or single-cue.
- **age_mismatch signal:** "an old chair" age 0.15 → fires; "a new chair" age 0.8 → fires; neutral "a tall cabinet" age 0.7 → fires; "a vintage cabinet" age 0.75 → does NOT fire; "an old chair" age 0.8 → does NOT fire.
- **sampler severity:** a population of many `decision_fired` (low) + a few `gate_rejected`/`age_mismatch` (high) → all high included, low capped at `low_severity_cap`, clean baseline included; deterministic by seed.
- **report:** dict gains `age_mismatches` and `material_conflicts`; text digest lists them.
- Existing slice-1 eval tests stay green (changes are additive).

## Out of scope (later additive slices)

Regression lens (expected-outcomes + scorer), journey-simulation lens, local CLIP/perceptual judge, qwen-augmented corpus, the UI. All still slot into the same core.
