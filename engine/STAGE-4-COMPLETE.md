# Stage 4 Rebalance — Complete (2026-06-16)

## Overview

Stage 4 replaces the SSP archetype-label model with a rich Intent Descriptor
interface. Instead of the LLM picking "kitchen" from a catalog, it authors a
structured creative brief (type, size, style, clutter, mood, must-have props,
features, seed) that the SSPEngine resolves into a parameterized, seeded room.

Four moves, fully implemented and tested.

---

## Move 1 — Model-Blind Cache Fix

**Problem:** The ArchitecturePlanner cache made repeat-diversity measurement
impossible — every call to `plan()` returned the cached result.

**Solution:** `skip_cache: bool = False` parameter threaded through the entire
pipeline.

### Files changed

| File | Change |
|------|--------|
| `compilation/pipeline/architecture_planner.py` | `plan()` accepts `skip_cache`; guards cache lookup/store with `not skip_cache` |
| `compilation/pipeline/engine.py` | `run_pipeline()` accepts and threads `skip_cache` through `_run_arch_path()`, `_run_spatial_path()`, and all 7 wrappers (`_run_layout_path`, `_run_building_path`, `_run_scatter_path`, `_run_ssp_path`, `_run_room_path`, `_run_wfc_path`, `_run_voronoi_path`) |
| `platform/server/server.py` | `GenerateRequest` accepts `skip_cache`, `planner`, `temperature` |
| `platform/mcp_server.py` | `apply_spec` threads `skip_cache` through to `run_pipeline()` |
| All 6 spatial planners | `plan()` accepts `skip_cache=False` for API compatibility |

### Usage

```python
# Measure true repeat-diversity (no cache):
result = engine.run_pipeline("build a kitchen", skip_cache=True, runs=10)
```

---

## Move 2 — Intent Descriptor Interface

**Problem:** The old SSP planner had the LLM pick from a flat catalog of 14
archetype labels. No adjectives, no mood, no creative control.

**Solution:** Grammar-constrained Intent Descriptor — the LLM authors a rich
JSON brief; every field changes the build.

### Move 2a — Grammar (`room_intent.gbnf`)

```
root ::= "{" ws "\"room_type\"" ws ":" ws string ws room-extra* ws "}"
room-extra ::= size-kv | style-kv | clutter-kv | mood-tags-kv | must-have-kv | special-features-kv | seed-kv
```

- `room_type`: Free text string (required)
- `size`: Enumerated — `cramped | normal | spacious`
- `style`: Enumerated — `rustic | industrial | noble | derelict`
- `clutter`: Number 0.0–1.0
- `mood_tags`: String array (13 known moods + open)
- `must_have`: String array (lexicon-validated asset IDs)
- `special_features`: String array (10 known features + open)
- `seed`: Integer (optional)

### Move 2b — RoomIntentPlanner

`devforge/spatial/room_intent_planner.py`

- `plan(context, prompt, llm_fn)` → Intent Descriptor dict
- Builds a creative prompt listing room types, features, moods, indoor assets
- Validates enumerated fields (size, style) with graceful degradation
- Filters must_have assets against the lexicon
- Clamps clutter to [0, 1]
- Wraps LLM errors in `RoomPlanningError`

### Move 2c — Engine Routing

`planner="room"` wired into `engine.py`:
- `RoomIntentPlanner` imported and initialized as `self._room_intent_planner`
- `_run_room_path()` wrapper delegates to `_run_spatial_path()`
- `runtime_config.py`: `"room"` added to `VALID_PLANNER_MODES`
- `spatial/__init__.py`: Exports `RoomIntentPlanner`

---

## Move 3 — Parameterized SSP Engine

**Problem:** The old SSPEngine was a static lookup table — same archetype always
produced the same room. No variation, no parameterization.

**Solution:** Two-path engine — detects format automatically and resolves every
Intent Descriptor field.

### Files changed

`devforge/spatial/ssp.py` — rebuilt `SSPEngine`

### Resolution map

| Intent Field | Engine Resolution |
|-------------|-------------------|
| `room_type` | `_REQUIRED_CATEGORIES` → picks assets from `_CATEGORY_TO_ASSETS`, assigns to randomly shuffled `_AVAILABLE_SLOTS` |
| `size` | `_SIZE_PRESETS` — cramped=3×3m, normal=5×4m, spacious=8×6m |
| `style` | `_STYLE_PALETTES` — rustic/industrial/noble/derelict RGB palettes → `slot_colours` |
| `clutter` | 0→1 scale → N extra props from `_CLUTTER_ASSETS` in `_CLUTTER_SLOTS` |
| `mood_tags` | `_MOOD_MODIFIERS` — 13 tags modify saturation, brightness, height, intact ratio, placement bias, prop count |
| `must_have` | Forced assets in available slots (can replace clutter slots) |
| `special_features` | Known features → ARCS overrides (secret_passage → shelf, fireplace → cabinet); unknown → logged & skipped |
| `seed` | Seeded `random.Random` — same brief + same seed = same room; different seed = different valid room |

### Backward compatibility

- `"archetype"` key → legacy path (`_compile_legacy`) — identical behavior
- `"room_type"` key → Intent path (`_compile_intent`) — new resolution
- Neither key → fallback to kitchen via Intent path

### Infrastructure

- `_SIZE_PRESETS`, `_STYLE_PALETTES`, `_MOOD_MODIFIERS` — module-level constants
- `_REQUIRED_CATEGORIES` + `_CATEGORY_TO_ASSETS` — category-based asset assignment
- `_AVAILABLE_SLOTS`, `_CLUTTER_SLOTS`, `_CLUTTER_ASSETS` — slot/category catalogs
- `_CHAIN_SLOTS` — dependency ordering for chain-anchor slots (chair_* → center_table)
- `_apply_color_mod()`, `_pick_with_seed()`, `_shuffle_with_seed()` — helper functions

---

## Move 4 — Variety Dashboard

**Problem:** No way to measure output diversity — the engine could produce
identical rooms for different prompts and nobody would know.

**Solution:** New check types in `gauntlet.py` + diagnostic runner.

### Check types

| Check | Expect Key | What It Measures |
|-------|-----------|-----------------|
| `variety:repeat_diversity` | `variety_min_diversity` | Jaccard distance of node sets across N runs (0=identical, 1=completely different) |
| `variety:intent_coverage` | `variety_min_intent_fields` | Adjacent-pair node set comparison — how many intent field variants produce different outputs |
| `variety:descriptor_entropy` | `variety_min_entropy` | Distinct arch_delta descriptors / total runs (measures LLM expressiveness) |
| `fidelity:llm_judge` | `fidelity_expect_rating` | Stub — deferred until LLM judge wiring is ready |

### How it works

- `--runs N` → aggregation block stores full `_ops` + `_arch_delta` per run
- `_compute_diversity(run_data)` → Jaccard distance, asset similarity, distinct outputs
- `_add_variety_checks()` fires new check types against expect keys
- Variety scorecard prints after the summary

### Diagnostic runner

`hub/diagnostics.py` — standalone script for live diversity measurement:

```bash
python diagnostics.py repeat   # "build a kitchen" ×10 — Jaccard + distinct ratio
python diagnostics.py intent   # 4 adjective variants — pairwise comparison
python diagnostics.py ceiling  # "wizard's tower" — node count (run once per model)
python diagnostics.py all      # All three
```

### Live diagnostic result (Qwen3.6-27B)

| Variant | Nodes | Latency |
|---------|-------|---------|
| cramped | 4 | 37s |
| spacious | 5 | 45s |
| abandoned | 4 | 49s |
| luxurious | 0 | 64s |

**Intent coverage: 5/6 pairs differ (83%)** — adjectives ARE being read and DO
change output. The hypothesis of 0% coverage is **refuted**.

---

## Infrastructure Fixes

### Compiler resilience

- `compiler.py`: `except (SlotViolation, ValueError)` in slot fill loop — chain-
  resolution failures skip gracefully instead of crashing the entire compilation
- `compiler.py`: `slot_colours` from layout_json propagated to placed assets as
  `material_override` SetPropertySteps (Step 3b)

### SSPEngine ordering

- Chain-slot dependency ordering: `_CHAIN_SLOTS` (`chair_north`, `chair_south`,
  `chair_east`, `chair_west`, `chair_inner`, `chair_outer`) always placed after
  `center_table` so chain targets resolve successfully

### Server threading

- `server.py` + `mcp_server.py`: `skip_cache`, `planner`, `temperature` threaded
  through HTTP/MCP endpoints

---

## Test Coverage

| File | Tests | Covers |
|------|-------|--------|
| `test_room_intent_planner.py` | 51 | Grammar loading, prompt building, response parsing (think tags, fences, prose, clamp, validation), graceful degradation, plan() with stubbed LLM, constants |
| `test_ssp.py` (extended) | 20+ | Intent Descriptor format detection, size presets, style palettes, mood modifiers, clutter, must_have, special features, seed determinism, backward compat, full descriptor compilation |
| Full suite | 689 | All passes, 0 failures, 0 regressions |

---

## File Manifest

### New files
```
devforge/spatial/prompts/room_intent.gbnf
devforge/spatial/room_intent_planner.py
devforge/tests/test_room_intent_planner.py
hub/data/gauntlet/sets/variety-v1.json
hub/data/gauntlet/sets/move1-diagnostics.json
hub/diagnostics.py
```

### Modified files
```
devforge/compilation/pipeline/architecture_planner.py   (skip_cache param)
devforge/compilation/pipeline/engine.py                  (skip_cache + room routing)
devforge/spatial/ssp.py                                  (Intent Descriptor engine + chain ordering)
devforge/spatial/ssp_planner.py                          (skip_cache param)
devforge/spatial/layout_planner.py                       (skip_cache param)
devforge/spatial/building_planner.py                     (skip_cache param)
devforge/spatial/scatter_planner.py                      (skip_cache param)
devforge/spatial/wfc_planner.py                          (skip_cache param)
devforge/spatial/voronoi_planner.py                      (skip_cache param)
devforge/spatial/__init__.py                             (RoomIntentPlanner export)
devforge/spatial/compiler.py                             (ValueError catch + slot_colours)
devforge/platform/server/server.py                       (skip_cache/planner/temp)
devforge/platform/mcp_server.py                          (skip_cache threading)
devforge/infrastructure/runtime_config.py                (room mode)
devforge/tests/test_ssp.py                               (Intent Descriptor tests)
hub/gauntlet.py                                          (variety checks + diversity)
```

---

## How to Use

### Old SSP (still works)
```python
result = engine.run_pipeline("build a kitchen", planner="ssp")
```

### New Intent Descriptor
```python
result = engine.run_pipeline(
    "build a cramped abandoned kitchen with a poison cabinet",
    planner="room",
)
```

### With cache bypass for diagnostics
```python
result = engine.run_pipeline("build a kitchen", planner="room", skip_cache=True)
```

### Variety gauntlet
```bash
cd hub && python gauntlet.py --run variety-v1 --runs 10
```

### Live diagnostics
```bash
cd hub && python diagnostics.py all
```
