# Palette Contract + Unified Material System Implementation Plan (CP‑1 + CP‑2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind asset color at scene-assembly from a harmonized per-scene palette, applied as one shared material per material-class (neutral structure texture × palette tint, triplanar), so heterogeneous geometry coheres and scenes are recolorable without re-baking.

**Architecture:** `palette.py` derives role colors from theme anchors + harmony rules. `material_classes.py` is the class taxonomy + a `class_for` bridge from the old per-material world. `class_materials.py` (Blender) bakes neutral per-class structure textures. `scene_compiler` consumes a `Palette` to emit one triplanar, palette-tinted `StandardMaterial3D` per class and `material_override`s it onto every surface, stripping incoming materials.

**Tech Stack:** Python 3 (`foundry/.venv`, stdlib `colorsys`), Blender (Cycles), Godot 4, pytest.

## Global Constraints

- **Determinism:** `build_palette(theme, seed, anchors)` is deterministic — no wall-clock, no unseeded RNG; the Palette is hashable and joins the scene cache key.
- **Per-class textures are NEUTRAL** (grayscale structure); hue comes only from the palette at assembly.
- **Texture references use `ext_resource type="Texture2D"`** (Godot resolves to `.ctex`) — NEVER `CompressedTexture2D` sub_resource with `load_path` (that throws "Bad header" → magenta; established bug).
- **Back-compat:** `compile_scene(palette=None)` keeps current behavior; no regression for callers not yet passing a palette.
- **Never hard-fail:** unknown theme → generic anchors; unknown class → `"stone"`; missing class texture → albedo_color only.
- **Tests:** run from `foundry/`; pure-Python tasks fully unit-tested by the implementer; **Blender-gated tests skip without `blender`** — the orchestrator runs the real bake + the two-palette recolor render (CLI owns unit; orchestrator owns Blender/visual). The full suite now exceeds 2 min (Blender tests spawn Blender) — the orchestrator runs the heavy suite.
- **Style:** match existing planners + `scene_compiler.py`.

---

### Task 1: `foundry/palette.py` — palette from anchors + harmony

**Files:**
- Create: `foundry/palette.py`
- Create: `foundry/tests/test_palette.py`

**Interfaces:**
- Produces: `build_palette(theme: str, seed: int = 0, anchors: dict | None = None) -> dict`.
  Returns a `Palette`: `{"roles": {base,shadow,midtone,highlight,accent,foliage,sky: (r,g,b)},
  "classes": {<from material_classes import is NOT required here — roles only>}, "theme": str,
  "seed": int}`. (The `classes` mapping is added by the compiler via `material_classes`; `palette.py`
  owns only `roles`.)
- Module data: `THEME_ANCHORS: dict[str, dict]` — per theme `{"anchors": [(r,g,b), ...],
  "mood": {"temp": "warm"|"cool"|"neutral", "saturation": float, "key": "dark"|"mid"|"bright"}}`,
  plus a `"*"` default.

- [ ] **Step 1: Write the failing tests**

```python
# foundry/tests/test_palette.py
import colorsys
from palette import build_palette

def _v(rgb):  # HSV value
    return colorsys.rgb_to_hsv(*rgb)[2]

def test_deterministic():
    assert build_palette("stone_keep", 0) == build_palette("stone_keep", 0)

def test_roles_present():
    r = build_palette("stone_keep", 0)["roles"]
    assert set(r) >= {"base", "shadow", "midtone", "highlight", "accent", "foliage", "sky"}

def test_shadow_darker_than_base():
    r = build_palette("stone_keep", 0)["roles"]
    assert _v(r["shadow"]) < _v(r["base"]) <= _v(r["highlight"])

def test_dark_key_is_lower_value_than_bright():
    dark = build_palette("dusk_crypt", 0)["roles"]["base"]
    bright = build_palette("sunlit_market", 0)["roles"]["base"]
    assert _v(dark) < _v(bright)

def test_unknown_theme_falls_back():
    r = build_palette("no_such_theme_xyz", 0)["roles"]
    assert set(r) >= {"base", "shadow"}  # generic default, no crash

def test_seed_varies_within_mood():
    a = build_palette("stone_keep", 0)["roles"]["base"]
    b = build_palette("stone_keep", 7)["roles"]["base"]
    assert a != b  # perturbed
    assert abs(_v(a) - _v(b)) < 0.25  # but stays near the mood value
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_palette.py -q`
Expected: FAIL (`No module named 'palette'`).

- [ ] **Step 3: Implement `foundry/palette.py`**

```python
"""foundry.palette — deterministic scene palette from theme anchors + harmony.

build_palette() expands a theme's anchor colors + mood into a harmonized set of
ROLE colors (base/shadow/midtone/highlight/accent/foliage/sky). Engine-agnostic;
the compiler maps material-classes onto these roles. Deterministic.
"""
from __future__ import annotations

import colorsys

# anchors = primary (+optional) RGB; mood = temperature / saturation / value-key.
THEME_ANCHORS: dict[str, dict] = {
    "stone_keep":     {"anchors": [(0.46, 0.45, 0.43)], "mood": {"temp": "cool", "saturation": 0.5, "key": "mid"}},
    "dusk_crypt":     {"anchors": [(0.30, 0.30, 0.34)], "mood": {"temp": "cool", "saturation": 0.5, "key": "dark"}},
    "sunlit_market":  {"anchors": [(0.62, 0.50, 0.34)], "mood": {"temp": "warm", "saturation": 0.7, "key": "bright"}},
    "*":              {"anchors": [(0.50, 0.48, 0.45)], "mood": {"temp": "neutral", "saturation": 0.5, "key": "mid"}},
}

_KEY_VALUE = {"dark": 0.42, "mid": 0.62, "bright": 0.82}


def build_palette(theme: str, seed: int = 0, anchors: dict | None = None) -> dict:
    spec = anchors or THEME_ANCHORS.get(theme, THEME_ANCHORS["*"])
    base_rgb = spec["anchors"][0]
    mood = spec["mood"]
    h, s, v = colorsys.rgb_to_hsv(*base_rgb)

    # seed perturbs hue slightly within the mood (bounded ±0.04)
    h = (h + ((seed * 0.6180339887) % 1.0 - 0.5) * 0.08) % 1.0
    key_v = _KEY_VALUE[mood["key"]]
    s = max(0.0, min(1.0, mood["saturation"]))

    def rgb(hue, sat, val):
        return tuple(round(c, 4) for c in colorsys.hsv_to_rgb(hue % 1.0, max(0, min(1, sat)), max(0, min(1, val))))

    warm = mood["temp"] == "warm"
    roles = {
        "base":      rgb(h, s, key_v),
        "shadow":    rgb(h, s * 0.85, key_v * 0.6),
        "midtone":   rgb(h, s, key_v * 0.82),
        "highlight": rgb(h, s * 0.9, min(1.0, key_v * 1.35)),
        "accent":    rgb(h + 0.45, min(1.0, s + 0.2), key_v * 1.05),
        "foliage":   rgb(0.28, 0.45, key_v * (0.9 if mood["key"] != "dark" else 0.7)),
        "sky":       rgb(0.07 if warm else 0.6, 0.35, min(1.0, key_v * (1.2 if mood["key"] != "dark" else 0.9))),
    }
    return {"roles": roles, "theme": theme, "seed": int(seed)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_palette.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/palette.py foundry/tests/test_palette.py
git commit -m "feat(palette): deterministic scene palette from anchors + HSV harmony"
```

---

### Task 2: `foundry/material_classes.py` — class taxonomy + `class_for`

**Files:**
- Create: `foundry/material_classes.py`
- Create: `foundry/tests/test_material_classes.py`

**Interfaces:**
- Produces:
  - `CLASSES: dict[str, dict]` — each class → `{"role": str, "roughness": float, "metallic": float,
    "texture": str}` (`texture` is the `class_<texture>_*` basename).
  - `class_for(key: str) -> str` — maps a `MATERIAL_PALETTE` family, a material_id, or a prop
    category to a class; unknown → `"stone"`.

- [ ] **Step 1: Write the failing tests**

```python
# foundry/tests/test_material_classes.py
from material_classes import CLASSES, class_for

def test_classes_have_required_fields():
    for name, c in CLASSES.items():
        assert {"role", "roughness", "metallic", "texture"} <= set(c)

def test_family_mapping():
    assert class_for("wood") == "wood"
    assert class_for("stone") == "stone"
    assert class_for("metal") == "metal"

def test_material_id_mapping():
    assert class_for("worn_oak") == "wood"      # via MATERIAL_PALETTE family
    assert class_for("rough_granite") == "stone"

def test_unknown_defaults_to_stone():
    assert class_for("nonsense_qux") == "stone"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_material_classes.py -q`
Expected: FAIL (`No module named 'material_classes'`).

- [ ] **Step 3: Implement `foundry/material_classes.py`**

```python
"""foundry.material_classes — material-class taxonomy + the bridge from the old
per-material world (MATERIAL_PALETTE families / prop categories) to classes.

A class is a coherence bucket: one neutral texture set + one palette role + fixed
surface params. The compiler emits one material per class per scene.
"""
from __future__ import annotations

from materials import MATERIAL_PALETTE

CLASSES: dict[str, dict] = {
    "stone":   {"role": "base",    "roughness": 0.9, "metallic": 0.0, "texture": "stone"},
    "wood":    {"role": "midtone", "roughness": 0.7, "metallic": 0.0, "texture": "wood"},
    "foliage": {"role": "foliage", "roughness": 0.8, "metallic": 0.0, "texture": "foliage"},
    "rock":    {"role": "shadow",  "roughness": 0.9, "metallic": 0.0, "texture": "rock"},
    "metal":   {"role": "accent",  "roughness": 0.35, "metallic": 1.0, "texture": "metal"},
    "fabric":  {"role": "accent",  "roughness": 0.85, "metallic": 0.0, "texture": "fabric"},
    "soil":    {"role": "shadow",  "roughness": 0.95, "metallic": 0.0, "texture": "soil"},
}

# family (from MATERIAL_PALETTE) → class
_FAMILY_CLASS = {"wood": "wood", "stone": "stone", "metal": "metal",
                 "fabric": "fabric", "ceramic": "stone", "foliage": "foliage",
                 "rock": "rock", "soil": "soil"}


def class_for(key: str) -> str:
    if key in CLASSES:
        return key
    if key in _FAMILY_CLASS:
        return _FAMILY_CLASS[key]
    fam = (MATERIAL_PALETTE.get(key) or {}).get("family")
    if fam and fam in _FAMILY_CLASS:
        return _FAMILY_CLASS[fam]
    return "stone"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_material_classes.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/material_classes.py foundry/tests/test_material_classes.py
git commit -m "feat(materials): material-class taxonomy + class_for bridge"
```

---

### Task 3: `foundry/blender/class_materials.py` — neutral class textures (Blender; ORCHESTRATOR)

> **OWNER: orchestrator.** Implemented + baked + committed by the orchestrator (Blender + visual).
> The CLI AI should NOT implement this task. Listed for completeness + the texture-name contract.

**Files:**
- Create: `foundry/blender/class_materials.py`
- Create: `foundry/tests/test_class_materials.py` (Blender-gated)

**Interfaces:**
- Produces: `blender --background --python class_materials.py -- <out_dir> [res]` → per class,
  `class_<name>_{albedo,normal,orm}.png` where **albedo is near-grayscale** (mean saturation < 0.1).
- v1 ships classes `stone`, `wood` (reuse `shell_materials` graphs, desaturated). `foliage/rock/soil`
  may be added with the exterior thread.

(Implementation: generalize `shell_materials.py` — same bake harness, but desaturate the albedo to
grayscale structure so the palette tint controls hue. Orchestrator validates near-grayscale +
screenshots.)

---

### Task 4: `scene_compiler.py` — assembly-time per-class material application

**Files:**
- Modify: `foundry/scene_compiler.py`
- Modify: `foundry/tests/test_scene_compiler.py`

**Interfaces:**
- Consumes: `build_palette` (Task 1) output `Palette`, `material_classes.CLASSES` + `class_for`
  (Task 2), the `class_<name>_*` textures (Task 3 names).
- Produces: `compile_scene(..., palette: dict | None = None)`. When a palette is given, emit ONE
  `StandardMaterial3D` per class present, tinted by the palette role, triplanar, applied as
  `material_override` (incoming stripped). `palette=None` → unchanged behavior.

- [ ] **Step 1: Write failing tests**

```python
# add to foundry/tests/test_scene_compiler.py
def test_palette_emits_one_material_per_class(monkeypatch):
    import scene_compiler as sc
    from palette import build_palette
    pal = build_palette("stone_keep", 0)
    # manifest with a wood table + a stone-ish item → 2 classes
    m = _manifest_with([("table", "worn_oak"), ("shelf", "rough_granite")])
    t = sc.compile_scene([], m, "/tmp/pal/scenes/main.tscn", room_size={"w": 8, "d": 6},
                         theme="stone_keep", palette=pal)
    assert t.count('type="StandardMaterial3D"') >= 2          # one per class
    assert "uv1_triplanar = true" in t
    # albedo tinted by the role colour (wood→midtone), as Color(...)
    midtone = pal["roles"]["midtone"]
    assert f"albedo_color = Color({midtone[0]}" in t
    # textures referenced as ext_resource, never CompressedTexture2D load_path
    assert 'ext_resource type="Texture2D" path="res://assets/class_wood_albedo.png"' in t
    assert "CompressedTexture2D" not in t.split("class_wood")[0][-400:]

def test_no_palette_unchanged():
    import scene_compiler as sc
    t = sc.compile_scene([], _minimal_manifest(), "/tmp/np/scenes/main.tscn",
                         room_size={"w": 8, "d": 6}, theme="stone_keep")  # no palette
    assert "StandardMaterial3D" in t  # existing path still works
```
(Use/adapt the test file's existing manifest helpers; `_manifest_with` mirrors them.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -k palette -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `scene_compiler.py`, add `palette=None` to `compile_scene`. When provided:
1. Compute the set of classes in the scene: for each placed surface/prop, `cls =
   class_for(entity's material_id or category)`; for the shell surfaces use their tags
   (`stone`→`stone`, `timber`→`wood`).
2. For each distinct class, emit (deduped):
   - header `ext_resource type="Texture2D" path="res://assets/class_<cls>_albedo.png"` (and
     `_normal`), unique ids;
   - a `[sub_resource type="StandardMaterial3D" id="mat_<cls>"]` with
     `albedo_texture = ExtResource(<albedo id>)`,
     `albedo_color = Color(r, g, b, 1)` where `(r,g,b) = palette["roles"][CLASSES[cls]["role"]]`,
     `normal_enabled = true` + `normal_texture = ExtResource(<normal id>)`,
     `roughness = CLASSES[cls]["roughness"]`, `metallic = CLASSES[cls]["metallic"]`,
     `uv1_triplanar = true`, `uv1_world_triplanar = true`.
3. Apply `material_override = SubResource("mat_<cls>")` on each surface/prop MeshInstance of that
   class (this STRIPS the GLB's own materials). Reuse the existing shell stone/timber override path,
   generalized to all props.
When `palette is None`, leave the current emission untouched.

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler.py
git commit -m "feat(scene): assembly-time per-class palette materials (triplanar, override)"
```

---

### Task 5: orchestrator — bake class textures + two-palette recolor render (ORCHESTRATOR)

**Files:** none (verification).

- [ ] **Step 1:** implement + bake `class_materials.py` (Task 3); confirm `class_stone/wood_*`
  albedos are near-grayscale; commit the textures into `godot_template/assets/`; update
  `scaffold`/compiler to copy `class_<name>_*` (retire `shell_{stone,timber}_*`).
- [ ] **Step 2:** full unit suite green (orchestrator runs the heavy suite):
  `cd foundry && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_godot_smoke.py`.
- [ ] **Step 3:** build the study scene with `palette=build_palette("stone_keep", 0)`, then again
  with a warm palette (`build_palette("sunlit_market", 0)`), clean Godot import, capture both. Confirm
  recolorability (same geometry, two coherent color stories; props + shell share the palette). Hand
  to the user for the verdict.

---

## Self-Review

**Spec coverage:** C1 palette → Task 1; C2 taxonomy/`class_for` → Task 2; C3 neutral class textures →
Task 3; C4 assembly application → Task 4; C5 migration (copy class textures, override props) → Tasks
4+5; determinism/caching → Task 1; testing → each task + Task 5. Out-of-scope (NPR roof, geometry
normalization) intentionally absent.

**Placeholder scan:** Task 3 is owner=orchestrator with the texture-name contract specified, not a
TODO; Task 4 Step 3 gives concrete emission rules + exact property names. No "add error handling"/TBD.

**Type consistency:** `build_palette(...)["roles"][role]` (Task 1) consumed by Task 4 via
`CLASSES[cls]["role"]` (Task 2); `class_<name>_{albedo,normal,orm}` texture names consistent across
Tasks 3/4/5; `class_for` signature consistent Tasks 2/4. `palette` kwarg name consistent Tasks 4/5.
