# Conditioning A/B — ON vs OFF

**Date:** 2026-06-17
**Branch:** `feat/planner-conditioning`
**Commit:** `019a89f`

## Prompt

> A village in a forest clearing with a road leading to it; the forest grows denser away from the road; a small market square at the village center.

## Method

- `planner='world'` (arch path), `skip_cache=True`
- ON = default (`DEVFORGE_PLANNER_CONDITIONING` unset)
- OFF = `DEVFORGE_PLANNER_CONDITIONING=0` in stack.env, service restarted

## Results

| Condition | Intent Count |
|-----------|-------------|
| ON        | 30          |
| OFF       | 9           |
| OFF       | 21          |

## Verdict

**conditioning raises planned richness (ON ≥ OFF) — system now owns it.**

ON produced 30 planned intents vs OFF's max 21 (1.4×) and min 9 (3.3×).
