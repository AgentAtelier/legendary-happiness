# Prompt-Driven Room Variety (#6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single hardcoded quest manifest with a prompt-driven pipeline that produces a themed, varied room: LLM picks room size + a prop set/counts over a closed grid, deterministic code lays them out across floor/underlay/wall surfaces, missing assets are generated on demand, and over-capacity surfaces as a Decision Point.

**Architecture:** A new grammar-constrained `RoomPlanner` (mirrors `AssetPlanner`) emits `{room_size, props}`. A new pure-Python `room_layout` turns that into a placed-entity manifest with `x/y/z/yaw/surface/decor` fields and an over-capacity Decision Point. The `quest` entrypoint orchestrates planner → layout → build-missing-GLBs (via existing `forge_from_request`) → scaffold. Two new thin-box Blender generators (`rug`, `painting`) extend the closed grid.

**Tech Stack:** Python 3.14 (foundry venv), llama.cpp + GBNF grammars, Blender (bmesh) GLB builders, trimesh gate, Godot 4.7 headless verification.

## Global Constraints

- Test command: `cd foundry && .venv/bin/python -m pytest tests/ -q` (run from `foundry/`; bare imports like `from planner import ...`).
- TDD red→green; commit after each green task with commit-proof (`git log --oneline -n` + `git status`).
- **Single-line GBNF only** — multi-line `|` alternations silently disable constraints.
- Never mutate the real `asset_lexicon.json` in tests or generate-on-demand — use a `/tmp` copy.
- qwen is stochastic — any live claim runs **twice** and compares.
- Godot-in-the-loop on a freshly scaffolded `builds/` project is the gate; structural `.tscn` asserts are necessary but not sufficient.
- Closed vocab: categories `table|chair|shelf|cabinet|rug|painting`; materials `worn_oak|rough_granite|wrought_iron`.
- Room size bounds: `w,d ∈ [4.0, 12.0]` m. Prop `count ∈ [1, 8]`.
- `rug`/`painting` are **decor**: `decor=true`, `surface` ∈ {`underlay`,`wall`}, never the quest target, no pickup/collision.
- Manifest entry shape (the contract with the delegated 1–5 renderer): `{id, category, material, x, y, z, yaw=0.0, surface="floor", decor=false}`; plus top-level `room_size={w,d}` in quest data.
- Don't touch `addons/godot_ai`; don't edit the delegated rendering concerns (walls/lights/no-clip) — only the manifest-generation side.

---

### Task 1: RoomPlanner grammar + module

**Files:**
- Create: `foundry/grammar/room_plan.gbnf`
- Create: `foundry/room_planner.py`
- Test: `foundry/tests/test_room_planner.py`

**Interfaces:**
- Produces: `RoomPlanner().plan(request: str, llm: Callable[[str, Optional[str]], str]) -> Tuple[dict, List[DecisionPoint]]` where the returned plan dict is `{"room_size": {"w": float, "d": float}, "props": [{"category": str, "material": str, "count": int}, ...]}`, all values validated/clamped to the closed vocab and bounds.
- Consumes: `decisions.make_decision`, `decisions.Choice`.

- [ ] **Step 1: Write the grammar file**

Create `foundry/grammar/room_plan.gbnf` (single-line alternations only):

```
# room_plan.gbnf — Constrains LLM output to a valid room-plan JSON.
# Single-line alternations only — normalize_gbnf() joins any multi-line `|`.

root ::= "{" ws "\"room_size\"" ws ":" ws size-object ws "," ws "\"props\"" ws ":" ws props-array ws "}"

size-object ::= "{" ws "\"w\"" ws ":" ws number ws "," ws "\"d\"" ws ":" ws number ws "}"

props-array ::= "[" ws (prop (ws "," ws prop)*)? ws "]"
prop ::= "{" ws "\"category\"" ws ":" ws category-val ws "," ws "\"material\"" ws ":" ws material-val ws "," ws "\"count\"" ws ":" ws number ws "}"

category-val ::= "\"table\"" | "\"chair\"" | "\"shelf\"" | "\"cabinet\"" | "\"rug\"" | "\"painting\""
material-val ::= "\"worn_oak\"" | "\"rough_granite\"" | "\"wrought_iron\""

number ::= "-"? [0-9]+ ("." [0-9]+)? ([eE] [-+]? [0-9]+)?

string ::= "\"" char* "\""
char ::= unescaped | "\\" escape
unescaped ::= [^"\\\x00-\x1F]
escape ::= ["\\/bfnrt] | "u" hex hex hex hex
hex ::= [0-9a-fA-F]

ws ::= [ \t\n\r]*
```

- [ ] **Step 2: Write the failing tests**

Create `foundry/tests/test_room_planner.py`:

```python
"""Tests for the prompt-driven RoomPlanner (stub LLM — no llama)."""
from __future__ import annotations

import json

from room_planner import RoomPlanner


def _stub(plan: dict):
    """Return an llm-shaped callable (prompt, grammar) -> JSON text."""
    return lambda prompt, grammar=None: json.dumps(plan)


def test_valid_plan_passes_through():
    plan = {"room_size": {"w": 6.0, "d": 5.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 2},
                      {"category": "rug", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan("a hermit's shack", _stub(plan))
    assert out["room_size"] == {"w": 6.0, "d": 5.0}
    assert out["props"][0] == {"category": "table", "material": "worn_oak", "count": 2}
    assert decisions == []


def test_room_size_out_of_range_is_clamped_with_decision():
    plan = {"room_size": {"w": 99.0, "d": 1.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 1}]}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["room_size"] == {"w": 12.0, "d": 4.0}
    assert any(d.code == "room.size_clamped" for d in decisions)


def test_count_clamped_and_unknown_material_defaulted():
    plan = {"room_size": {"w": 5.0, "d": 5.0},
            "props": [{"category": "table", "material": "plutonium", "count": 50}]}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["props"][0]["count"] == 8
    assert out["props"][0]["material"] == "worn_oak"
    assert any(d.code == "room.prop_clamped" for d in decisions)


def test_empty_props_emits_decision():
    plan = {"room_size": {"w": 5.0, "d": 5.0}, "props": []}
    out, decisions = RoomPlanner().plan("x", _stub(plan))
    assert out["props"] == []
    assert any(d.code == "room.empty" for d in decisions)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'room_planner'`.

- [ ] **Step 4: Register the new Decision Point templates**

In `foundry/decisions.py`, find the `_TEMPLATES` registry dict and add three entries (match the existing `(technical, plain)` tuple shape):

```python
    "room.size_clamped": (
        "room_size {axis}={raw} clamped to {clamped} (bounds [{lo}, {hi}])",
        "The room was an unusual size, so it was nudged to a sensible {clamped} m.",
    ),
    "room.prop_clamped": (
        "prop {field}={raw!r} invalid → {fixed!r}",
        "One furnishing choice ({field}) didn't fit the catalogue, so it was adjusted to {fixed}.",
    ),
    "room.empty": (
        "room plan had no props",
        "The room came out empty, so there's nothing to furnish it with yet.",
    ),
    "room.over_capacity": (
        "{placed} of {requested} floor props placed; {dropped} over capacity for {w}x{d} room",
        "The model asked for more furniture than the room holds; {placed} fit and {dropped} were left out.",
    ),
```

- [ ] **Step 5: Write the RoomPlanner module**

Create `foundry/room_planner.py`:

```python
"""RoomPlanner — turns a room prompt into a grammar-constrained room plan
(room size + a prop set/counts over the closed grid). Mirrors AssetPlanner:
injectable LLM, single-line GBNF, deterministic post-validation → Decision Points.
The LLM picks nouns + numbers only; it never positions anything.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from decisions import Choice, DecisionPoint, make_decision
from llm import load_grammar as _load_grammar

_GRAMMAR_PATH = str(Path(__file__).resolve().parent / "grammar" / "room_plan.gbnf")
_GRAMMAR = _load_grammar(_GRAMMAR_PATH)

CATEGORIES = ("table", "chair", "shelf", "cabinet", "rug", "painting")
MATERIALS = ("worn_oak", "rough_granite", "wrought_iron")
SIZE_LO, SIZE_HI = 4.0, 12.0
COUNT_LO, COUNT_HI = 1, 8

_PROMPT = """You are a room planner for a 3D game. From the user's description, output ONLY a JSON object — no prose.

First choose room_size (a rectangle in metres): w and d each between 4 and 12. Pick a size that fits the scene.
Then choose props: a list of furnishings appropriate to the room you just sized. Each prop has:
  - category: one of "table", "chair", "shelf", "cabinet", "rug", "painting"
  - material: one of "worn_oak", "rough_granite", "wrought_iron"
  - count: how many of that prop (1 to 8). Do NOT ask for more than fit the room.

Theme the choices: a blacksmith leans wrought_iron and denser; a hermit leans worn_oak and sparse.

Request: {request}

Output JSON now:"""


class RoomPlanner:
    def build_prompt(self, request: str) -> str:
        return _PROMPT.format(request=request)

    def parse(self, text: str) -> dict:
        if not text or not text.strip():
            raise ValueError("Empty LLM response")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```\s*$", "", text)
        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON found:\n{text[:200]}")
        return json.loads(text[start:])

    def plan(
        self, request: str, llm: Callable[[str, Optional[str]], str]
    ) -> Tuple[dict, List[DecisionPoint]]:
        raw = self.parse(llm(self.build_prompt(request), _GRAMMAR))
        decisions: List[DecisionPoint] = []

        size_in = raw.get("room_size", {}) or {}
        room_size = {}
        for axis in ("w", "d"):
            val = size_in.get(axis)
            fval = float(val) if isinstance(val, (int, float)) else SIZE_LO
            clamped = min(max(fval, SIZE_LO), SIZE_HI)
            if clamped != fval:
                decisions.append(make_decision(
                    "room.size_clamped", stage="room", severity="info",
                    context={"axis": axis, "raw": fval, "clamped": clamped,
                             "lo": SIZE_LO, "hi": SIZE_HI},
                    choices=[Choice("accept", "Use the adjusted size")],
                ))
            room_size[axis] = clamped

        props = []
        for p in raw.get("props", []) or []:
            cat = p.get("category")
            mat = p.get("material")
            cnt = p.get("count")
            fixed_cat = cat if cat in CATEGORIES else CATEGORIES[0]
            fixed_mat = mat if mat in MATERIALS else MATERIALS[0]
            icnt = int(cnt) if isinstance(cnt, (int, float)) else COUNT_LO
            fixed_cnt = min(max(icnt, COUNT_LO), COUNT_HI)
            for field, raw_v, fixed_v in (("category", cat, fixed_cat),
                                          ("material", mat, fixed_mat),
                                          ("count", cnt, fixed_cnt)):
                if raw_v != fixed_v:
                    decisions.append(make_decision(
                        "room.prop_clamped", stage="room", severity="info",
                        context={"field": field, "raw": raw_v, "fixed": fixed_v},
                        choices=[Choice("accept", "Use the adjusted value")],
                    ))
            props.append({"category": fixed_cat, "material": fixed_mat, "count": fixed_cnt})

        if not props:
            decisions.append(make_decision(
                "room.empty", stage="room", severity="warn", context={},
                choices=[Choice("add_prop", "Add at least one prop")],
            ))

        return {"room_size": room_size, "props": props}, decisions
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_planner.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add foundry/grammar/room_plan.gbnf foundry/room_planner.py foundry/tests/test_room_planner.py foundry/decisions.py
git commit -m "feat(foundry): RoomPlanner — grammar-constrained room size + prop set"
```

---

### Task 2: Deterministic room layout

**Files:**
- Create: `foundry/room_layout.py`
- Test: `foundry/tests/test_room_layout.py`

**Interfaces:**
- Consumes: the plan dict from Task 1; `decisions.make_decision`, `decisions.Choice`.
- Produces: `layout_room(plan: dict) -> Tuple[List[dict], dict, List[DecisionPoint]]` returning `(manifest, room_size, decisions)`. Each manifest entry is `{id, category, material, x, y, z, yaw, surface, decor}`. `room_size` is `{w, d}`. Floor furniture is non-overlapping; rugs are `surface="underlay"` decor; paintings are `surface="wall"` decor; over-capacity emits `room.over_capacity`.

- [ ] **Step 1: Write the failing tests**

Create `foundry/tests/test_room_layout.py`:

```python
"""Tests for deterministic room layout (no LLM, no Blender)."""
from __future__ import annotations

from room_layout import layout_room

FURNITURE = {"table", "chair", "shelf", "cabinet"}


def _aabb_overlap(a, b, pad=0.0):
    return (abs(a["x"] - b["x"]) < (1.6 - pad) and abs(a["z"] - b["z"]) < (1.6 - pad))


def test_furniture_is_non_overlapping():
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 4}]}
    manifest, room_size, decisions = layout_room(plan)
    furn = [e for e in manifest if e["category"] in FURNITURE]
    assert len(furn) == 4
    for i in range(len(furn)):
        for j in range(i + 1, len(furn)):
            assert not _aabb_overlap(furn[i], furn[j]), f"{furn[i]} overlaps {furn[j]}"
    assert all(e["surface"] == "floor" and not e["decor"] for e in furn)


def test_rug_is_overlappable_underlay_decor():
    plan = {"room_size": {"w": 6.0, "d": 6.0},
            "props": [{"category": "rug", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)
    rug = [e for e in manifest if e["category"] == "rug"][0]
    assert rug["surface"] == "underlay" and rug["decor"] is True
    assert rug["y"] < 0.1  # sits on the floor


def test_painting_is_wall_mounted_decor_facing_in():
    plan = {"room_size": {"w": 6.0, "d": 6.0},
            "props": [{"category": "painting", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)
    p = [e for e in manifest if e["category"] == "painting"][0]
    assert p["surface"] == "wall" and p["decor"] is True
    assert abs(p["z"]) > 2.0 or abs(p["x"]) > 2.0   # against a wall
    assert p["y"] > 1.0                              # hung at height


def test_over_capacity_emits_decision_and_caps_placement():
    plan = {"room_size": {"w": 4.0, "d": 4.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 8}]}
    manifest, _, decisions = layout_room(plan)
    furn = [e for e in manifest if e["category"] in FURNITURE]
    assert len(furn) < 8                       # capped
    dp = [d for d in decisions if d.code == "room.over_capacity"]
    assert dp and dp[0].context["dropped"] == 8 - len(furn)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_layout.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'room_layout'`.

- [ ] **Step 3: Write the layout module**

Create `foundry/room_layout.py`:

```python
"""Deterministic room layout: (room plan) → placed-entity manifest.

No LLM. Floor furniture goes on a non-overlapping grid clear of the player
spawn (origin) and the NPC slot; rugs are floor underlays (overlap intended);
paintings hang on walls. Over-capacity is a Decision Point, never a clip.
"""
from __future__ import annotations

from typing import List, Tuple

from decisions import Choice, DecisionPoint, make_decision

CELL = 1.6            # grid cell size (m) — one furniture item per cell
WALL_MARGIN = 0.8     # keep furniture this far from walls
FURNITURE = ("table", "chair", "shelf", "cabinet")
NPC_Z_INSET = 0.6     # NPC sits this far in from the back wall


def _expand(props: List[dict]) -> List[dict]:
    """props with counts → flat list of single entities, stable order."""
    out = []
    for p in props:
        for _ in range(int(p["count"])):
            out.append({"category": p["category"], "material": p["material"]})
    return out


def _grid_cells(w: float, d: float) -> List[Tuple[float, float]]:
    """Cell centres inside the room, excluding the player spawn (origin)
    and the NPC slot (back-centre)."""
    n_cols = max(1, int((w - 2 * WALL_MARGIN) // CELL))
    n_rows = max(1, int((d - 2 * WALL_MARGIN) // CELL))
    npc_z = -d / 2.0 + NPC_Z_INSET
    cells = []
    for r in range(n_rows):
        for c in range(n_cols):
            x = -(n_cols - 1) * CELL / 2.0 + c * CELL
            z = -(n_rows - 1) * CELL / 2.0 + r * CELL
            if abs(x) < CELL / 2.0 and abs(z) < CELL / 2.0:
                continue                       # player spawn at origin
            if abs(x) < CELL / 2.0 and abs(z - npc_z) < CELL / 2.0:
                continue                       # NPC slot
            cells.append((x, z))
    return cells


def layout_room(plan: dict) -> Tuple[List[dict], dict, List[DecisionPoint]]:
    room_size = plan["room_size"]
    w, d = float(room_size["w"]), float(room_size["d"])
    entities = _expand(plan.get("props", []))
    decisions: List[DecisionPoint] = []
    manifest: List[dict] = []

    furniture = [e for e in entities if e["category"] in FURNITURE]
    rugs = [e for e in entities if e["category"] == "rug"]
    paintings = [e for e in entities if e["category"] == "painting"]

    # ── Floor furniture on the grid ──────────────────────────
    cells = _grid_cells(w, d)
    placed = furniture[: len(cells)]
    dropped = len(furniture) - len(placed)
    for i, (e, (x, z)) in enumerate(zip(placed, cells)):
        manifest.append({"id": f"{e['category']}_{i}", "category": e["category"],
                         "material": e["material"], "x": round(x, 3), "y": 0.0,
                         "z": round(z, 3), "yaw": 0.0, "surface": "floor",
                         "decor": False})
    if dropped > 0:
        decisions.append(make_decision(
            "room.over_capacity", stage="room", severity="warn",
            context={"placed": len(placed), "requested": len(furniture),
                     "dropped": dropped, "w": w, "d": d},
            choices=[Choice("grow_room", "Use a larger room"),
                     Choice("fewer_props", "Reduce the prop count")],
        ))

    # ── Rugs: floor underlays, centred, overlap intended ─────
    for i, e in enumerate(rugs):
        manifest.append({"id": f"rug_{i}", "category": "rug", "material": e["material"],
                         "x": 0.0, "y": 0.01, "z": 0.0, "yaw": 0.0,
                         "surface": "underlay", "decor": True})

    # ── Paintings: hung on walls, facing inward ──────────────
    # Distribute along the back wall (z = -d/2), then side walls.
    walls = [("back", 0.0, -d / 2.0 + 0.05, 0.0),
             ("left", -w / 2.0 + 0.05, 0.0, 1.5708),
             ("right", w / 2.0 - 0.05, 0.0, -1.5708)]
    for i, e in enumerate(paintings):
        _, wx, wz, yaw = walls[i % len(walls)]
        manifest.append({"id": f"painting_{i}", "category": "painting",
                         "material": e["material"], "x": round(wx, 3), "y": 1.5,
                         "z": round(wz, 3), "yaw": yaw, "surface": "wall",
                         "decor": True})

    return manifest, {"w": w, "d": d}, decisions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_layout.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/room_layout.py foundry/tests/test_room_layout.py
git commit -m "feat(foundry): deterministic room layout + over-capacity Decision Point"
```

---

### Task 3: Thread room_size into compiled quest data

**Files:**
- Modify: `foundry/scene_compiler.py` (the `compile_scene` quest_data block, ~line 250)
- Test: `foundry/tests/test_scene_compiler.py` (add one test)

**Interfaces:**
- Consumes: `room_size` dict from Task 2.
- Produces: `compile_scene(..., room_size: dict | None = None)` writes `room_size` into the `_quest_data.json`. Extra manifest entry keys (`yaw/surface/decor`) are ignored by the compiler today and must keep round-tripping without error (the delegated renderer consumes them).

- [ ] **Step 1: Write the failing test**

Add to `foundry/tests/test_scene_compiler.py`:

```python
def test_compile_scene_writes_room_size(tmp_path):
    from scene_compiler import compile_scene, read_quest_data
    spec = {"target_entity": "table_0", "npc_role": "smith",
            "objective": {"type": "fetch", "target": "table_0", "giver": "npc"},
            "dialogue": {"greet": "hi", "ask": "find it", "wrong": "no", "thank": "ok"}}
    manifest = [{"id": "table_0", "category": "table", "material": "worn_oak",
                 "x": 1.0, "y": 0.0, "z": -1.0, "yaw": 0.0,
                 "surface": "floor", "decor": False}]
    out = str(tmp_path / "main.tscn")
    compile_scene(spec, manifest, out, room_size={"w": 6.0, "d": 5.0})
    data = read_quest_data(out)
    assert data["room_size"] == {"w": 6.0, "d": 5.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py::test_compile_scene_writes_room_size -q`
Expected: FAIL — `compile_scene() got an unexpected keyword argument 'room_size'`.

- [ ] **Step 3: Add the parameter and write the field**

In `foundry/scene_compiler.py`, change the `compile_scene` signature to add `room_size: dict | None = None` (after `scene_uid`), and in the `quest_data` dict literal (~line 250) add the line:

```python
    quest_data: dict = {
        "npc_role": npc_role,
        "target_entity": target_entity,
        "dialogue": dialogue,
        "objective": objective,
        "room_size": room_size or {"w": 8.0, "d": 8.0},
    }
```

- [ ] **Step 4: Run the test + full compiler suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -q`
Expected: PASS (all, including the new test).

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler.py
git commit -m "feat(foundry): carry room_size into compiled quest data"
```

---

### Task 4: `rug` generator (thin-box GLB)

**Files:**
- Modify: `foundry/compiler.py` (`GENERATORS`, `PARAM_RANGES`)
- Modify: `foundry/grammar/asset_spec.gbnf` (`asset-id-val`, `generator-val`)
- Modify: `foundry/blender/build_asset.py` (`_build_rug_geometry`, `_BUILDERS`, `apply_bevel` guard)
- Modify: the lexicon at `engine/devforge/spatial/asset_lexicon.json` (add `rug` envelope)
- Test: `foundry/tests/test_compiler.py` (accept rug spec) + `foundry/tests/test_build_blender.py` (live build, skip-if-no-blender)

**Interfaces:**
- Produces: a buildable `rug` generator with params `width, depth, thickness`; envelope in the lexicon so `gate_asset` passes.

- [ ] **Step 1: Write the failing compiler test**

Add to `foundry/tests/test_compiler.py`:

```python
def test_rug_spec_compiles():
    from compiler import compile_spec
    spec = {"asset_id": "rug", "generator": "rug", "material": "worn_oak",
            "age": 0.2, "params": {"width": 2.0, "depth": 1.4, "thickness": 0.02}}
    out = compile_spec(spec)
    assert out["generator"] == "rug" and out["params"]["thickness"] == 0.02
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py::test_rug_spec_compiles -q`
Expected: FAIL — `SpecError: unknown generator: 'rug'`.

- [ ] **Step 3: Extend the compiler vocabulary**

In `foundry/compiler.py`: add `"rug"` to `GENERATORS`, and add to `PARAM_RANGES`:

```python
    "rug": {
        "width": (0.8, 3.5),
        "depth": (0.6, 2.5),
        "thickness": (0.01, 0.04),
    },
```

- [ ] **Step 4: Extend the grammar**

In `foundry/grammar/asset_spec.gbnf`, append `| "\"rug\""` to **both** `asset-id-val` and `generator-val` (keep them single-line).

- [ ] **Step 5: Add the lexicon envelope**

In `engine/devforge/spatial/asset_lexicon.json`, add under `"assets"` (envelope must exceed max params + the gate's 15% tol):

```json
    "rug": { "path": "", "category": ["decor"], "footprint": { "width": 3.5, "depth": 2.5 }, "height": 0.06, "greybox": { "mesh": "box", "color": [0.5, 0.3, 0.2] } }
```

- [ ] **Step 6: Add the geometry builder + bevel guard**

In `foundry/blender/build_asset.py` add the builder and register it:

```python
def _build_rug_geometry(params):
    """A thin flat watertight box — a rug/mat lying on the floor."""
    w, d, t = params["width"], params["depth"], params["thickness"]
    mesh = bpy.data.meshes.new("rug")
    obj = bpy.data.objects.new("rug", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, t / 2.0, w, d, t)
    bm.to_mesh(mesh)
    bm.free()
    return mesh
```

Add `"rug": _build_rug_geometry,` to `_BUILDERS`. Then make `apply_bevel` safe for thin props — change its fixed `offset=0.015` to derive from the mesh so a 0.02 m rug isn't collapsed:

```python
def apply_bevel(mesh_data):
    """Apply a small uniform edge bevel, clamped so thin props survive."""
    import numpy as _np
    co = _np.array([v.co for v in mesh_data.vertices])
    min_extent = float((co.max(axis=0) - co.min(axis=0)).min()) if len(co) else 0.05
    offset = min(0.015, 0.4 * min_extent)
    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    bmesh.ops.bevel(
        bm,
        geom=[e for e in bm.edges],
        offset=offset,
        offset_type="OFFSET",
        segments=2,
```

(keep the rest of `apply_bevel` unchanged below this point.)

- [ ] **Step 7: Write the live build test**

Add to `foundry/tests/test_build_blender.py` (follow the file's existing skip-if-no-blender guard; this mirrors it explicitly):

```python
import shutil, json, subprocess, sys
from pathlib import Path
import pytest
from gate import gate_asset
from library import read_envelope

_BLENDER = shutil.which("blender")

@pytest.mark.skipif(_BLENDER is None, reason="blender not installed")
def test_rug_builds_and_passes_gate(tmp_path):
    spec = {"asset_id": "rug", "generator": "rug", "material": "worn_oak",
            "age": 0.2, "params": {"width": 2.0, "depth": 1.4, "thickness": 0.02}}
    sp = tmp_path / "rug.json"; sp.write_text(json.dumps(spec))
    out = tmp_path / "rug.glb"
    build = Path(__file__).resolve().parent.parent / "blender" / "build_asset.py"
    r = subprocess.run([_BLENDER, "--background", "--python", str(build), "--",
                        str(sp), str(out)], capture_output=True, text=True, timeout=300)
    assert out.exists(), r.stderr[-2000:]
    lex = str(Path(__file__).resolve().parents[2] / "engine/devforge/spatial/asset_lexicon.json")
    fp, h = read_envelope(lex, "rug")
    assert gate_asset(str(out), fp, h).passed
```

- [ ] **Step 8: Run tests**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py::test_rug_spec_compiles tests/test_build_blender.py -q`
Expected: compiler test PASS; rug build test PASS (or SKIP if blender absent — then run the build manually once and paste output as proof).

- [ ] **Step 9: Commit**

```bash
git add foundry/compiler.py foundry/grammar/asset_spec.gbnf foundry/blender/build_asset.py foundry/tests/test_compiler.py foundry/tests/test_build_blender.py engine/devforge/spatial/asset_lexicon.json
git commit -m "feat(foundry): rug generator — thin-box decor GLB + bevel guard for thin props"
```

---

### Task 5: `painting` generator (wall-mounted thin-box GLB)

**Files:** same set as Task 4.

**Interfaces:**
- Produces: a buildable `painting` generator with params `width, height, thickness`; lexicon envelope so `gate_asset` passes. Geometry is authored so its thin axis is Y (Blender) → depth in the GLB; the layout's `yaw` faces it into the room.

- [ ] **Step 1: Write the failing compiler test**

Add to `foundry/tests/test_compiler.py`:

```python
def test_painting_spec_compiles():
    from compiler import compile_spec
    spec = {"asset_id": "painting", "generator": "painting", "material": "worn_oak",
            "age": 0.2, "params": {"width": 0.6, "height": 0.8, "thickness": 0.05}}
    out = compile_spec(spec)
    assert out["generator"] == "painting" and out["params"]["height"] == 0.8
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py::test_painting_spec_compiles -q`
Expected: FAIL — `SpecError: unknown generator: 'painting'`.

- [ ] **Step 3: Extend compiler vocabulary**

In `foundry/compiler.py`: add `"painting"` to `GENERATORS`, and to `PARAM_RANGES`:

```python
    "painting": {
        "width": (0.3, 1.2),
        "height": (0.3, 1.2),
        "thickness": (0.03, 0.08),
    },
```

- [ ] **Step 4: Extend the grammar**

In `foundry/grammar/asset_spec.gbnf`, append `| "\"painting\""` to **both** `asset-id-val` and `generator-val` (single-line).

- [ ] **Step 5: Add the lexicon envelope**

In `engine/devforge/spatial/asset_lexicon.json`, under `"assets"`:

```json
    "painting": { "path": "", "category": ["decor"], "footprint": { "width": 1.2, "depth": 0.12 }, "height": 1.3, "greybox": { "mesh": "box", "color": [0.4, 0.3, 0.2] } }
```

- [ ] **Step 6: Add the geometry builder**

In `foundry/blender/build_asset.py` add and register:

```python
def _build_painting_geometry(params):
    """A thin vertical watertight box — a framed painting to hang on a wall.
    Thin axis is Y (Blender) → becomes depth in the Y-up GLB; width=X, height=Z."""
    w, h, t = params["width"], params["height"], params["thickness"]
    mesh = bpy.data.meshes.new("painting")
    obj = bpy.data.objects.new("painting", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, h / 2.0, w, t, h)
    bm.to_mesh(mesh)
    bm.free()
    return mesh
```

Add `"painting": _build_painting_geometry,` to `_BUILDERS`.

- [ ] **Step 7: Write the live build test**

Add to `foundry/tests/test_build_blender.py`:

```python
@pytest.mark.skipif(_BLENDER is None, reason="blender not installed")
def test_painting_builds_and_passes_gate(tmp_path):
    spec = {"asset_id": "painting", "generator": "painting", "material": "worn_oak",
            "age": 0.2, "params": {"width": 0.6, "height": 0.8, "thickness": 0.05}}
    sp = tmp_path / "painting.json"; sp.write_text(json.dumps(spec))
    out = tmp_path / "painting.glb"
    build = Path(__file__).resolve().parent.parent / "blender" / "build_asset.py"
    r = subprocess.run([_BLENDER, "--background", "--python", str(build), "--",
                        str(sp), str(out)], capture_output=True, text=True, timeout=300)
    assert out.exists(), r.stderr[-2000:]
    lex = str(Path(__file__).resolve().parents[2] / "engine/devforge/spatial/asset_lexicon.json")
    fp, h = read_envelope(lex, "painting")
    assert gate_asset(str(out), fp, h).passed
```

- [ ] **Step 8: Run tests**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py -q tests/test_build_blender.py -q`
Expected: compiler tests PASS; painting build PASS or SKIP (build manually once for proof if skipped).

- [ ] **Step 9: Commit**

```bash
git add foundry/compiler.py foundry/grammar/asset_spec.gbnf foundry/blender/build_asset.py foundry/tests/test_compiler.py foundry/tests/test_build_blender.py engine/devforge/spatial/asset_lexicon.json
git commit -m "feat(foundry): painting generator — wall-mounted thin-box decor GLB"
```

---

### Task 6: Integration — generate-on-demand + wire RoomPlanner into `quest`

**Files:**
- Create: `foundry/asset_ensure.py` (build-missing-GLBs helper)
- Modify: `foundry/__main__.py` (`_cmd_quest`: replace the hardcoded manifest)
- Modify: `foundry/scaffold.py` (`scaffold_project`: add `room_size` param, forward to `compile_scene`)
- Test: `foundry/tests/test_asset_ensure.py`

**Interfaces:**
- Consumes: Task 1 `RoomPlanner.plan`, Task 2 `layout_room`, Task 3 `compile_scene(room_size=...)`, existing `behaviour_gen.QuestBehaviourPlanner.plan`, `scaffold.scaffold_project`, `runner.forge_from_request`.
- Produces: `ensure_assets(manifest, library_dir, lexicon_path, *, builder=forge_from_request) -> List[DecisionPoint]` — builds any `(category, material)` GLB not already present, into `library_dir`, using a **/tmp copy** of the lexicon; reuses an existing GLB.

- [ ] **Step 1: Write the failing test (stub builder — no Blender)**

Create `foundry/tests/test_asset_ensure.py`:

```python
"""generate-on-demand orchestration (stub builder — no Blender, no llama)."""
from __future__ import annotations

from pathlib import Path
from asset_ensure import ensure_assets


def test_builds_only_missing_glbs(tmp_path):
    lib = tmp_path / "assets"; lib.mkdir()
    (lib / "table_worn_oak.glb").write_text("existing")     # already built
    lex = tmp_path / "asset_lexicon.json"
    lex.write_text('{"assets": {"table": {"footprint": {"width": 1, "depth": 1}, "height": 1}}}')
    built = []

    def fake_builder(request, lexicon_path, library_dir, **kw):
        # emulate forge writing a GLB named <category>_<material>.glb
        cat, mat = request.split("|")
        Path(library_dir, f"{cat}_{mat}.glb").write_text("built")
        built.append((cat, mat, lexicon_path))

    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak"},   # exists → skip
        {"id": "shelf_0", "category": "shelf", "material": "wrought_iron"},# missing → build
    ]
    ensure_assets(manifest, str(lib), str(lex),
                  builder=fake_builder, request_fmt="{category}|{material}")
    pairs = [(b[0], b[1]) for b in built]
    assert ("shelf", "wrought_iron") in pairs      # missing → built
    assert ("table", "worn_oak") not in pairs      # already present → skipped
    # never built against the real lexicon path
    assert all(b[2] != str(lex) for b in built), "must use a /tmp lexicon copy"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_asset_ensure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asset_ensure'`.

- [ ] **Step 3: Write the helper**

Create `foundry/asset_ensure.py`:

```python
"""Build any (category, material) GLB a manifest references that isn't yet in
the library. Reuses the existing single-asset forge. Never mutates the real
lexicon — copies it to /tmp first (standing rule).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable, List

from decisions import DecisionPoint


def ensure_assets(
    manifest: List[dict],
    library_dir: str,
    lexicon_path: str,
    *,
    builder: Callable = None,
    request_fmt: str = "a {material} {category}",
) -> List[DecisionPoint]:
    if builder is None:
        from runner import forge_from_request as builder  # noqa: N806
    decisions: List[DecisionPoint] = []
    # /tmp copy of the lexicon — never mutate the real one.
    tmp_lex = Path(tempfile.mkdtemp()) / "asset_lexicon.json"
    shutil.copy(lexicon_path, tmp_lex)
    Path(library_dir).mkdir(parents=True, exist_ok=True)

    seen: set[tuple[str, str]] = set()
    for e in manifest:
        cat, mat = e["category"], e["material"]
        if (cat, mat) in seen:
            continue
        seen.add((cat, mat))
        glb = Path(library_dir) / f"{cat}_{mat}.glb"
        if glb.exists():
            continue
        request = request_fmt.format(category=cat, material=mat)
        result = builder(request, str(tmp_lex), library_dir)
        if result is not None and getattr(result, "decisions", None):
            decisions.extend(result.decisions)
    return decisions
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_asset_ensure.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the pipeline into `_cmd_quest`**

In `foundry/__main__.py`, replace the hardcoded `manifest = [...]` block in `_cmd_quest` with the generated path (insert after `parsed = parser.parse_args(args)` and the LLM build):

```python
    # ── Step 0: Plan the room from the prompt ─────────────────
    from room_planner import RoomPlanner
    from room_layout import layout_room
    from asset_ensure import ensure_assets

    room_plan, room_decisions = RoomPlanner().plan(parsed.request, llm)
    manifest, room_size, layout_decisions = layout_room(room_plan)

    # Build any (category, material) the room needs that isn't in the library.
    ensure_decisions = ensure_assets(manifest, parsed.library_dir, parsed.lexicon)
```

Then: pass `room_size=room_size` into the `compile_scene` call **inside `scaffold_project`** — add a `room_size` parameter to `scaffold.scaffold_project` that it forwards to `compile_scene` (default `None`), and pass `room_size=room_size` from `_cmd_quest`. Finally extend the decisions rendered at the end:

```python
    all_decisions = room_decisions + layout_decisions + ensure_decisions + decisions
    rendered = _render_decisions_cli(all_decisions)
```

(Keep the existing `behaviour_gen` call, which now receives the **generated** manifest instead of the hardcoded one.)

- [ ] **Step 6: Run the full suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/ -q`
Expected: PASS (all green; previously 502 + the new tests).

- [ ] **Step 7: Live verification (run-twice + Godot-in-the-loop + stress test)**

With llama healthy on a ≥9B model (per [[quest-npc-model-capability]]), run:

```bash
cd foundry && .venv/bin/python -m foundry quest --request "a blacksmith's back room" --scene rv_smith_a
cd foundry && .venv/bin/python -m foundry quest --request "a blacksmith's back room" --scene rv_smith_b
godot --headless --path ../builds/rv_smith_a --quit
```

Confirm: the two rooms differ (size/props/counts/palette); the scaffolded build opens headlessly with no missing-resource errors; the over-capacity Decision Point fires when you force a dense prompt (e.g. "a cramped armory crammed with furniture"). Paste the two specs + headless output as commit-proof.

- [ ] **Step 8: Commit**

```bash
git add foundry/asset_ensure.py foundry/__main__.py foundry/scaffold.py foundry/tests/test_asset_ensure.py
git commit -m "feat(foundry): wire RoomPlanner→layout→generate-on-demand into quest"
```

---

## Self-Review notes (for the executor)

- **Decor rendering** (no collider / no pickup tag / `yaw` orientation for rug & painting) and **walls/floor sized to `room_size`** live in the **delegated 1–5 renderer**, not here — this plan only *produces* the contract fields. If that work hasn't merged when Task 7 runs, rug/painting will render as plain pickable boxes (harmless); re-verify decor behavior after the merge.
- **behaviour_gen target eligibility:** the quest target must be a furniture prop, not decor. If `QuestBehaviourPlanner` can pick a `rug_*`/`painting_*` id from the generated manifest, add a follow-up guard (filter decor from the manifest it sees). Verify during Task 7; ticket it if it surfaces.
- **Generate-on-demand is slow** (Blender per missing GLB). First run of a new theme builds several assets; subsequent runs reuse them. Acceptable for this testing-grade slice.
