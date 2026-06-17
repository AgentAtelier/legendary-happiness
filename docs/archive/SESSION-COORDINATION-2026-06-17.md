# Session Coordination Document — June 17, 2026

**Purpose:** Another AI reading this should be able to pick up exactly where work left off.

---

## 1. BRANCH LANDSCAPE

| Branch | Role | Base |
|---|---|---|
| `main` | Production | — |
| `migrate/testbench` | **ACTIVE** — Guide 1 (all categories) + Guide 2 Phase B | off `main` at ~`b3c699d` |
| `exp/world-state-richness` | Reference — Guide 2 Phases A/B/C fully done | off `migrate/testbench` at `b5f68d3` |

**Current checkout:** `migrate/testbench`
**Last commit:** `99bfca2` — "refactor(Guide1): Category F — UI repoint to forge_testbench, remove dead JS"

---

## 2. GUIDE 1 — TESTBENCH MIGRATION: ✅ COMPLETE

All categories A–G implemented and committed on `migrate/testbench`. The legacy runners in `hub/` have been deleted. The hub Testing tab UI has been repointed.

| Category | Commit | What |
|---|---|---|
| A (probes) | `fd376ef` | Probe parity fixes + layer suites in `forge_testbench/tests/probes.py` |
| B (scenarios) | `fd376ef` | 16 scenario tests migrated to `forge_testbench/tests/scenarios.py` |
| C (gauntlet) | `1624804` | 7 gauntlet sets → `*_gauntlet.py` (capability, spatial, building, garden, ssp, wfc, voronoi) |
| D (diagnostics) | `b5f68d3` | Diagnostics (variety, intent, ceiling) → `forge_testbench/tests/diagnostics.py` |
| E (stress) | `7f2c99d` | Stress test scenario → `forge_testbench/tests/stress_v1.py` |
| F (UI repoint) | `99bfca2` | `static/index.html` repointed to testbench endpoints; ~850 lines dead JS removed |
| G (teardown) | `860c93d` | Deleted `bench.py`, `scenarios.py`, `gauntlet.py`, `diagnostics.py`; removed ~400 lines of hub.py API routes |

**New API endpoints** (added in Category F commit to `hub.py`):
- `GET /api/testbench/catalog` — returns test registry + suites from `forge_testbench/catalog.py`
- `POST /api/testbench/run` — starts an async job via `forge_testbench/runner.py`
- `GET /api/testbench/history` — returns recent `Artifact` results

### Files deleted (Guide 1 Category G)
- `hub/bench.py`
- `hub/scenarios.py`
- `hub/gauntlet.py`
- `hub/diagnostics.py`

### Files marked DEPRECATED (still exist, import deleted modules — will fail at runtime)
- `hub/multi_model_bench.py`
- `hub/comprehensive_bench.py`
- `hub/tests/test_probes.py`

### Files kept and modified
- `hub/hub.py` — removed old bench/scenarios/gauntlet routes, added testbench endpoints
- `hub/shootout.py` — MCP helpers moved inline from scenarios.py; DATA_DIR defined locally
- `hub/static/index.html` — Testing tab JS repointed; dead Bench/Probe/Scorecard/Shootout JS removed

---

## 3. GUIDE 2 — WORLD-STATE RICHNESS: 🟡 IN PROGRESS

### 3.1 Phase A — Design Proposal ✅ (on `exp/world-state-richness` only)
Commit `cd2007b` — wrote `docs/reviews/world-state/DESIGN-PROPOSAL.md`.
Not yet ported to `migrate/testbench`.

### 3.2 Phase B — WorldState Dataclass + Engine Integration 🟡 (uncommitted on `migrate/testbench`)

**Files changed (UNCOMMITTED):**

1. **NEW: `engine/devforge/spatial/world_state.py`** (untracked, ~235 lines)
   - `WorldState` dataclass — sparse occupancy grid with per-cell layers:
     - `height: Dict[(x,z), float]`
     - `biome: Dict[(x,z), str]`
     - `occupancy: Dict[(x,z), Set[str]]`
     - `network: Dict[(x,z), str]`
     - `regions: Dict[str, RegionSpec]`
   - Key methods: `is_occupied()`, `mark_occupied()`, `unmark_occupied()`, `cell_at()`, `cell_center()`, `set_height()`, `get_height()`, `set_biome()`, `get_biome()`, `set_network()`, `get_network()`, `register_region()`, `get_region()`, `summary()`, `to_dict()`, `from_dict()`
   - `RegionSpec` dataclass — `type`, `bounds: (min_x, min_z, max_x, max_z)`, `connects: List[str]`
   - Default cell size: 2m. Grid is sparse (only populated cells use memory).

2. **MODIFIED: `engine/devforge/spatial/scatter.py`**
   - Added `world_state: "WorldState | None" = None` param to `ScatterEngine.compile_garden()`
   - In placement loop: skips occupied cells via `world_state.is_occupied()`, marks footprints via `world_state.mark_occupied()`
   - Uses `placed_count` (skipped-item-aware) instead of `i` for entity naming
   - Import guarded with `TYPE_CHECKING`

3. **MODIFIED: `engine/devforge/spatial/voronoi.py`**
   - Added `world_state: "WorldState | None" = None` param to `VoronoiEngine.compile_town()`
   - Before placing each building: checks `world_state.is_occupied(bx, bz, margin=max(bw,bd)/2)`, skips if occupied
   - After placing: calls `world_state.mark_occupied(entity_id, bx, bz, footprint=(bw, bd))`
   - Import guarded with `TYPE_CHECKING`

4. **MODIFIED: `engine/devforge/spatial/__init__.py`**
   - Added `from devforge.spatial.world_state import RegionSpec, WorldState`
   - Added `"WorldState"` and `"RegionSpec"` to `__all__`

### 3.3 Phase C — WorldPlanner + _run_world_path ❌ NOT YET DONE on `migrate/testbench`

**Exists on `exp/world-state-richness`** (commit `284b328`). Must be **ported or reimplemented** on `migrate/testbench`.

Files needed:
- `engine/devforge/spatial/world_planner.py` — new file (~150 lines)
- `engine/devforge/spatial/prompts/world_planner.gbnf` — new GBNF grammar file
- `engine/devforge/compilation/pipeline/engine.py` — add `_run_world_path` method + "world" dispatch

Key design notes from the exp branch:
- `WorldPlanner` class: calls LLM with GBNF grammar → produces `world_intents` JSON array
- Each intent has: `engine` (e.g. "scatter", "voronoi", "wfc"), `region_id`, `bounds`, `keep_out`, `inside`, `spec`, `connects`, `width`, `type`
- `AVAILABLE_ENGINES` = `["scatter", "voronoi", "wfc", "building", "ssp", "room", "network"]`
- `_run_world_path` in `PipelineEngine`: orchestrates WorldPlanner → sub-engine dispatch → merged DevForgePlan with shared WorldState
- The pipeline engine stores `_world_planner`, `_world_state`, `_region_spec` fields
- Error aggregation via `world_errors` list, logged at end

**To port Phase C from the exp branch:**
```bash
git checkout exp/world-state-richness -- \
  engine/devforge/spatial/world_planner.py \
  engine/devforge/spatial/prompts/world_planner.gbnf
# Then manually merge engine.py changes (the _run_world_path method)
```

Or reimplement from scratch using the reference.

---

## 4. CURRENT UNCOMMITTED STATE

```
 M engine/devforge/spatial/__init__.py     (Phase B — added WorldState/RegionSpec exports)
 M engine/devforge/spatial/scatter.py      (Phase B — world_state param integration)
 M engine/devforge/spatial/voronoi.py      (Phase B — world_state param integration)
?? engine/devforge/spatial/world_state.py  (Phase B — new file)
```

---

## 5. IMMEDIATE NEXT STEPS (in order)

1. **Validate Phase B:** Run `ruff format` + `ruff check --fix` on the 4 changed files, then `bash scripts/check.sh`
2. **Commit Phase B** on `migrate/testbench` with a conventional commit message
3. **Implement Phase C** — port `world_planner.py`, `world_planner.gbnf`, and `_run_world_path` from `exp/world-state-richness`
4. **Validate Phase C** — ruff + check.sh
5. **Commit Phase C** on `migrate/testbench`
6. **Push `migrate/testbench`** for owner review + merge to `main`

---

## 6. KEY ARCHITECTURE NOTES FOR ANOTHER AI

### Project layout
- `engine/devforge/` — the DevForge pipeline (spatial engines, compilation, planners, prompts)
- `hub/` — the web hub (FastAPI server, static UI, testbench, MCP client)
- `hub/forge_testbench/` — the new unified test chassis (runner, catalog, context, result/metric types)
- Both `engine/` and `hub/` live in the same git repo at `/home/mrg/dev/games/Forge`

### Coding conventions (from `docs/current/CONVENTIONS.md`)
- `scripts/check.sh` is the gate — must stay green
- Uses `ruff` for formatting and linting
- New files ≤ 500 lines
- `TYPE_CHECKING` guards for optional/forward-compat imports
- `from __future__ import annotations` at top of files
- Conventional commits on feature branches

### WorldState pattern
- Engines accept `world_state: Optional[WorldState]` and use it for read-before-write coordination
- The `TYPE_CHECKING` guard keeps the import optional (no hard dependency on the new module)
- `is_occupied()` + `mark_occupied()` is the primary read/write contract
- The LLM never sees raw grid data — only `WorldState.summary()` (topological summary)

### Testbench chassis
- `Runner(emit, models, repeat, skip_cache, reset).run(test_ids, suite, models, repeat, skip_cache)` returns `Artifact`
- `Artifact` has typed `Metric` objects (no stringly-typed measurements)
- Tests are plug-in classes inheriting from `Test` (in `forge_testbench/test.py`)
- `catalog_entries()` returns `[{id, category, title, description, suites}]`

### Stack services (systemd)
- `forge-hub` — the FastAPI web server
- `forge-devforge` — the DevForge pipeline
- `forge-llama` — the LLM server (llama.cpp)
- Restart `forge-hub` after hub-side changes; restart `forge-devforge` after engine/prompt changes

---

## 7. FILE INDEX (quick lookup)

| Path | Purpose |
|---|---|
| `docs/current/IMPL-GUIDE-1-testbench-migration.md` | Guide 1 spec (all categories) |
| `docs/current/IMPL-GUIDE-2-world-state-experiment.md` | Guide 2 spec (Phases A–B) |
| `docs/current/CONVENTIONS.md` | Coding rules |
| `docs/current/FORGE-BACKLOG.md` | Backlog of remaining work |
| `docs/current/ROADMAP.md` | Project roadmap (Stage 1 & 2) |
| `docs/decisions/003-approach-survey-and-world-state-gap.md` | ADR for world-state experiment |
| `docs/decisions/005-legacy-test-runner-cutover.md` | ADR for hard-cut deletion |
| `docs/current/SPATIAL-GENERATION-ARCHITECTURE.md` | Existing spatial engine architecture |
| `engine/devforge/spatial/world_state.py` | **NEW** — WorldState + RegionSpec (uncommitted) |
| `engine/devforge/spatial/scatter.py` | ScatterEngine with world_state param (uncommitted) |
| `engine/devforge/spatial/voronoi.py` | VoronoiEngine with world_state param (uncommitted) |
| `engine/devforge/compilation/pipeline/engine.py` | PipelineEngine — needs `_run_world_path` (Phase C) |
| `hub/hub.py` | FastAPI server — testbench endpoints added, old routes removed |
| `hub/static/index.html` | Hub UI — Testing tab repointed |
| `hub/forge_testbench/` | New test chassis (catalog, runner, result, test base, context) |
| `scripts/check.sh` | Quality gate (ruff + format + file-length) |
| `pyproject.toml` | Project config + ruff settings |
