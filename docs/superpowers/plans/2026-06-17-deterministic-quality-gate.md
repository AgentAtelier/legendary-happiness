# Deterministic Quality / Collapse Gate — Implementation Plan

> **For agentic workers:** Execute task-by-task on a branch. Steps use checkbox
> (`- [ ]`) syntax. Self-contained — do exactly what it says; read referenced
> files for surrounding context.

**Goal:** Add a deterministic, advisory quality gate that inspects the scene graph
(entities, systems, operations) for cheap "collapse" signals — variety collapse,
op monoculture, thin output, missing behavior — and surfaces plain-language
warnings on every generation, *without* a model and *without* blocking.

**Architecture:** One pure function `assess_quality(operations, arch_delta,
prompt) -> list[str]` (no I/O, no LLM). The pipeline calls it before returning,
stamps the warnings onto `PipelineResult.quality_warnings`, logs them, and
includes them in the apply_spec artifact. This is slice **B** of
`docs/current/NEXT-PHASE-RECONCILED-DIRECTION.md` — the survey's "scene-graph
linter," which it chose over a VLM judge. It is **advisory only**: it never
blocks, retries, or escalates (those are expensive/risky per the survey).

**Tech Stack:** Python 3.12, pytest, ruff. DevForge engine. Live stack runs as
systemd user services; engine changes need a `forge-devforge` restart.

## Global Constraints

- **Branch only.** `git checkout main && git checkout -b feat/quality-gate`.
  NEVER commit to `main`; NEVER merge. Push + report; the owner reviews/merges.
- **Advisory, additive, behavior-preserving.** The gate must NEVER block,
  mutate operations, retry, or change generation. It only appends warnings to a
  new field. With no warnings, output is identical to before.
- **`scripts/check.sh` GREEN** after every task (`bash scripts/check.sh`, exit 0).
  New files ≤ 500 lines.
- **Engine imports are absolute under `devforge.`**
- **Commit after each task** (conventional message). If any expected result
  doesn't occur, **STOP and report**.
- **Tooling:** ruff = `hub/.venv/bin/ruff`. Engine tests: `cd engine &&
  .venv/bin/python -m pytest devforge/tests/<f>.py -v`.

---

### Task 1: The pure quality-gate function

**Files:**
- Create: `engine/devforge/governance/quality_gate.py`
- Test: `engine/devforge/tests/test_quality_gate.py`

**Interfaces:**
- Produces: `assess_quality(operations: list[dict], arch_delta: dict, prompt: str)
  -> list[str]` — returns warning strings; empty list = healthy.

- [ ] **Step 1: Confirm the package exists.**
  ```bash
  test -f engine/devforge/governance/__init__.py || : > engine/devforge/governance/__init__.py
  ```

- [ ] **Step 2: Write the failing test** at `engine/devforge/tests/test_quality_gate.py`:

```python
from devforge.governance.quality_gate import assess_quality


def test_healthy_scene_has_no_warnings():
    ops = [{"type": "add_node"}, {"type": "set_property"}, {"type": "add_node"}]
    delta = {"entities": [{"type": "MeshInstance3D"}, {"type": "Camera3D"}], "systems": []}
    assert assess_quality(ops, delta, "a small village") == []


def test_variety_collapse():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "Tree"}, {"type": "Tree"}, {"type": "Tree"}], "systems": []}
    assert any("variety_collapse" in w for w in assess_quality(ops, delta, "a forest"))


def test_operation_monoculture():
    ops = [{"type": "add_node"}, {"type": "add_node"}, {"type": "add_node"}]
    delta = {"entities": [{"type": "A"}, {"type": "B"}], "systems": []}
    assert any("operation_monoculture" in w for w in assess_quality(ops, delta, "x y z a b c d"))


def test_thin_generation():
    w = assess_quality([{"type": "add_node"}], {"entities": [], "systems": []},
                       "build a sprawling medieval castle with many towers")
    assert any("thin_generation" in x for x in w)


def test_missing_systems():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "CharacterBody3D"}], "systems": []}
    w = assess_quality(ops, delta, "an npc that can patrol and attack the player")
    assert any("missing_systems" in x for x in w)


def test_no_false_positive_on_simple_request():
    ops = [{"type": "add_node"}, {"type": "set_property"}]
    delta = {"entities": [{"type": "MeshInstance3D"}], "systems": []}
    assert assess_quality(ops, delta, "add a red cube") == []
```

- [ ] **Step 3: Run it to confirm it fails**

  Run: `cd engine && .venv/bin/python -m pytest devforge/tests/test_quality_gate.py -v`
  Expected: FAIL — `ModuleNotFoundError: No module named 'devforge.governance.quality_gate'`.

- [ ] **Step 4: Write the module** at `engine/devforge/governance/quality_gate.py`:

```python
"""Deterministic quality / collapse gate — signals, never blocks.

The chat + CLI surveys converged: judge the scene graph deterministically, not
with another model. This inspects the planner output (entities, systems) and the
generated operations for cheap, countable collapse signals and returns
plain-language WARNINGS. It is ADVISORY — it never blocks, retries, or escalates.
The warnings ride along in PipelineResult so the caller, the artifact, and the
testbench can see them.
"""

from __future__ import annotations

from typing import Any

# Words implying the scene needs behavior/systems, not just geometry.
_BEHAVIOR_KEYWORDS = (
    "move", "walk", "run", "patrol", "attack", "collect", "spawn", "die",
    "health", "score", "input", "control", "signal", "timer", "animate",
    "interact", "npc", "enemy", "player", "open", "close", "trigger",
)


def assess_quality(
    operations: list[dict[str, Any]],
    arch_delta: dict[str, Any],
    prompt: str,
) -> list[str]:
    """Return collapse/quality WARNINGS. Empty list = healthy. Pure function."""
    warnings: list[str] = []
    entities = arch_delta.get("entities") or []
    systems = arch_delta.get("systems") or []
    prompt_lc = (prompt or "").lower()
    word_count = len((prompt or "").split())

    # 1. Variety collapse: several entities, all the same type.
    if len(entities) >= 3:
        types = {e.get("type", "") for e in entities if isinstance(e, dict)}
        if len(types) == 1:
            warnings.append(
                f"variety_collapse: {len(entities)} entities but all are type "
                f"'{next(iter(types))}'"
            )

    # 2. Operation monoculture: several ops, all the same op type.
    if len(operations) >= 3:
        op_types = {o.get("type", "") for o in operations if isinstance(o, dict)}
        if len(op_types) == 1:
            warnings.append(
                f"operation_monoculture: {len(operations)} ops but all are "
                f"'{next(iter(op_types))}'"
            )

    # 3. Thin generation: a non-trivial request produced almost nothing.
    if word_count > 5 and len(operations) < 2:
        warnings.append(
            f"thin_generation: only {len(operations)} op(s) for a "
            f"{word_count}-word request"
        )

    # 4. Missing systems: the request implies behavior but none was planned.
    if not systems and any(kw in prompt_lc for kw in _BEHAVIOR_KEYWORDS):
        warnings.append(
            "missing_systems: request implies behavior but no systems were planned"
        )

    return warnings
```

- [ ] **Step 5: Run the test to confirm it passes**

  Run: `cd engine && .venv/bin/python -m pytest devforge/tests/test_quality_gate.py -v`
  Expected: PASS (6 passed).

- [ ] **Step 6: Lint + gate**

  Run: `hub/.venv/bin/ruff format engine/devforge/governance/quality_gate.py engine/devforge/tests/test_quality_gate.py && hub/.venv/bin/ruff check engine/devforge/governance/quality_gate.py engine/devforge/tests/test_quality_gate.py && bash scripts/check.sh`
  Expected: ruff clean; "All checks passed."

- [ ] **Step 7: Commit**

```bash
git add engine/devforge/governance/quality_gate.py engine/devforge/governance/__init__.py engine/devforge/tests/test_quality_gate.py
git commit -m "feat(engine): deterministic quality/collapse gate (pure, advisory)"
```

---

### Task 2: Wire it into the pipeline + artifact

**Files:**
- Modify: `engine/devforge/compilation/pipeline/engine.py` (3 edits — see steps).
- Modify: `engine/devforge/platform/mcp_server.py` (1 edit — surface in artifact).

**Interfaces:**
- Consumes: `assess_quality` from Task 1.
- Produces: `PipelineResult.quality_warnings: list[str]` (new field).

- [ ] **Step 1: Add the import** near the other `from devforge.…` imports at the
  top of `engine/devforge/compilation/pipeline/engine.py`:
  ```python
  from devforge.governance.quality_gate import assess_quality
  ```

- [ ] **Step 2: Add the field** to the `PipelineResult` dataclass (engine.py:128).
  After the last field `truncated: bool = False` (line ~151), add:
  ```python
      # Slice B: deterministic quality/collapse warnings (advisory, never blocks)
      quality_warnings: List[str] = field(default_factory=list)
  ```

- [ ] **Step 3: Populate it before the main success return.** In `run_pipeline`,
  find the `return PipelineResult(` that includes `gate_results=gate_results,`
  (the main success return, after governance). Immediately **above** that return,
  insert:

```python
            # Slice B: deterministic quality gate (advisory — signals, never blocks).
            quality_warnings = assess_quality(operations, arch_delta, planner_prompt)
            if quality_warnings:
                logger.warn(
                    "pipeline.engine",
                    f"quality gate: {'; '.join(quality_warnings)}",
                )
```

  Then add this line inside that `return PipelineResult(...)` call (e.g. right
  after the `gate_results=gate_results,` line):
  ```python
                quality_warnings=quality_warnings,
  ```

- [ ] **Step 4: Surface it in the artifact.** In
  `engine/devforge/platform/mcp_server.py`, find the `full_payload = {` dict in
  `_apply_spec_impl` (it has keys `"files"`, `"operations"`, `"errors"`,
  `"arch_delta"`, `"execution"`). Add one key:
  ```python
                "quality_warnings": result.quality_warnings,
  ```

- [ ] **Step 5: Lint + gate + import-smoke**

  Run:
  ```bash
  hub/.venv/bin/ruff format engine/devforge/compilation/pipeline/engine.py engine/devforge/platform/mcp_server.py && hub/.venv/bin/ruff check engine/devforge/compilation/pipeline/engine.py engine/devforge/platform/mcp_server.py && bash scripts/check.sh
  cd engine && .venv/bin/python -c "import devforge.platform.mcp_server; print('engine imports OK')"; cd ..
  ```
  Expected: `check.sh` green; "engine imports OK". If import fails, STOP and report.

- [ ] **Step 6: Commit**

```bash
git add engine/devforge/compilation/pipeline/engine.py engine/devforge/platform/mcp_server.py
git commit -m "feat(engine): stamp quality warnings onto PipelineResult + apply_spec artifact"
```

---

### Task 3: Prove it end-to-end (live)

The Godot editor must be open on `res://probe.tscn`, readiness `ready`.

- [ ] **Step 1: Restart the engine to load the gate.**
  ```bash
  systemctl --user restart forge-devforge.service && sleep 4
  systemctl --user is-active forge-devforge.service   # expect: active
  ```

- [ ] **Step 2: A behavior-implying prompt with no systems should warn.** Run it
  and read the artifact's `quality_warnings`:

```bash
cd hub && timeout 120 .venv/bin/python -c "
import asyncio
from mcp_client import apply_spec, read_artifact, godot_ai_call
async def m():
    st = await godot_ai_call('editor_state', {})
    if st.get('readiness') != 'ready':
        print('editor not ready — STOP (env, not code)'); return
    r = await apply_spec('an NPC named Guard that can patrol and attack the player')
    art = await read_artifact(r['artifact_id'])
    print('quality_warnings:', art.get('quality_warnings'))
asyncio.run(m())
"; cd ..
```
  Expected: `quality_warnings` contains a `missing_systems` entry (if the planner
  produced no systems). Also confirm the devforge log shows the gate line:
  `journalctl --user -u forge-devforge.service -n 40 --no-pager | grep "quality gate" | tail -1`

- [ ] **Step 3: A simple healthy prompt should NOT warn.**

```bash
cd hub && timeout 90 .venv/bin/python -c "
import asyncio
from mcp_client import apply_spec, read_artifact
async def m():
    r = await apply_spec('Add a red cube named GateSmoke to the scene root')
    art = await read_artifact(r['artifact_id'])
    print('applied:', r.get('applied'), 'quality_warnings:', art.get('quality_warnings'))
asyncio.run(m())
"; cd ..
```
  Expected: `applied > 0` and `quality_warnings: []` (no false positive on a
  simple request). If a simple request warns, STOP and report.

- [ ] **Step 4: Write a short result note** to
  `docs/reviews/quality-gate/RESULT.md` with the two outputs (warning fired on the
  behavior prompt; empty on the simple prompt). Commit + push:

```bash
git add docs/reviews/quality-gate/RESULT.md
git commit -m "docs: quality gate verified live (warns on collapse, quiet on healthy)"
git push -u origin feat/quality-gate
```

- [ ] **Step 5: Report** — branch name, both Task-3 outputs, all gates passed. Do
  NOT merge.

---

## Self-Review
- **Spec coverage:** Slice B = "deterministic scene-graph collapse signals,
  advisory, surfaced." Task 1 (pure function + tests), Task 2 (field + populate +
  artifact), Task 3 (live proof). ✓
- **Placeholder scan:** All code shown; no TBD. ✓
- **Type consistency:** `assess_quality(operations, arch_delta, prompt) ->
  list[str]` and `PipelineResult.quality_warnings: list[str]` used consistently in
  module, tests, pipeline, and artifact. ✓
- **Scope:** Single subsystem. Geometric checks (overlap/clipping/floating) are a
  deliberate follow-on — see roadmap.

---

## Remaining roadmap (everything else still open — NOT in this plan)

Each is its own future plan (one focused, testable deliverable each). Listed so
the full picture lives in one place.

**Reconciled-direction slices:**
- **Screenshot capture fix** — frame the editor camera on the built scene so
  `editor_screenshot source=viewport` shows it (worlds build fine; camera isn't
  pointed at them). *Risk to confirm FIRST:* whether godot-ai exposes a framing op
  (`view_target`/`camera_manage`/`game_eval`); if not, it needs a godot-ai plugin
  change, which is out of bounds. Gate the plan on that check.
- **Geometric quality checks (gate v2)** — extend this gate with bounding-box
  overlap, floating-node, and camera-in-wall detection (needs transform parsing
  from operations). Follow-on to this plan.
- **Schema / scale investigation (the deepest lever)** — an *experiment*, not a
  build: widen the planner's prop schema (beyond `mesh/shape/color/position/text`)
  and move *scale* to a deterministic parameter; measure whether 4B vs 27B then
  visibly diverges. Run as a probe with a verdict, like the richness experiment.
- **VLM (deferred, optional, last)** — only after a calibration set exists;
  non-gating, offline, human-facing description; never blocks.

**Maintenance backlog (separate track, not the project direction):**
- **Cherry-pick the executor chunking fix to `main`** — DONE (commit `72f4cd8`).
- **World-state branch (`exp/richness-verdict`)** — decide whether/how to merge
  its machinery (`world_planner`, `_run_world_path`, scatter/voronoi occupancy)
  into `main`; currently isolated. The conditioning + executor fixes already on
  `main` will apply to it once merged.
- **God-file splits (Layer-3 Phase 1B/1C)** — `engine.py` (~1500) and
  `mcp_server.py` (~2140) still grandfathered; split when convenient.
- **`hub.py` split (Layer-3 Phase 2)** — now unblocked (testbench migration +
  legacy deletion are done); its own plan.
