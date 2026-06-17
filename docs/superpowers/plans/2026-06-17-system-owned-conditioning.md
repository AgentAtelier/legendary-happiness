# System-Owned Planner Conditioning — Implementation Plan

> **For agentic workers:** Execute this plan **task-by-task** on a branch. Steps
> use checkbox (`- [ ]`) syntax. This plan is self-contained — do exactly what it
> says; read the referenced files for surrounding context.

**Goal:** Make the richness/quality framing a system-owned directive that the
pipeline prepends to every planner prompt, so a plain user request gets the best
output without the owner ever typing "magic words" — with a deterministic toggle
and an A/B proof.

**Architecture:** One pure module (`conditioning.py`) is the single source of
truth for the directive. The pipeline's `run_pipeline` prepends it to
`planner_prompt` (the one string that flows to every planner path: arch, spatial,
world, ops) right after script-extraction. A `DEVFORGE_PLANNER_CONDITIONING=0` env
var disables it for A/B measurement. This is slice **A** of
`docs/current/NEXT-PHASE-RECONCILED-DIRECTION.md`.

**Tech Stack:** Python 3.12, pytest, ruff. DevForge engine (`engine/devforge/`).
The live stack runs as systemd user services; engine changes need a
`forge-devforge` restart to take effect.

## Global Constraints

- **Branch only.** `git checkout main && git checkout -b feat/planner-conditioning`.
  NEVER commit to `main`. NEVER merge. Push the branch and report; the owner
  reviews + merges.
- **Additive / behavior-preserving.** When conditioning is disabled (toggle `0`)
  OR the module is bypassed, output must be byte-identical to before. The only new
  behavior is the prepended directive when enabled.
- **`scripts/check.sh` must stay GREEN** after every task (`bash scripts/check.sh`,
  exit 0 — ruff + format + file-length gate). New files ≤ 500 lines.
- **Engine imports are absolute under `devforge.`** (e.g.
  `from devforge.reasoning.prompts.conditioning import prepend_conditioning`).
- **Commit after each task** with a conventional message. If any step's expected
  result does not occur, **STOP and report** — do not paper over it.
- **Tooling:** ruff is `hub/.venv/bin/ruff`. Engine tests run from `engine/`:
  `cd engine && .venv/bin/python -m pytest devforge/tests/<f>.py -v`.

---

### Task 1: The conditioning module (pure, single source of truth)

**Files:**
- Create: `engine/devforge/reasoning/prompts/conditioning.py`
- Test: `engine/devforge/tests/test_conditioning.py`

**Interfaces:**
- Produces:
  - `CONDITIONING_BLOCK: str` — the directive text.
  - `conditioning_enabled() -> bool` — reads `DEVFORGE_PLANNER_CONDITIONING`
    (default `"1"`; only `"0"` disables).
  - `prepend_conditioning(prompt: str, enabled: bool | None = None) -> str` —
    returns `f"{CONDITIONING_BLOCK}\n\n{prompt}"` when enabled, else `prompt`
    unchanged. `enabled=None` reads the env toggle.

- [ ] **Step 1: Ensure the package exists.** Confirm
  `engine/devforge/reasoning/prompts/__init__.py` exists (it should — `planner_prompt.py`
  lives there). If absent, create it empty:
  ```bash
  test -f engine/devforge/reasoning/prompts/__init__.py || : > engine/devforge/reasoning/prompts/__init__.py
  ```

- [ ] **Step 2: Write the failing test** at `engine/devforge/tests/test_conditioning.py`:

```python
from devforge.reasoning.prompts.conditioning import (
    CONDITIONING_BLOCK,
    prepend_conditioning,
)


def test_prepend_when_enabled():
    out = prepend_conditioning("a forest village", enabled=True)
    assert out.startswith(CONDITIONING_BLOCK)
    assert out.endswith("a forest village")


def test_noop_when_disabled():
    assert prepend_conditioning("a forest village", enabled=False) == "a forest village"


def test_env_toggle_default_on(monkeypatch):
    monkeypatch.delenv("DEVFORGE_PLANNER_CONDITIONING", raising=False)
    assert prepend_conditioning("x").startswith(CONDITIONING_BLOCK)


def test_env_toggle_off(monkeypatch):
    monkeypatch.setenv("DEVFORGE_PLANNER_CONDITIONING", "0")
    assert prepend_conditioning("x") == "x"
```

- [ ] **Step 3: Run it to confirm it fails**

  Run: `cd engine && .venv/bin/python -m pytest devforge/tests/test_conditioning.py -v`
  Expected: FAIL — `ModuleNotFoundError: No module named 'devforge.reasoning.prompts.conditioning'`.

- [ ] **Step 4: Write the module** at `engine/devforge/reasoning/prompts/conditioning.py`:

```python
"""System-owned planner conditioning — the one place that frames output quality.

A neutral user prompt yields thin output; an explicit "be ambitious / varied"
directive multiplies it. That directive must be OWNED BY THE SYSTEM, not typed by
the user — the non-coder owner should never need "magic words". This module is the
single source of truth; the pipeline prepends it to the prompt every planner sees.

Toggle (for A/B measurement): DEVFORGE_PLANNER_CONDITIONING=0 disables it. Any
other value (or unset) leaves it enabled.
"""

from __future__ import annotations

import os

# Deliberately SCOPE-AWARE: it must not pad a simple request (the "a simple wooden
# box should stay simple" objection from review) while unlocking richness when the
# request warrants it.
CONDITIONING_BLOCK = """\
SCENE QUALITY DIRECTIVE (from the system):
- Match the scope of the request. A simple request stays simple; a rich request
  becomes rich. Do not pad trivial requests, and never collapse a rich request
  into a single repeated primitive.
- When the request warrants richness, be ambitious: use a variety of element
  types, vary their positions and sizes, and include supporting detail — not only
  the one named object.
- Prefer a few meaningful, distinct elements over many identical copies."""


def conditioning_enabled() -> bool:
    """True unless DEVFORGE_PLANNER_CONDITIONING is set to '0'."""
    return os.getenv("DEVFORGE_PLANNER_CONDITIONING", "1") != "0"


def prepend_conditioning(prompt: str, enabled: bool | None = None) -> str:
    """Prepend the system conditioning directive to a planner prompt.

    Returns the prompt unchanged when disabled. When ``enabled`` is None, reads the
    env toggle; pass True/False explicitly in tests.
    """
    if enabled is None:
        enabled = conditioning_enabled()
    if not enabled:
        return prompt
    return f"{CONDITIONING_BLOCK}\n\n{prompt}"
```

- [ ] **Step 5: Run the test to confirm it passes**

  Run: `cd engine && .venv/bin/python -m pytest devforge/tests/test_conditioning.py -v`
  Expected: PASS (4 passed).

- [ ] **Step 6: Lint + gate**

  Run: `hub/.venv/bin/ruff format engine/devforge/reasoning/prompts/conditioning.py engine/devforge/tests/test_conditioning.py && hub/.venv/bin/ruff check engine/devforge/reasoning/prompts/conditioning.py engine/devforge/tests/test_conditioning.py && bash scripts/check.sh`
  Expected: ruff clean; `check.sh` ends "All checks passed." (exit 0).

- [ ] **Step 7: Commit**

```bash
git add engine/devforge/reasoning/prompts/conditioning.py engine/devforge/reasoning/prompts/__init__.py engine/devforge/tests/test_conditioning.py
git commit -m "feat(engine): system-owned planner conditioning module (pure, toggleable)"
```

---

### Task 2: Wire it into the pipeline (single injection point)

**Files:**
- Modify: `engine/devforge/compilation/pipeline/engine.py` (add import near the
  other `from devforge.…` imports at the top; add one injection line inside
  `run_pipeline`, immediately **before** the `# Phase 1: Context Assembly` comment
  — right after the script-extraction "fully consumed" early-return block).

**Interfaces:**
- Consumes: `prepend_conditioning` from Task 1.

- [ ] **Step 1: Add the import.** Near the top of
  `engine/devforge/compilation/pipeline/engine.py`, with the other
  `from devforge.…` imports, add:
  ```python
  from devforge.reasoning.prompts.conditioning import prepend_conditioning
  ```

- [ ] **Step 2: Add the injection.** In `run_pipeline`, find the comment line
  `# Phase 1: Context Assembly`. Immediately **above** it (after the
  `if extracted_files and not planner_prompt.strip(): … return PipelineResult(…)`
  block), insert:

```python
            # Phase 0.5: System-owned conditioning (additive). Prepend the quality
            # directive so a plain user prompt gets the best output — the owner
            # never needs "magic words". Toggle: DEVFORGE_PLANNER_CONDITIONING=0.
            # (NEXT-PHASE-RECONCILED-DIRECTION.md, slice A.)
            planner_prompt = prepend_conditioning(planner_prompt)
```

- [ ] **Step 3: Lint + gate + import-smoke**

  Run:
  ```bash
  hub/.venv/bin/ruff format engine/devforge/compilation/pipeline/engine.py && hub/.venv/bin/ruff check engine/devforge/compilation/pipeline/engine.py && bash scripts/check.sh
  cd engine && .venv/bin/python -c "import devforge.compilation.pipeline.engine; print('engine imports OK')"; cd ..
  ```
  Expected: `check.sh` green; "engine imports OK". If the import fails, STOP and report.

- [ ] **Step 4: Restart the engine + behavior-preserving smoke.** The change is
  additive; confirm the existing path still works end-to-end (the Godot editor
  must be open on `res://probe.tscn`, readiness `ready`).

```bash
systemctl --user restart forge-devforge.service && sleep 4
cd hub && .venv/bin/python -c "
import asyncio
from mcp_client import apply_spec, godot_ai_call
async def m():
    st = await godot_ai_call('editor_state', {})
    assert st.get('readiness') == 'ready', f'editor not ready: {st}'
    r = await apply_spec('Add a red cube named CondSmoke to the scene root')
    print('apply:', {k: r.get(k) for k in ('applied','error_count')})
    assert r.get('applied', 0) > 0 and r.get('error_count', 1) == 0
    print('SMOKE OK')
asyncio.run(m())
"; cd ..
```
  Expected: `applied > 0`, `error_count == 0`, "SMOKE OK". If the editor isn't
  ready, STOP and report (environmental, not a code failure).

- [ ] **Step 5: Commit**

```bash
git add engine/devforge/compilation/pipeline/engine.py
git commit -m "feat(engine): prepend system conditioning to planner_prompt in run_pipeline"
```

---

### Task 3: Prove it (A/B — conditioning on vs off)

This is the deliverable's proof: the SAME rich prompt should plan **at least as
many** distinct regions/entities with conditioning ON as OFF (it unlocked ~3–4×
richness in the manual experiment — now system-owned, no magic words in the user
prompt).

**Files:**
- Create: `docs/reviews/world-state-richness/CONDITIONING-AB.md` (the result note).

- [ ] **Step 1: Capture ON (default).** Conditioning is on by default. Run a rich
  spatial prompt twice and record the planned intent/entity count from the logs:

```bash
cd hub && .venv/bin/python -c "
import asyncio
from mcp_client import apply_spec, godot_ai_call
PROMPT='A village in a forest clearing with a road leading to it; the forest grows denser away from the road; a small market square at the village center.'
async def m():
    for i in (1,2):
        try:
            from forge_testbench.runner import _scene_reset; await _scene_reset()
        except Exception as e: print('reset warn', e)
        r = await apply_spec(PROMPT, planner='world', skip_cache=True)
        print('ON run', i, {k:r.get(k) for k in ('applied','error_count')})
asyncio.run(m())
"; cd ..
journalctl --user -u forge-devforge.service -n 60 --no-pager | grep 'World plan parsed' | tail -2
```
  Record the two "World plan parsed: N intent(s)" numbers as **ON**.

- [ ] **Step 2: Capture OFF.** Disable the toggle, restart, repeat:

```bash
# append the disable toggle to stack.env
grep -q '^DEVFORGE_PLANNER_CONDITIONING=' ~/.config/forge-stack/stack.env \
  && sed -i 's/^DEVFORGE_PLANNER_CONDITIONING=.*/DEVFORGE_PLANNER_CONDITIONING=0/' ~/.config/forge-stack/stack.env \
  || printf '\nDEVFORGE_PLANNER_CONDITIONING=0\n' >> ~/.config/forge-stack/stack.env
systemctl --user restart forge-devforge.service && sleep 4
cd hub && .venv/bin/python -c "
import asyncio
from mcp_client import apply_spec
PROMPT='A village in a forest clearing with a road leading to it; the forest grows denser away from the road; a small market square at the village center.'
async def m():
    for i in (1,2):
        try:
            from forge_testbench.runner import _scene_reset; await _scene_reset()
        except Exception as e: print('reset warn', e)
        r = await apply_spec(PROMPT, planner='world', skip_cache=True)
        print('OFF run', i, {k:r.get(k) for k in ('applied','error_count')})
asyncio.run(m())
"; cd ..
journalctl --user -u forge-devforge.service -n 60 --no-pager | grep 'World plan parsed' | tail -2
```
  Record the two numbers as **OFF**.

- [ ] **Step 3: Restore the toggle to ON.**

```bash
sed -i '/^DEVFORGE_PLANNER_CONDITIONING=0$/d' ~/.config/forge-stack/stack.env
systemctl --user restart forge-devforge.service && sleep 4
```

- [ ] **Step 4: Write the result note** to
  `docs/reviews/world-state-richness/CONDITIONING-AB.md` with the exact prompt, the
  ON intent counts, the OFF intent counts, and a one-line verdict:
  "conditioning raises planned richness (ON ≥ OFF) — system now owns it" or, if ON
  is NOT ≥ OFF, "no effect / regression — FLAG for owner" and STOP.

- [ ] **Step 5: Commit + push the branch**

```bash
git add docs/reviews/world-state-richness/CONDITIONING-AB.md
git commit -m "docs(experiment): A/B confirms system-owned conditioning raises planned richness"
git push -u origin feat/planner-conditioning
```

- [ ] **Step 6: Report.** Reply with: the branch name, the ON vs OFF numbers, and
  whether all three tasks' gates passed. Do NOT merge.

---

## Self-Review

- **Spec coverage:** Slice A of the reconciled direction = "one conditioning
  module, injected at the dispatch, env toggle, proven impact." Task 1 (module),
  Task 2 (single injection at `run_pipeline`, env toggle), Task 3 (A/B proof). ✓
- **Placeholder scan:** All code shown in full; no TBD/TODO. ✓
- **Type consistency:** `prepend_conditioning(prompt, enabled=None) -> str` and
  `CONDITIONING_BLOCK` used identically in the module, the test, and the engine
  import. ✓
- **Scope:** Single subsystem (planner prompt conditioning). The deterministic
  collapse gate (B), screenshot capture, and schema/scale work are **separate
  plans** by design.
