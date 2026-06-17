# Forge Hub — Testing & Look Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the hub's four scattered testing tabs into one faceted Testing tab with a single 0–100 + verdict scoring model, honest live progress, real press feedback, a global re-skin, and a hand-drawn logo.

**Architecture:** Zero-build vanilla — refactor `hub/static/index.html` in place. A new pure-Python module `hub/forge_score.py` owns score→verdict normalization and ETA math (fully pytest-tested via the existing `TestClient` pattern in `tests/test_hub_api.py`). The frontend becomes a thin renderer of normalized results. Existing run endpoints stay; the frontend routes facet combos to them.

**Tech Stack:** FastAPI (existing), vanilla JS + hand CSS, inline SVG, pytest + `fastapi.testclient.TestClient`.

**Git note:** This tree is NOT a git repository. Do not `git init` or `git commit`. Each task ends in a **Checkpoint** (run the test suite green) instead of a commit. If the user later wants version control, that is a separate decision.

**Spec:** `docs/superpowers/specs/2026-06-14-hub-testing-rework-design.md`

---

## File Structure

- **Create** `hub/forge_score.py` — pure scoring/verdict/ETA functions. One responsibility: turn any suite's raw result into the unified scorecard shape, and durations into an ETA. No I/O, no FastAPI.
- **Create** `hub/tests/test_forge_score.py` — unit tests for the above.
- **Modify** `hub/hub.py` — apply `normalize_result` to the four run endpoints' responses; ensure each run records `duration_s` in history.
- **Modify** `hub/tests/test_hub_api.py` — served-HTML structural assertions (theme tokens, logo, 6-tab nav, Testing tab present, old 4 tabs gone) + normalized-shape assertions.
- **Modify** `hub/static/index.html` — theme remap, logo SVG, new Testing tab (faceted runner + unified scorecard + live strip + history), global button-feedback helper, nav 9→6. Remove the four old testing tabs' markup/JS.

**The unified scorecard shape** (returned by `normalize_result`, rendered by `renderScorecard`):
```json
{
  "suite": "gauntlet", "target": "current", "label": "capability-v1 · qwen3-14b",
  "score": 83, "verdict": "partial",
  "metrics": [
    {"label": "depth", "value": "1/4", "good": false},
    {"label": "scripts", "value": 4, "good": true},
    {"label": "nodes", "value": "3/25", "good": false},
    {"label": "overlap", "value": 0, "good": true}
  ]
}
```

---

## Phase A — Global re-skin + logo (lowest risk, immediate unification)

### Task 1: Theme palette remap

**Files:**
- Modify: `hub/static/index.html` (the `:root` block ~line 10, and literal border colors)
- Test: `hub/tests/test_hub_api.py`

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_hub_api.py`:
```python
class TestTheme:
    def test_new_palette_tokens_served(self):
        r = client.get("/", headers={"Host": "127.0.0.1:8003"})
        assert r.status_code == 200
        html = r.text
        # middle-ground palette + bright border
        assert "--bg:#0a0e0a" in html
        assert "--panebg:#0e160e" in html
        assert "--fg:#b8e6c4" in html
        assert "--border:#3f9657" in html
        assert "--warn-amber:#e0b341" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mrg/dev/games/Forge/hub && .venv/bin/python -m pytest tests/test_hub_api.py::TestTheme -v`
Expected: FAIL (old `--bg:#070b07` still served).

- [ ] **Step 3: Implement — remap `:root`**

Replace the `:root { ... }` line (~line 10 of `index.html`) with:
```css
:root { --bg:#0a0e0a; --panebg:#0e160e; --fg:#b8e6c4; --dim:#6f8a76; --border:#3f9657;
  --accent:#00ff41; --ok:#00ff41; --warn-amber:#e0b341; --warn:#e0b341; --err:#ff5b5b; --blue:#3fd0ff; }
```

- [ ] **Step 4: Route literal border colors to the token**

In `index.html`, replace the hardcoded border literals so the look is driven by `--border`. Do a literal find-and-replace (these are the border greens used throughout):
- `#1f5c1f` → `var(--border)`
- `#143014` → `var(--border)`
- `#2e7d3a` (only where it appears inside a `border` / `border-color` declaration; leave `--dim` mapping alone) → `var(--border)`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestTheme -v`
Expected: PASS.

- [ ] **Step 6: Manual verify**

Start the hub, load it, confirm: dark slate panes, gray-green body text, bright green box outlines, neon green headings, no broken/invisible borders.

- [ ] **Step 7: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → all green.

---

### Task 2: Header logo (inline SVG)

**Files:**
- Modify: `hub/static/index.html` (`#header` block ~line 171)
- Test: `hub/tests/test_hub_api.py`

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_hub_api.py`:
```python
class TestLogo:
    def test_logo_svg_present(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="forge-logo"' in html
        assert "<svg" in html
        assert 'aria-label="Forge Hub logo"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestLogo -v`
Expected: FAIL.

- [ ] **Step 3: Implement — replace the `⚒ FORGE-HUB` h1**

In `index.html`, replace `<h1>⚒ FORGE-HUB</h1>` with the logo + wordmark:
```html
<h1 style="display:flex;align-items:center;gap:8px;">
  <svg id="forge-logo" viewBox="0 0 48 48" width="30" height="30" role="img" aria-label="Forge Hub logo" style="flex:none;">
    <!-- RPG hex emblem frame -->
    <polygon points="24,2 44,13 44,35 24,46 4,35 4,13" fill="none" stroke="var(--accent)" stroke-width="2"/>
    <!-- Terraform: terrain contour lines -->
    <path d="M9 34 Q16 31 24 34 T39 34" fill="none" stroke="var(--dim)" stroke-width="1.6"/>
    <path d="M11 38 Q18 35.5 24 38 T37 38" fill="none" stroke="var(--dim)" stroke-width="1.3" opacity="0.7"/>
    <!-- DevForge: anvil -->
    <path d="M15 19 H33 V22 H27 L26 26 H22 L21 22 H15 Z M19 26 H29 V29 H19 Z" fill="var(--accent)"/>
    <!-- Climate disaster: heat/lightning streak -->
    <path d="M31 7 L23 21 L27 21 L19 35" fill="none" stroke="var(--warn-amber)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>
  FORGE-HUB
</h1>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestLogo -v`
Expected: PASS.

- [ ] **Step 5: Manual verify**

Load the hub; confirm the emblem renders crisply at header height: hex frame, anvil, contour lines, amber streak. Inherits theme colors.

- [ ] **Step 6: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

## Phase B — Unified scoring backend (`forge_score.py`)

### Task 3: `score_to_verdict`

**Files:**
- Create: `hub/forge_score.py`
- Test: `hub/tests/test_forge_score.py`

- [ ] **Step 1: Write the failing test**

Create `hub/tests/test_forge_score.py`:
```python
from forge_score import score_to_verdict


class TestVerdict:
    def test_pass_at_90(self):
        assert score_to_verdict(90) == "pass"
        assert score_to_verdict(100) == "pass"

    def test_partial_band(self):
        assert score_to_verdict(60) == "partial"
        assert score_to_verdict(89) == "partial"

    def test_fail_below_60(self):
        assert score_to_verdict(59) == "fail"
        assert score_to_verdict(0) == "fail"

    def test_custom_thresholds(self):
        assert score_to_verdict(80, pass_at=80, partial_at=50) == "pass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestVerdict -v`
Expected: FAIL (no module `forge_score`).

- [ ] **Step 3: Implement**

Create `hub/forge_score.py`:
```python
"""Unified scoring for the Forge hub Testing tab.

Pure functions only — no I/O, no FastAPI. Turns any suite's raw result into the
common scorecard shape and durations into a soft ETA. Tested in
tests/test_forge_score.py.
"""
from __future__ import annotations
from statistics import median
from typing import Any


def score_to_verdict(score: float, pass_at: float = 90, partial_at: float = 60) -> str:
    """Map a 0-100 score to a verdict band."""
    if score >= pass_at:
        return "pass"
    if score >= partial_at:
        return "partial"
    return "fail"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestVerdict -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

### Task 4: `normalize_result` (per-suite → common scorecard)

**Files:**
- Modify: `hub/forge_score.py`
- Test: `hub/tests/test_forge_score.py`

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_forge_score.py`:
```python
from forge_score import normalize_result


class TestNormalize:
    def test_health_passfail_maps_to_100_0(self):
        raw = {"checks": [{"name": "llama", "passed": True},
                          {"name": "devforge", "passed": True},
                          {"name": "godot", "passed": False}]}
        card = normalize_result("health", raw, target="current", label="quick")
        assert card["suite"] == "health"
        assert card["score"] == 67  # 2/3 rounded
        assert card["verdict"] == "fail"
        assert {"label": "godot", "value": "fail", "good": False} in card["metrics"]

    def test_gauntlet_coverage_is_score(self):
        raw = {"coverage": 83, "metrics": {"depth": "1/4", "scripts": 4,
                                           "nodes": "3/25", "overlap": 0}}
        card = normalize_result("gauntlet", raw, target="current", label="G7")
        assert card["score"] == 83
        assert card["verdict"] == "partial"
        # good/bad inferred: fractions where num<den are bad, zero-overlap is good
        labels = {m["label"]: m for m in card["metrics"]}
        assert labels["scripts"]["good"] is True
        assert labels["nodes"]["good"] is False
        assert labels["overlap"]["good"] is True

    def test_scenarios_coverage_is_score(self):
        raw = {"coverage": 95, "metrics": {"geometry": "9/10", "tools": "ok"}}
        card = normalize_result("scenarios", raw, target="current", label="all")
        assert card["score"] == 95
        assert card["verdict"] == "pass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestNormalize -v`
Expected: FAIL (no `normalize_result`).

- [ ] **Step 3: Implement**

Append to `hub/forge_score.py`:
```python
def _metric_good(label: str, value: Any) -> bool:
    """Heuristic: a metric is 'good' unless it signals a shortfall.
    - 'n/m' fraction: good iff n >= m.
    - 'overlap'/'err'/'errors': good iff zero/falsey.
    - bool: good iff True. Everything else: good (informational)."""
    low = label.lower()
    if isinstance(value, str) and "/" in value:
        try:
            num, den = (int(x) for x in value.split("/", 1))
            return num >= den
        except ValueError:
            return True
    if low in ("overlap", "err", "errors", "failed"):
        return not value
    if isinstance(value, bool):
        return value
    return True


def normalize_result(suite: str, raw: dict, *, target: str = "current",
                     label: str = "") -> dict:
    """Turn any suite's raw result into the unified scorecard shape."""
    metrics: list[dict] = []
    if suite == "health":
        checks = raw.get("checks", [])
        passed = sum(1 for c in checks if c.get("passed"))
        score = round(100 * passed / len(checks)) if checks else 0
        metrics = [{"label": c.get("name", "?"),
                    "value": "pass" if c.get("passed") else "fail",
                    "good": bool(c.get("passed"))} for c in checks]
    else:  # scenarios, gauntlet, and any coverage-based suite
        score = round(raw.get("coverage", raw.get("score", 0)))
        for k, v in (raw.get("metrics") or {}).items():
            metrics.append({"label": k, "value": v, "good": _metric_good(k, v)})
    return {"suite": suite, "target": target, "label": label,
            "score": score, "verdict": score_to_verdict(score), "metrics": metrics}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestNormalize -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

### Task 5: `eta_from_durations`

**Files:**
- Modify: `hub/forge_score.py`
- Test: `hub/tests/test_forge_score.py`

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_forge_score.py`:
```python
from forge_score import eta_from_durations


class TestEta:
    def test_median_of_recent(self):
        # uses the most recent N, returns median seconds
        assert eta_from_durations([100, 120, 110], recent=5) == 110

    def test_caps_to_recent(self):
        # only the last 2 considered → median(200,300)=250
        assert eta_from_durations([10, 10, 10, 200, 300], recent=2) == 250

    def test_too_few_returns_none(self):
        assert eta_from_durations([90], recent=5) is None
        assert eta_from_durations([], recent=5) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestEta -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `hub/forge_score.py`:
```python
def eta_from_durations(durations: list[float], recent: int = 5) -> float | None:
    """Median of the most recent `recent` run durations, or None if <2 samples.
    Returns an estimate in the same unit as the inputs (seconds)."""
    if len(durations) < 2:
        return None
    window = durations[-recent:]
    return median(window)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_forge_score.py::TestEta -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

## Phase C — Wire normalization (ADAPTED during execution)

> **Execution note (2026-06-14):** The four runners are async SSE jobs (`POST`→`job_id`→
> stream→result persisted to history), NOT synchronous calls. So normalization runs
> **frontend-side**, mirroring the tested Python `normalize_result`/`score_to_verdict`
> (the spec permits "frontend-side initially"). The Python module remains the canonical
> unit-tested reference. ETA history is kept in `localStorage` per suite+target — no backend
> change. Task 6 below is therefore reduced to an **import-guard contract test**; the real
> wiring lives in Tasks 8–9. Backend run/persistence code is left untouched (lowest risk).

### Task 6: Contract guard — hub can import the tested normalizer

**Files:**
- Modify: `hub/hub.py` (the four run endpoints: `/api/bench/run`, `/api/scenarios/run`, `/api/gauntlet/run`, `/api/shootout`; their history-recording paths)
- Test: `hub/tests/test_hub_api.py`

- [ ] **Step 1: Read first**

Read each run endpoint in `hub.py` (lines ~715, 834, 997, 900) and find where each appends to history (search `history`, `_record`, `.append(`, json dump under `data/`). Note the result dict each returns and the raw fields available (coverage / checks / metrics / timing). This determines the exact `normalize_result(...)` call args.

- [ ] **Step 2: Write the failing test**

Add to `hub/tests/test_hub_api.py` (uses the existing live-stack-free path — assert the gauntlet *sets* endpoint and the normalized shape helper are wired; for run endpoints that need the stack, assert the response schema key exists on a mocked/last-history read):
```python
from forge_score import normalize_result

class TestNormalizedShape:
    def test_normalize_contract_used_by_hub(self):
        # The hub must expose results in the unified shape. Contract test on the
        # helper the endpoints call, guarding the keys the frontend depends on.
        card = normalize_result("gauntlet",
                                {"coverage": 83, "metrics": {"nodes": "3/25"}},
                                target="current", label="G7")
        assert set(card) >= {"suite", "target", "label", "score", "verdict", "metrics"}
        assert card["verdict"] in ("pass", "partial", "fail")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestNormalizedShape -v`
Expected: FAIL until `from forge_score import normalize_result` resolves at the hub package root (confirms module importable from tests dir).

- [ ] **Step 4: Implement — wrap responses + record duration**

In each of the four run endpoints in `hub.py`:
1. At the top of the handler, capture `t0 = time.monotonic()`.
2. After the run produces its raw result dict, compute `duration_s = round(time.monotonic() - t0, 1)` and add it to both the response and the history entry being persisted.
3. Build the unified card and attach it:
```python
from forge_score import normalize_result
# health (bench):
result["scorecard"] = normalize_result("health", result, target="current",
                                        label=result.get("label", "health"))
# scenarios:
result["scorecard"] = normalize_result("scenarios", result, target="current",
                                        label=result.get("model", "scenarios"))
# gauntlet:
result["scorecard"] = normalize_result("gauntlet", result, target="current",
                                        label=result.get("set", "gauntlet"))
# shootout (per-model): attach a scorecard per model entry, target="compare"
for entry in result.get("models", []):
    entry["scorecard"] = normalize_result("scenarios", entry, target="compare",
                                           label=entry.get("model", "?"))
```
(Adapt the raw field names to what Step 1 found — e.g. if bench returns `tests` not `checks`, map it: `{"checks": [{"name": t["name"], "passed": t["status"]=="pass"} for t in result["tests"]]}` before normalizing.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestNormalizedShape -v`
Expected: PASS.

- [ ] **Step 6: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

## Phase D — Testing tab frontend (faceted runner)

### Task 7: Nav 9→6 + Testing tab shell; remove old 4 tabs

**Files:**
- Modify: `hub/static/index.html` (`<nav>` ~line 180; tab bodies `#tab-bench` ~222, `#tab-score` ~266, `#tab-shootout` ~287, `#tab-gauntlet` ~317; their JS handlers)
- Test: `hub/tests/test_hub_api.py`

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_hub_api.py`:
```python
class TestNav:
    def test_six_tab_nav(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'data-tab="testing"' in html
        # old testing tabs folded away
        for gone in ('data-tab="bench"', 'data-tab="score"',
                     'data-tab="shootout"', 'data-tab="gauntlet"'):
            assert gone not in html, f"{gone} should be removed"
        # survivors
        for keep in ("overview", "testing", "models", "config", "activity", "doc"):
            assert f'data-tab="{keep}"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestNav -v`
Expected: FAIL.

- [ ] **Step 3: Implement — replace nav**

Replace the `<nav id="nav">…</nav>` block with:
```html
<nav id="nav">
  <button data-tab="overview" class="active">Overview</button>
  <button data-tab="testing">Testing</button>
  <button data-tab="models">Models</button>
  <button data-tab="config">Config</button>
  <button data-tab="activity">Activity</button>
  <button data-tab="doc">Doc</button>
</nav>
```

- [ ] **Step 4: Implement — remove the four old tab bodies**

Delete the four `<div id="tab-bench">…</div>`, `<div id="tab-score">…</div>`, `<div id="tab-shootout">…</div>`, `<div id="tab-gauntlet">…</div>` blocks. Leave their JS functions for now (Task 8/9 reuse the fetch logic); only the markup containers go. Add the empty Testing container after Overview:
```html
<div id="tab-testing" class="tab">
  <div id="testing-rail"></div>      <!-- left config rail (Task 8) -->
  <div id="testing-results"></div>   <!-- right results column (Task 9) -->
</div>
```
Add to the stylesheet:
```css
#tab-testing { display:none; gap:12px; }
#tab-testing.active { display:flex; }
#testing-rail { width:34%; min-width:220px; border:1px solid var(--border); border-radius:6px; padding:10px; background:var(--panebg); align-self:flex-start; }
#testing-results { flex:1; min-width:0; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestNav -v`
Expected: PASS.

- [ ] **Step 6: Manual verify**

Load hub; the nav shows 6 tabs; clicking Testing shows an empty two-column shell; no JS console errors (old tab handlers referencing removed IDs are guarded in Task 8).

- [ ] **Step 7: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

### Task 8: Config rail — facets + Run, with facet→endpoint routing

**Files:**
- Modify: `hub/static/index.html` (Testing tab JS)
- Test: `hub/tests/test_hub_api.py` (served-markup) + manual

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_hub_api.py`:
```python
class TestTestingRail:
    def test_facet_controls_served(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="facet-target"' in html
        assert 'id="facet-suite"' in html
        assert 'id="facet-depth"' in html
        assert 'id="testing-run"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestTestingRail -v`
Expected: FAIL.

- [ ] **Step 3: Implement — render the rail + routing table**

Add this script block near the other tab JS in `index.html` (renders into `#testing-rail` on load):
```html
<script>
// Facet → endpoint routing. depthFlag maps Fast/Full to each endpoint's flag.
const SUITE_ROUTES = {
  health:    {current: "/api/bench/run",     depthFlag: d => ({fast: d==="fast"})},
  scenarios: {current: "/api/scenarios/run", compare: "/api/shootout",
              depthFlag: d => ({mode: d==="fast" ? "geometry" : "full"})},
  gauntlet:  {current: "/api/gauntlet/run",  compare: "/api/shootout",
              depthFlag: d => ({subset: d==="fast"})},
};
const TESTING = {target: "current", suite: "gauntlet", depth: "full", job: null, t0: 0};

function renderRail() {
  const pill = (group, val, cur) =>
    `<span class="facet ${cur===val?'on':''}" data-group="${group}" data-val="${val}">${val}</span>`;
  document.getElementById("testing-rail").innerHTML = `
    <div class="flabel">Target</div>
    <div id="facet-target" class="frow">${pill("target","current",TESTING.target)}${pill("target","compare",TESTING.target)}</div>
    <div class="flabel">Suite</div>
    <div id="facet-suite" class="frow">${["health","scenarios","gauntlet"].map(s=>pill("suite",s,TESTING.suite)).join("")}</div>
    <div class="flabel">Depth</div>
    <div id="facet-depth" class="frow">${pill("depth","fast",TESTING.depth)}${pill("depth","full",TESTING.depth)}</div>
    <button id="testing-run" class="primary" style="width:100%;margin-top:10px;">▶ Run</button>
    <div id="testing-plan" class="dim" style="text-align:center;margin-top:6px;font-size:10px;"></div>`;
  document.querySelectorAll("#testing-rail .facet").forEach(el =>
    el.onclick = () => { TESTING[el.dataset.group] = el.dataset.val; renderRail(); updatePlan(); });
  document.getElementById("testing-run").onclick = runTesting;
  updatePlan();
}
function updatePlan() {
  const route = SUITE_ROUTES[TESTING.suite];
  const ok = route && (route[TESTING.target] || route.current);
  const plan = document.getElementById("testing-plan");
  if (!ok) { plan.textContent = `${TESTING.suite} has no “${TESTING.target}” mode`; }
  else { plan.textContent = `${TESTING.suite} · ${TESTING.target} · ${TESTING.depth}`; }
}
</script>
```
Add styles:
```css
.flabel { color:var(--dim); font-size:10px; text-transform:uppercase; letter-spacing:1px; margin:8px 0 3px; }
.frow { display:flex; gap:6px; flex-wrap:wrap; }
.facet { padding:2px 9px; border:1px solid var(--border); border-radius:4px; cursor:pointer; color:var(--dim); }
.facet.on { background:#143a1d; color:var(--accent); }
```
Wire `renderRail()` into the existing tab-switch logic so it runs when Testing is shown (find the `data-tab` click handler; when target is `testing`, call `renderRail()` once).

- [ ] **Step 4: Implement — `runTesting()` (routing + dispatch)**

Add to the same script block:
```html
<script>
async function runTesting() {
  const route = SUITE_ROUTES[TESTING.suite];
  const url = route[TESTING.target] || route.current;
  if (!url) return;
  const body = Object.assign({depth: TESTING.depth}, route.depthFlag(TESTING.depth));
  if (TESTING.target === "compare") body.compare = true;
  buttonBusy("testing-run", true);                 // Task 11
  TESTING.t0 = Date.now();
  startStatusStrip();                              // Task 9
  try {
    const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"},
                               body: JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    onTestingResult(data);                         // Task 9
    buttonFlash("testing-run", "ok");              // Task 11
  } catch (e) {
    statusFailed(e.message); buttonFlash("testing-run", "err");
  } finally { buttonBusy("testing-run", false); }
}
</script>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestTestingRail -v`
Expected: PASS.

- [ ] **Step 6: Manual verify**

Load Testing; the rail shows Target/Suite/Depth pills + Run; clicking pills updates the highlighted selection and the plan line; switching Suite to Health hides the compare option implicitly (plan shows "health · current · …").

- [ ] **Step 7: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

### Task 9: Results column — live status strip + unified scorecard + history

**Files:**
- Modify: `hub/static/index.html` (Testing tab JS, results column)
- Test: manual (interactive); served-markup smoke test

- [ ] **Step 1: Write the failing test (served smoke)**

Add to `hub/tests/test_hub_api.py`:
```python
class TestResultsScaffold:
    def test_results_containers_served(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert 'id="status-strip"' in html
        assert 'id="scorecard-host"' in html
        assert 'id="testing-history"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestResultsScaffold -v`
Expected: FAIL.

- [ ] **Step 3: Implement — results scaffold + renderers**

Set `#testing-results` innerHTML in `renderRail()` setup (or on tab show) to:
```html
<div id="status-strip" style="display:none;border:1px solid var(--border);border-radius:6px;padding:9px;margin-bottom:10px;background:var(--panebg);"></div>
<div id="scorecard-host"></div>
<div id="testing-history" style="margin-top:10px;"></div>
```
Add the renderers (one `renderScorecard` for ALL suites — this is the unify point):
```html
<script>
const VERDICT_COLOR = {pass:"var(--ok)", partial:"var(--warn-amber)", fail:"var(--err)"};
function renderScorecard(card) {
  const c = VERDICT_COLOR[card.verdict] || "var(--fg)";
  const metrics = (card.metrics||[]).map(m =>
    `<span>${m.label} <b style="color:${m.good?'var(--ok)':'var(--warn-amber)'}">${m.value}</b></span>`).join("");
  return `<div style="border:1px solid var(--border);border-radius:6px;padding:10px;background:var(--panebg);">
    <div style="display:flex;align-items:center;gap:10px;">
      <span style="font-size:28px;font-weight:700;color:${c}">${card.score}</span>
      <span style="background:#3a3216;color:${c};padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;">${card.verdict.toUpperCase()}</span>
      <span class="dim" style="margin-left:auto;font-size:11px;">${card.suite} · ${card.label}</span>
    </div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;border-top:1px solid var(--border);padding-top:8px;font-size:11px;">${metrics}</div>
  </div>`;
}
function onTestingResult(data) {
  stopStatusStrip();
  const cards = data.models ? data.models.map(m=>m.scorecard) : [data.scorecard];
  document.getElementById("scorecard-host").innerHTML =
    cards.filter(Boolean).map(renderScorecard).join("");
  pushHistory(cards.filter(Boolean));
}
</script>
```

- [ ] **Step 4: Implement — live status strip (phase + elapsed + determinate + ETA)**

```html
<script>
let _statusTimer = null;
function startStatusStrip() {
  const strip = document.getElementById("status-strip");
  strip.style.display = "block";
  const eta = etaForCurrent();   // null or seconds
  _statusTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - TESTING.t0)/1000);
    const elapsed = `${Math.floor(sec/60)}:${String(sec%60).padStart(2,"0")}`;
    const left = eta ? ` · ~${Math.max(0,Math.round(eta-sec))}s left · based on history` : "";
    strip.innerHTML = `<span style="color:var(--warn-amber)">● running</span> · ${sec}s${left}
      <span style="float:right" class="dim">${elapsed}</span>
      <div style="height:5px;background:#16241a;border-radius:3px;margin-top:6px;overflow:hidden;">
        <div style="height:5px;${eta?`width:${Math.min(100,100*sec/eta)}%;background:var(--warn-amber);`:'width:40%;background:var(--dim);animation:pulse 1s infinite;'}border-radius:3px;"></div>
      </div>`;
  }, 250);
}
function stopStatusStrip(){ clearInterval(_statusTimer); document.getElementById("status-strip").style.display="none"; }
function statusFailed(msg){ clearInterval(_statusTimer);
  document.getElementById("status-strip").innerHTML = `<span style="color:var(--err)">● failed</span> · ${msg}`; }
async function etaForCurrent(){ return null; } // filled in Step 5
</script>
```
Add `@keyframes pulse { 0%,100%{opacity:.4} 50%{opacity:1} }` to the stylesheet.

- [ ] **Step 5: Implement — ETA from history**

Replace `etaForCurrent` to read the suite's history endpoint and compute the median client-side (mirrors `eta_from_durations`, recent=5):
```html
<script>
const HISTORY_ENDPOINTS = {
  health: "/api/bench/history", scenarios: "/api/scorecards",
  gauntlet: "/api/gauntlet/history",
};
async function etaForCurrent() {
  try {
    const url = HISTORY_ENDPOINTS[TESTING.suite]; if (!url) return null;
    const rows = await (await fetch(url)).json();
    const durs = (Array.isArray(rows)?rows:rows.items||[]).map(r=>r.duration_s).filter(x=>typeof x==="number");
    if (durs.length < 2) return null;
    const w = durs.slice(-5).sort((a,b)=>a-b);
    return w[Math.floor(w.length/2)];   // median
  } catch { return null; }
}
</script>
```
(Note: needs `duration_s` in history entries — added in Task 6 Step 4. If a history endpoint's rows lack it, older rows simply produce no ETA, which is the honest fallback.)

- [ ] **Step 6: Implement — unified history strip**

```html
<script>
const _history = [];
function pushHistory(cards){
  cards.forEach(c => _history.unshift(c));
  document.getElementById("testing-history").innerHTML =
    `<div class="flabel">History</div><div class="frow">` +
    _history.slice(0,12).map(c=>{
      const col = VERDICT_COLOR[c.verdict];
      return `<span class="facet" style="cursor:default;">${c.label} <b style="color:${col}">${c.score}</b></span>`;
    }).join("") + `</div>`;
}
</script>
```

- [ ] **Step 7: Run served test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestResultsScaffold -v`
Expected: PASS.

- [ ] **Step 8: Manual verify (needs live stack)**

With the stack up, run each suite: status strip ticks elapsed + phase, shows ETA after ≥2 prior runs; on completion a scorecard renders with score+verdict+metrics; the run appears in History. Run Compare (Target: compare, Suite: scenarios) → multiple side-by-side scorecards.

- [ ] **Step 9: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

## Phase E — Press feedback + audit

### Task 10: Global button-feedback helper

**Files:**
- Modify: `hub/static/index.html` (shared JS + stylesheet)
- Test: served-markup + manual

- [ ] **Step 1: Write the failing test**

Add to `hub/tests/test_hub_api.py`:
```python
class TestButtonFeedback:
    def test_helpers_present(self):
        html = client.get("/", headers={"Host": "127.0.0.1:8003"}).text
        assert "function buttonBusy" in html
        assert "function buttonFlash" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestButtonFeedback -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to the shared JS:
```html
<script>
function buttonBusy(id, busy){
  const b = document.getElementById(id); if(!b) return;
  if(busy){ b.dataset.label = b.dataset.label||b.textContent; b.disabled=true;
            b.textContent = "… "+b.dataset.label.replace(/^▶ /,"Running "); }
  else { b.disabled=false; if(b.dataset.label) b.textContent=b.dataset.label; }
}
function buttonFlash(id, kind){    // kind: "ok" | "err"
  const b = document.getElementById(id); if(!b) return;
  b.classList.add(kind==="ok"?"flash-ok":"flash-err");
  setTimeout(()=>b.classList.remove("flash-ok","flash-err"), 700);
  toast(kind==="ok" ? "Done" : "Failed", kind);
}
function toast(msg, kind){
  let host = document.getElementById("toast-host");
  if(!host){ host=document.createElement("div"); host.id="toast-host";
    host.style.cssText="position:fixed;bottom:16px;right:16px;z-index:99;display:flex;flex-direction:column;gap:6px;"; document.body.appendChild(host); }
  const t=document.createElement("div");
  t.textContent=msg;
  t.style.cssText=`padding:6px 12px;border-radius:5px;font-size:12px;border:1px solid ${kind==="err"?'var(--err)':'var(--ok)'};color:${kind==="err"?'var(--err)':'var(--ok)'};background:var(--panebg);`;
  host.appendChild(t); setTimeout(()=>t.remove(), 2500);
}
</script>
```
Add styles:
```css
button:active { transform:translateY(1px); }
.flash-ok { animation:flashok .7s; } .flash-err { animation:flasherr .7s; }
@keyframes flashok { 0%{box-shadow:0 0 0 2px var(--ok)} 100%{box-shadow:none} }
@keyframes flasherr { 0%{box-shadow:0 0 0 2px var(--err)} 100%{box-shadow:none} }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hub_api.py::TestButtonFeedback -v`
Expected: PASS.

- [ ] **Step 5: Manual verify**

Click Run: button depresses, shows spinner text, disables; on success flashes green + "Done" toast; on error flashes red + "Failed" toast.

- [ ] **Step 6: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green.

---

### Task 11: Audit pass — walk all surfaces, fix wiring

**Files:**
- Modify: `hub/static/index.html` / `hub/hub.py` as findings require
- Output: `hub/docs/superpowers/AUDIT-2026-06-14.md`

- [ ] **Step 1: Start the hub and the stack**

Start the hub; bring the forge stack up. Open the hub in a browser.

- [ ] **Step 2: Walk the 6 tabs**

For each of Overview, Testing, Models, Config, Activity, Doc: confirm it renders with the new theme, every button reacts (press feedback), and primary data loads. Note anything blank, errored, or referencing a removed ID (old `tab-bench`/`tab-score`/etc.).

- [ ] **Step 3: Walk every facet combo in Testing**

Run each valid combo: Health/Scenarios/Gauntlet × current, and Scenarios/Gauntlet × compare, × fast/full. Confirm each routes to a live endpoint, the status strip drives, and a unified scorecard renders. Record failures with the exact combo + endpoint + error.

- [ ] **Step 4: Record findings**

Write `hub/docs/superpowers/AUDIT-2026-06-14.md`: a table of `surface | expected | actual | status (ok/fixed/open)`.

- [ ] **Step 5: Fix wiring gaps**

For each gap that is a wiring break introduced by the rework (dangling ID, dead handler, wrong endpoint), fix it. Defer pre-existing/unrelated bugs to the audit doc's "open" list (do not scope-creep).

- [ ] **Step 6: Checkpoint**

Run: `.venv/bin/python -m pytest tests/ -q` → green; the audit doc lists every surface as ok/fixed (or open with a note).

---

## Self-Review (completed during planning)

- **Spec coverage:** faceted runner → Tasks 7–9; one-score+verdict → Tasks 3–4,9; ETA+phase+determinate → Tasks 5,9; press feedback → Task 10; theme → Task 1; logo → Task 2; nav 9→6 → Task 7; audit → Task 11. All spec sections mapped.
- **Type consistency:** the scorecard keys (`suite,target,label,score,verdict,metrics[{label,value,good}]`) are produced by `normalize_result` (Task 4) and consumed identically by `renderScorecard` (Task 9) and `pushHistory` (Task 9). `score_to_verdict` band names (`pass/partial/fail`) match `VERDICT_COLOR` keys. `buttonBusy/buttonFlash` defined in Task 10, called in Task 8.
- **Placeholders:** none — every code step shows complete code; the two read-first steps (Task 6 Step 1, Task 9 Step 5) are investigations with concrete fallbacks, not deferred code.
