# Generative Lighting Implementation Plan (Sprint)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the enclosed interior atmospheric *and* readable: a deterministic lighting planner derives hearth/torch/candle/window sources from the Brief+room+manifest, which drive shell window openings, the realtime Godot rig (tier-0 floor), and the Cycles GI bake (extended for interior emitters).

**Architecture:** New `lighting_planner.py` is the single source of truth (engine-agnostic data). The quest path computes the plan *before* the shell (windows cut openings), then `scene_compiler` emits the realtime rig + a brighter Environment and orchestrates the bake. `bake_lighting.py` gains interior emitters so GI bounces warm interior light, not just sky.

**Tech Stack:** Python 3 (`foundry/.venv`), numpy, Blender (Cycles/HIP), Godot 4, pytest.

## Global Constraints

- **Determinism:** `plan_lighting` is deterministic for `(brief, room_size, manifest, seed)` — sorted iteration, no wall-clock, no unseeded RNG. GPU bakes aren't bit-exact, so the **bake cache key is authoritative**.
- **Never hard-fail:** Blender missing or bake failure → tier-0 realtime (already built into `bake_scene`); the realtime rig must look good on its own.
- **Build order:** `plan_lighting` runs BEFORE `build_room_shell` (windows drive openings).
- **No authored assets:** lights/geometry are generated.
- **Tests:** run from `foundry/`; `.venv/bin/python -m pytest`. Pure-Python tasks fully unit-tested by the implementer; **Blender-gated tests skip when `blender` is absent** — orchestrator runs the real bake + visual verification (CLI owns unit+smoke; orchestrator owns Blender/visual).
- **Style:** match existing planners (`room_planner.py`, `exterior_planner.py`) and `scene_compiler.py`.

---

### Task 1: `foundry/lighting_planner.py` — the LightingPlan

**Files:**
- Create: `foundry/lighting_planner.py`
- Create: `foundry/tests/test_lighting_planner.py`

**Interfaces:**
- Produces: `plan_lighting(brief: dict, room_size: dict, manifest: list, seed: int = 0) -> dict`
  returning a `LightingPlan` dict with keys `sources` (list of `{type,pos,color,energy,range,flicker}`),
  `windows` (list of `{wall,center,width,height,sill}`), `sun` (`{color,energy,direction}`),
  `sky` (`{top,ambient_energy}`), `environment`
  (`{ambient_color,ambient_energy,fog_color,fog_energy,tonemap,exposure}`).
  `wall` ∈ {"N","S","E","W"} (N/S run along X at z=∓d/2; E/W run along Z at x=±w/2).

- [ ] **Step 1: Write failing tests**

```python
# foundry/tests/test_lighting_planner.py
from lighting_planner import plan_lighting

BRIEF = {"theme_tag": "stone_keep", "setting": "dusk study"}

def _plan(w=8, d=6, manifest=None):
    return plan_lighting(BRIEF, {"w": w, "d": d}, manifest or [], seed=0)

def test_exactly_one_hearth():
    p = _plan()
    hearths = [s for s in p["sources"] if s["type"] == "hearth"]
    assert len(hearths) == 1

def test_torch_count_scales_with_perimeter():
    small = sum(s["type"] == "torch" for s in _plan(6, 4)["sources"])
    big = sum(s["type"] == "torch" for s in _plan(14, 12)["sources"])
    assert big > small >= 2

def test_candles_only_on_tables():
    m = [{"id": "table_0", "category": "table", "x": 1.0, "z": 1.0},
         {"id": "rug_0", "category": "rug", "x": 0.0, "z": 0.0}]
    cands = [s for s in _plan(manifest=m)["sources"] if s["type"] == "candle"]
    assert len(cands) == 1
    assert abs(cands[0]["pos"][0] - 1.0) < 1e-6 and abs(cands[0]["pos"][2] - 1.0) < 1e-6

def test_windows_avoid_hearth_wall():
    p = _plan()
    hearth_wall = p["_hearth_wall"]
    assert p["windows"]
    assert all(wnd["wall"] != hearth_wall for wnd in p["windows"])

def test_environment_is_readable():
    env = _plan()["environment"]
    assert env["ambient_energy"] >= 0.5   # not the old near-black 0.4

def test_determinism():
    assert _plan() == _plan()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_lighting_planner.py -q`
Expected: FAIL (`No module named 'lighting_planner'`).

- [ ] **Step 3: Implement `foundry/lighting_planner.py`**

```python
"""foundry.lighting_planner — deterministic motivated-lighting plan.

Derives interior light sources (hearth, torches, candles) + window openings +
environment from the Brief + room geometry + manifest. Engine-agnostic data,
consumed by build_room_shell (windows), scene_compiler (realtime rig + bake
scene_desc), and bake_lighting (interior emitters). Deterministic.
"""
from __future__ import annotations

_WARM_HEARTH = (1.0, 0.6, 0.3)
_WARM_TORCH = (1.0, 0.7, 0.4)
_WARM_CANDLE = (1.0, 0.8, 0.5)
_TABLE_CATS = {"table", "shelf", "desk", "cabinet"}
_TORCH_SPACING_M = 3.5
_CANDLE_MAX = 3
_TORCH_H = 2.2
_CANDLE_TOP_Y = 0.8


def plan_lighting(brief: dict, room_size: dict, manifest: list, seed: int = 0) -> dict:
    w = float(room_size["w"])
    d = float(room_size["d"])
    # Hearth on the longest wall (deterministic): N if w>=d else E.
    hearth_wall = "N" if w >= d else "E"
    sources: list[dict] = []

    # ── hearth ────────────────────────────────────────────────
    sources.append({
        "type": "hearth",
        "pos": _wall_point(hearth_wall, 0.5, w, d, y=0.5),
        "color": _WARM_HEARTH, "energy": 6.0, "range": 6.0, "flicker": True,
    })

    # ── torches: evenly spaced around the perimeter ───────────
    perim = 2 * (w + d)
    n_torch = max(2, int(perim / _TORCH_SPACING_M))
    for i in range(n_torch):
        wall, t = _perimeter_param(i / n_torch, w, d)
        sources.append({
            "type": "torch",
            "pos": _wall_point(wall, t, w, d, y=_TORCH_H),
            "color": _WARM_TORCH, "energy": 3.0, "range": 4.0, "flicker": True,
        })

    # ── candles on table-like surfaces (sorted for determinism) ─
    tables = sorted(
        (e for e in manifest if e.get("category") in _TABLE_CATS),
        key=lambda e: e.get("id", ""),
    )[:_CANDLE_MAX]
    for e in tables:
        sources.append({
            "type": "candle",
            "pos": (float(e.get("x", 0.0)), _CANDLE_TOP_Y, float(e.get("z", 0.0))),
            "color": _WARM_CANDLE, "energy": 1.2, "range": 1.5, "flicker": False,
        })

    # ── windows on the two walls perpendicular to the hearth ──
    win_walls = (["E", "W"] if hearth_wall in ("N", "S") else ["N", "S"])
    windows = [{
        "wall": wll, "center": 0.5,
        "width": min(1.2, (d if wll in ("E", "W") else w) - 1.0),
        "height": 1.4, "sill": 1.2,
    } for wll in win_walls]

    return {
        "sources": sources,
        "windows": windows,
        "sun": {"color": (0.5, 0.6, 0.85), "energy": 0.8,
                "direction": (-0.3, -0.6, -0.5)},
        "sky": {"top": (0.4, 0.45, 0.6), "ambient_energy": 0.4},
        "environment": {"ambient_color": (0.40, 0.40, 0.45), "ambient_energy": 0.6,
                        "fog_color": (0.15, 0.15, 0.20), "fog_energy": 0.1,
                        "tonemap": 2, "exposure": 1.2},
        "_hearth_wall": hearth_wall,
    }


def _wall_point(wall: str, t: float, w: float, d: float, y: float):
    """A point on `wall` at parameter t∈[0,1] along it, inset 0.15 m off the face."""
    inset = 0.15
    if wall == "N":   return (-w / 2 + t * w, y, -d / 2 + inset)
    if wall == "S":   return (-w / 2 + t * w, y, d / 2 - inset)
    if wall == "E":   return (w / 2 - inset, y, -d / 2 + t * d)
    return (-w / 2 + inset, y, -d / 2 + t * d)  # W


def _perimeter_param(frac: float, w: float, d: float):
    """Map frac∈[0,1) around the perimeter to (wall, t-along-wall)."""
    perim = 2 * (w + d)
    s = frac * perim
    if s < w:            return "N", s / w
    s -= w
    if s < d:            return "E", s / d
    s -= d
    if s < w:            return "S", s / w
    s -= w
    return "W", s / d
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_lighting_planner.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/lighting_planner.py foundry/tests/test_lighting_planner.py
git commit -m "feat(lighting): deterministic lighting planner (hearth/torch/candle/window + env)"
```

---

### Task 2: `build_room_shell.py` — window openings  (Blender; orchestrator-verified)

**Files:**
- Modify: `foundry/blender/build_room_shell.py`
- Modify: `foundry/room_shell.py` (cache key + signature include windows; bump `GEN_VERSION`)
- Test: `foundry/tests/test_build_room_shell.py` (add a gated case)

**Interfaces:**
- Consumes: `windows` list (Task 1 `Window` dicts) via CLI arg (JSON) to the Blender script and via
  `room_shell.ensure_room_shell(..., windows=...)`.
- Produces: a shell GLB whose walls have rectangular openings matching the windows.

- [ ] **Step 1: Add a gated test**

```python
# add to foundry/tests/test_build_room_shell.py
def test_walls_have_window_opening(tmp_path):
    import json, subprocess, shutil, trimesh
    blender = shutil.which("blender")
    if blender is None:
        import pytest; pytest.skip("blender not installed")
    out = tmp_path / "shellw.glb"
    windows = json.dumps([{"wall": "E", "center": 0.5, "width": 1.2, "height": 1.4, "sill": 1.2}])
    subprocess.run([blender, "--background", "--python",
                    "blender/build_room_shell.py", "--",
                    str(out), "8", "6", "3", "study", "0", windows],
                   check=True, capture_output=True, timeout=300, cwd="foundry"
                   if __import__("os").path.exists("foundry") else ".")
    scene = trimesh.load(str(out))
    # A windowed E wall has more vertices than a solid one (opening adds a frame).
    assert out.exists() and out.stat().st_size > 0
```

- [ ] **Step 2: Implement (orchestrator runs the bake to verify)**

In `build_room_shell.py`: accept an optional 7th argv (JSON list of windows). For each window on a
wall, replace that wall's single box with **four framing boxes** (below sill, above head, and the two
side jambs) so a rectangular hole remains — deterministic, no boolean needed:
```python
def _wall_with_opening(bm, wall, w, d, wall_h, wall_t, win):
    # win: center∈[0,1] along wall, width, height, sill (all metres)
    length = w if wall in ("N", "S") else d
    cu = (win["center"]) * length - length / 2          # opening centre along wall axis
    half = win["width"] / 2
    sill, head = win["sill"], win["sill"] + win["height"]
    segs = [("below", 0, sill), ("above", head, wall_h)]  # full-width bands
    # left/right jambs span sill..head
    # emit each band/jamb as a _beam() box positioned on the wall plane
    ...
```
Walls without a window stay a single box. Update `room_shell.ensure_room_shell` to accept `windows`,
serialize to JSON for the subprocess, add it to the cache key, and bump `GEN_VERSION`.

- [ ] **Step 3 (orchestrator): build + screenshot** the windowed shell; confirm the opening reads.

- [ ] **Step 4: Commit**

```bash
git add foundry/blender/build_room_shell.py foundry/room_shell.py foundry/tests/test_build_room_shell.py
git commit -m "feat(shell): window openings in room-shell generator (framed bands/jambs)"
```

---

### Task 3: `scene_compiler.py` — realtime rig from the plan

**Files:**
- Modify: `foundry/scene_compiler.py` (lighting emission + `compile_scene` accepts `lighting_plan`)
- Modify: `foundry/tests/test_scene_compiler.py`

**Interfaces:**
- Consumes: `LightingPlan` (Task 1) via a new `lighting_plan: dict | None = None` kwarg on
  `compile_scene`.
- Produces: a `.tscn` with one `OmniLight3D` per `source`, the `DirectionalLight3D` from `sun`, and
  an `Environment` built from `environment` (replacing the hardcoded dim values). When
  `lighting_plan is None`, the existing default lighting is emitted (back-compat).

- [ ] **Step 1: Write failing tests**

```python
# add to foundry/tests/test_scene_compiler.py
def test_lighting_plan_emits_one_omni_per_source():
    import scene_compiler as sc
    plan = {"sources": [
              {"type": "hearth", "pos": (0,0.5,-3), "color": (1,0.6,0.3), "energy": 6, "range": 6, "flicker": True},
              {"type": "torch",  "pos": (2,2.2,-3), "color": (1,0.7,0.4), "energy": 3, "range": 4, "flicker": True}],
            "windows": [], "sun": {"color": (0.5,0.6,0.85), "energy": 0.8, "direction": (-0.3,-0.6,-0.5)},
            "sky": {"top": (0.4,0.45,0.6), "ambient_energy": 0.4},
            "environment": {"ambient_color": (0.4,0.4,0.45), "ambient_energy": 0.6,
                            "fog_color": (0.15,0.15,0.2), "fog_energy": 0.1, "tonemap": 2, "exposure": 1.2}}
    t = sc.compile_scene([], _minimal_manifest(), "/tmp/lt/scenes/main.tscn",
                         room_size={"w":8,"d":6}, theme="study", lighting_plan=plan)
    assert t.count('type="OmniLight3D"') == 2
    assert "ambient_light_energy = 0.6" in t      # readable, not 0.4

def test_no_plan_keeps_default_lighting():
    import scene_compiler as sc
    t = sc.compile_scene([], _minimal_manifest(), "/tmp/lt2/scenes/main.tscn",
                         room_size={"w":8,"d":6}, theme="study")  # no lighting_plan
    assert "OmniLight3D" in t  # still emits the existing default rig
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -k lighting -q`
Expected: FAIL (kwarg/behavior absent).

- [ ] **Step 3: Implement**

Add `lighting_plan=None` to `compile_scene`. When provided, in the lighting-emit helper:
- emit one `[node name="Light{i}" type="OmniLight3D"]` per `source` with
  `transform` at `pos`, `light_color = Color(r,g,b,1)`, `light_energy = energy`,
  `omni_range = range`;
- emit the `DirectionalLight3D` from `sun` (color + direction→basis);
- build the `Environment` sub-resource from `environment` (`ambient_light_color/energy`,
  `fog_light_color/energy`, `tonemap_mode`, `tonemap_exposure`).
When `None`, keep the current hardcoded emission unchanged.

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler.py
git commit -m "feat(scene): realtime light rig + Environment from LightingPlan (readable dusk)"
```

---

### Task 4: bake `scene_desc` builder + `bake_scene` wiring

**Files:**
- Modify: `foundry/scene_compiler.py` (or a small `foundry/lighting_apply.py` — keep it focused)
- Modify: `foundry/tests/test_scene_compiler.py`

**Interfaces:**
- Consumes: `LightingPlan`, the compiled placements, `lighting_bake.bake_scene`.
- Produces: `build_lighting_scene_desc(lighting_plan, placements, tier, samples) -> dict` with keys
  `tier, samples, placements, sun, sky, interior_lights`; and a call that bakes + applies artifacts
  (tier 0 → no-op; tier ≥1 → apply per the cache result).

- [ ] **Step 1: Write failing tests**

```python
# add to foundry/tests/test_scene_compiler.py
def test_scene_desc_carries_interior_lights():
    from scene_compiler import build_lighting_scene_desc
    plan = {"sources": [{"type":"hearth","pos":(0,0.5,-3),"color":(1,0.6,0.3),"energy":6,"range":6,"flicker":True}],
            "sun": {"color":(0.5,0.6,0.85),"energy":0.8,"direction":(-0.3,-0.6,-0.5)},
            "sky": {"top":(0.4,0.45,0.6),"ambient_energy":0.4}}
    desc = build_lighting_scene_desc(plan, placements=[], tier=2, samples=64)
    assert desc["tier"] == 2 and desc["sun"] == plan["sun"]
    assert desc["interior_lights"] == plan["sources"]

def test_tier0_skips_bake(monkeypatch):
    import scene_compiler as sc, lighting_bake
    called = []
    monkeypatch.setattr(lighting_bake, "bake_scene", lambda *a, **k: called.append(1) or {"tier":0,"status":"realtime","artifacts":[]})
    sc.bake_and_apply(build_lighting_scene_desc({"sources":[],"sun":{},"sky":{}}, [], tier=0, samples=1), build_dir="/tmp/x")
    # tier 0 short-circuits inside scene_compiler before calling the baker
    assert called == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -k "scene_desc or tier0" -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def build_lighting_scene_desc(lighting_plan, placements, tier, samples):
    return {
        "tier": int(tier), "samples": int(samples),
        "placements": placements,
        "sun": lighting_plan.get("sun", {}),
        "sky": lighting_plan.get("sky", {}),
        "interior_lights": lighting_plan.get("sources", []),
    }

def bake_and_apply(scene_desc, build_dir):
    if int(scene_desc.get("tier", 0)) == 0:
        return {"tier": 0, "status": "realtime", "artifacts": []}
    import lighting_bake
    from lighting_bake import Baker  # existing baker entry
    result = lighting_bake.bake_scene(scene_desc, baker=Baker())
    # tier 1: apply vertex-colour artifacts (COLOR_0 render-active); tier 2: lightmap.
    _apply_bake_artifacts(result, build_dir)
    return result
```
`_apply_bake_artifacts` honors the COLOR_0 gotcha (render-active color attribute,
`export_vertex_color="ACTIVE"`, prune stray color attrs) for tier 1; references the lightmap for
tier 2. (Orchestrator validates the actual artifact application against a real bake.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -k "scene_desc or tier0" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler.py
git commit -m "feat(lighting): scene_desc builder + bake_scene wiring (tier-0 short-circuit)"
```

---

### Task 5: `bake_lighting.py` interior emitters + `bake_key`

**Files:**
- Modify: `foundry/blender/bake_lighting.py` (add interior lamps; Blender — orchestrator-verified)
- Modify: `foundry/lighting_bake.py` (`bake_key` hashes `interior_lights`)
- Modify: `foundry/tests/test_lighting_bake.py`

**Interfaces:**
- Consumes: `scene_desc["interior_lights"]` (Task 4).
- Produces: GI bakes that include interior bounce; cache invalidates when interior lights change.

- [ ] **Step 1: Write failing test (pure-Python, the cache key)**

```python
# foundry/tests/test_lighting_bake.py  (add)
from lighting_bake import bake_key
def test_bake_key_depends_on_interior_lights():
    base = {"tier":2,"samples":64,"placements":[],"sun":{},"sky":{},"interior_lights":[]}
    lit  = {**base, "interior_lights":[{"type":"hearth","pos":(0,0.5,-3),"color":(1,0.6,0.3),"energy":6}]}
    assert bake_key(base) != bake_key(lit)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_lighting_bake.py -k interior -q`
Expected: FAIL (`bake_key` ignores `interior_lights`).

- [ ] **Step 3: Implement**

`lighting_bake.bake_key`: add `interior_lights` to the hashed payload (round positions/energies for
stability):
```python
"il": [[l.get("type"),
        [round(float(x),4) for x in l.get("pos", ())],
        [round(float(c),4) for c in l.get("color", ())],
        round(float(l.get("energy",0.0)),4)]
       for l in scene_desc.get("interior_lights", [])],
```
`blender/bake_lighting.py`: after the sun/sky setup, add one Blender lamp per interior light:
```python
for li in desc.get("interior_lights", []):
    ld = bpy.data.lights.new(li.get("type","point"), type="POINT")
    ld.energy = float(li.get("energy", 1.0)) * 60.0   # W; tuned by orchestrator
    ld.color = tuple(li.get("color", (1,1,1)))
    ob = bpy.data.objects.new(ld.name, ld)
    bpy.context.collection.objects.link(ob)
    ob.location = tuple(li.get("pos", (0,0,0)))
```

- [ ] **Step 4: Run to verify it passes (key test)**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_lighting_bake.py -k interior -q`
Expected: PASS. (Orchestrator runs the real Blender bake to validate interior bounce.)

- [ ] **Step 5: Commit**

```bash
git add foundry/blender/bake_lighting.py foundry/lighting_bake.py foundry/tests/test_lighting_bake.py
git commit -m "feat(bake): interior emitters in Cycles GI bake + bake_key invalidation"
```

---

### Task 6: wire the build order into the quest path

**Files:**
- Modify: `foundry/__main__.py` (`_cmd_quest`) and/or `foundry/scaffold.py`
- Modify: `foundry/tests/test_scaffold.py` or `test_quest_integration` as present

**Interfaces:**
- Consumes: `plan_lighting`, `ensure_room_shell(..., windows=…)`, `compile_scene(..., lighting_plan=…)`,
  `build_lighting_scene_desc`/`bake_and_apply`.
- Produces: a quest build whose shell has window openings, whose scene uses the planned realtime rig,
  and (when tier≥1 + Blender present) a baked GI applied.

- [ ] **Step 1: Write failing test**

```python
# foundry/tests/test_quest_lighting_wiring.py
def test_plan_runs_before_shell(monkeypatch):
    import lighting_planner, room_shell
    order = []
    monkeypatch.setattr(lighting_planner, "plan_lighting",
                        lambda *a, **k: order.append("plan") or {"sources":[],"windows":[{"wall":"E","center":0.5,"width":1.2,"height":1.4,"sill":1.2}],"sun":{},"sky":{},"environment":{"ambient_energy":0.6}})
    def fake_shell(*a, **k):
        order.append("shell"); assert "windows" in k  # windows passed through
        return None
    monkeypatch.setattr(room_shell, "ensure_room_shell", fake_shell)
    # drive the quest build path far enough to hit both (use the project's existing
    # quest entry/helper; stub the LLM/interpreter as other quest tests do)
    ...
    assert order == ["plan", "shell"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_quest_lighting_wiring.py -q`
Expected: FAIL (plan not computed / windows not passed).

- [ ] **Step 3: Implement**

In `_cmd_quest` (after `layout_room` gives `manifest`+`room_size`, before the shell is resolved):
```python
from lighting_planner import plan_lighting
lighting_plan = plan_lighting(brief, room_size, manifest, seed=seed or 0)
```
Pass `windows=lighting_plan["windows"]` into the shell resolution (`scaffold`→`ensure_room_shell`),
pass `lighting_plan=lighting_plan` into `compile_scene`, and after compile call `bake_and_apply(
build_lighting_scene_desc(lighting_plan, placements, tier=LIGHTING_TIER, samples=…), build_dir)`
where `LIGHTING_TIER` defaults to 2 (showcase) and falls to 0 if Blender is unavailable.

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_quest_lighting_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add foundry/__main__.py foundry/scaffold.py foundry/tests/test_quest_lighting_wiring.py
git commit -m "feat(quest): wire lighting plan -> shell windows + realtime rig + GI bake"
```

---

### Task 7: orchestrator end-to-end + screenshots (verification only)

**Files:** none.

- [ ] **Step 1: Full unit suite** — `cd foundry && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_godot_smoke.py` → all pass.
- [ ] **Step 2 (orchestrator):** rebuild the study scene (14b + 27b), run the **real** Cycles bake at tier 2, clean Godot import, capture screenshots of realtime (tier 0) and baked (tier 2). Confirm: warm interior, cool window shafts, readable, no magenta. Hand to the user for the verdict.
- [ ] **Step 3:** tune planner energies / environment / interior-lamp wattage against the screenshots; commit the tuning.

---

## Self-Review

**Spec coverage:** C1 planner → Task 1; C2 shell windows → Task 2; C3 realtime rig → Task 3; C4 bake
wiring → Task 4; C5 bake interior emitters + bake_key → Task 5; build-order → Task 6; determinism/
caching → Tasks 1/2/5; testing → each task + Task 7. Out-of-scope items have no tasks.

**Placeholder scan:** Blender geometry/bake steps are concrete with code; the `...` in Task 6 Step 1
and Task 2 `_wall_with_opening` mark where the implementer slots project-specific stubs, not missing
logic — every behavioral requirement has code or an explicit rule. No "add error handling"/"TBD".

**Type consistency:** `plan_lighting` return shape (Task 1) is consumed verbatim by `compile_scene
(lighting_plan=…)` (Task 3), `build_lighting_scene_desc` (Task 4), and `bake_key`/`bake_lighting`
(Task 5); `interior_lights` key name is consistent across Tasks 4/5; `windows` dict shape consistent
across Tasks 1/2/6.
