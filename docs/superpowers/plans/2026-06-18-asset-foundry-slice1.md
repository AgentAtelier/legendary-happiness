# Asset Foundry — Slice 1 (Spine Prover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the offline asset foundry end-to-end on one asset — turn a hand-written `table` spec into a gated, lexicon-registered `table.glb`, with a render for visual verification.

**Architecture:** A standalone top-level `foundry/` package (own venv, no engine import — it reads the lexicon JSON directly). A deterministic `compiler` validates a JSON asset-spec; a `runner` shells out to `blender --background` to build the mesh (bmesh primitives, slice 1) and export GLB; a `gate` checks the exported GLB with `trimesh` (watertight, polygon budget, bounds vs the lexicon's footprint/height); `library` writes the GLB path into a lexicon entry. A Blender render script produces a PNG for eyeball verification.

**Tech Stack:** Python 3.14 (foundry venv), `trimesh` (GLB inspection), `pytest`, Blender (headless, `bpy`, bmesh, glTF export, Cycles-CPU render).

## Global Constraints

- **Blender must be installed and on PATH** (`blender --version` works). Install is a prerequisite, done outside this plan (`sudo pacman -S blender`). Blender-dependent tests `skipif` it is absent, so Tasks 1–3 are fully runnable without it.
- **Foundry is standalone:** lives in top-level `foundry/`, has its own `foundry/.venv`, and **does not import the `devforge` engine package** — it reads `asset_lexicon.json` as plain JSON.
- **Reproducible recipes, no binary blobs:** the generator is built in code (bmesh in a `bpy` script); do not commit a hand-authored `.blend`.
- **Slice-1 scope:** generator internals are **bmesh primitives** (GeoNodes node-tree authoring is Slice 2). **Live-scene instancing is deferred** — verify by standalone render, not by the live Godot pipeline.
- Files ≤ 500 lines. Fork policy (never patch godot-ai) — not touched this slice.
- **Coordinate convention:** Blender is Z-up; the glTF exporter converts to Y-up, so in the exported GLB **height is Y, footprint is X (width) and Z (depth)**. The gate and fixtures use this convention.
- Foundry test command (from repo root): `cd foundry && .venv/bin/python -m pytest tests/ -q`

---

### Task 1: Foundry scaffold + AssetCompiler (spec validation)

**Files:**
- Create: `foundry/__init__.py` (empty), `foundry/conftest.py` (empty — puts `foundry/` on `sys.path`)
- Create: `foundry/compiler.py`
- Create: `foundry/specs/table.json`
- Create: `foundry/tests/__init__.py` (empty), `foundry/tests/test_compiler.py`
- Create: `foundry/.venv` (via command), `foundry/requirements.txt`

**Interfaces:**
- Produces: `compiler.SpecError(ValueError)`; `compiler.load_spec(path: str) -> dict`; `compiler.compile_spec(spec: dict) -> dict` returning `{"asset_id": str, "generator": str, "material": str, "params": dict}` or raising `SpecError`.

- [ ] **Step 1: Create the package, venv, and dependencies**

```bash
cd /home/mrg/dev/games/Forge
mkdir -p foundry/specs foundry/tests foundry/blender
touch foundry/__init__.py foundry/conftest.py foundry/tests/__init__.py
printf 'trimesh\npytest\n' > foundry/requirements.txt
python -m venv foundry/.venv
foundry/.venv/bin/pip install -q -r foundry/requirements.txt
foundry/.venv/bin/python -c "import trimesh, pytest; print('deps ok')"
```
Expected: prints `deps ok`.

- [ ] **Step 2: Write the table spec**

Create `foundry/specs/table.json` (designed to match the lexicon envelope: width 1.5, depth 1.0, height = leg_height + top_thickness = 0.67 + 0.08 = 0.75):

```json
{
  "asset_id": "table",
  "generator": "table",
  "material": "worn_oak",
  "params": {
    "top_width": 1.5,
    "top_depth": 1.0,
    "top_thickness": 0.08,
    "leg_height": 0.67,
    "leg_radius": 0.06,
    "leg_inset": 0.1
  }
}
```

- [ ] **Step 3: Write the failing test**

Create `foundry/tests/test_compiler.py`:

```python
import json

import pytest

from compiler import SpecError, compile_spec, load_spec


def _spec():
    return {
        "asset_id": "table",
        "generator": "table",
        "material": "worn_oak",
        "params": {
            "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
            "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
        },
    }


def test_valid_spec_compiles():
    out = compile_spec(_spec())
    assert out["generator"] == "table"
    assert out["material"] == "worn_oak"
    assert out["params"]["top_width"] == 1.5


def test_unknown_generator_rejected():
    s = _spec(); s["generator"] = "spaceship"
    with pytest.raises(SpecError):
        compile_spec(s)


def test_unknown_material_rejected():
    s = _spec(); s["material"] = "neon_plasma"
    with pytest.raises(SpecError):
        compile_spec(s)


def test_param_out_of_range_rejected():
    s = _spec(); s["params"]["top_width"] = 10.0
    with pytest.raises(SpecError):
        compile_spec(s)


def test_missing_param_rejected():
    s = _spec(); del s["params"]["leg_height"]
    with pytest.raises(SpecError):
        compile_spec(s)


def test_load_spec_reads_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_spec()), encoding="utf-8")
    assert load_spec(str(p))["asset_id"] == "table"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'compiler'`.

- [ ] **Step 5: Implement the compiler**

Create `foundry/compiler.py`:

```python
"""AssetCompiler: validate an asset-spec against the known generators and the
closed material/param vocabulary. Slice 1 has one generator (table). This is the
deterministic gate between LLM/hand intent and the Blender build — it does the
relative reasoning (range checks) the LLM must never do."""

from __future__ import annotations

import json

GENERATORS = {"table"}
MATERIALS = {"worn_oak"}

# Per-generator parameter ranges (min, max). The narrow, known-good envelope —
# the guardrail against the "95% of the parameter space is garbage" failure.
PARAM_RANGES = {
    "table": {
        "top_width": (0.5, 3.0),
        "top_depth": (0.4, 2.0),
        "top_thickness": (0.03, 0.2),
        "leg_height": (0.3, 1.1),
        "leg_radius": (0.03, 0.12),
        "leg_inset": (0.0, 0.3),
    }
}


class SpecError(ValueError):
    """Raised when an asset-spec is invalid (unknown generator/material, or a
    parameter missing or out of its known-good range)."""


def load_spec(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compile_spec(spec: dict) -> dict:
    gen = spec.get("generator")
    if gen not in GENERATORS:
        raise SpecError(f"unknown generator: {gen!r} (known: {sorted(GENERATORS)})")

    material = spec.get("material")
    if material not in MATERIALS:
        raise SpecError(f"unknown material: {material!r} (known: {sorted(MATERIALS)})")

    params = spec.get("params") or {}
    ranges = PARAM_RANGES[gen]
    for key, (lo, hi) in ranges.items():
        if key not in params:
            raise SpecError(f"missing param: {key!r}")
        val = params[key]
        if not isinstance(val, (int, float)):
            raise SpecError(f"param {key!r} must be a number, got {type(val).__name__}")
        if not (lo <= val <= hi):
            raise SpecError(f"param {key!r}={val} out of range [{lo}, {hi}]")

    return {
        "asset_id": spec.get("asset_id", gen),
        "generator": gen,
        "material": material,
        "params": {k: float(params[k]) for k in ranges},
    }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_compiler.py -q`
Expected: PASS (6 passed).

- [ ] **Step 7: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/__init__.py foundry/conftest.py foundry/requirements.txt foundry/compiler.py foundry/specs/table.json foundry/tests/__init__.py foundry/tests/test_compiler.py
git commit -m "feat(foundry): asset-spec compiler + table spec (slice 1 scaffold)"
```
(Do not commit `foundry/.venv` — add a `.gitignore` if the repo doesn't already ignore venvs.)

---

### Task 2: Deterministic gate (trimesh, no Blender)

**Files:**
- Create: `foundry/gate.py`
- Create: `foundry/tests/test_gate.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `gate.GateResult` (dataclass: `passed: bool`, `reasons: list[str]`); `gate.gate_asset(glb_path: str, footprint: dict, height: float, poly_budget: int = 2000, tol: float = 0.15) -> GateResult`. `footprint` is `{"width": float, "depth": float}`.

- [ ] **Step 1: Write the failing test**

Create `foundry/tests/test_gate.py`:

```python
import trimesh

from gate import gate_asset

FOOTPRINT = {"width": 1.5, "depth": 1.0}
HEIGHT = 0.75


def _export(tmp_path, mesh, name):
    p = tmp_path / name
    mesh.export(str(p))
    return str(p)


def test_well_formed_asset_passes(tmp_path):
    # extents map to (width=X, height=Y, depth=Z) per the GLB Y-up convention
    box = trimesh.creation.box(extents=[1.5, 0.75, 1.0])
    glb = _export(tmp_path, box, "good.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert res.passed, res.reasons


def test_oversized_asset_fails_bounds(tmp_path):
    box = trimesh.creation.box(extents=[3.0, 0.75, 1.0])  # too wide
    glb = _export(tmp_path, box, "wide.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("width" in r for r in res.reasons)


def test_non_watertight_fails(tmp_path):
    box = trimesh.creation.box(extents=[1.5, 0.75, 1.0])
    holey = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-2])
    glb = _export(tmp_path, holey, "holey.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("watertight" in r for r in res.reasons)


def test_over_budget_fails(tmp_path):
    sphere = trimesh.creation.icosphere(subdivisions=4)  # ~5120 faces
    sphere.apply_scale([1.5, 0.75, 1.0])
    glb = _export(tmp_path, sphere, "dense.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT, poly_budget=2000)
    assert not res.passed
    assert any("budget" in r for r in res.reasons)


def test_degenerate_fails(tmp_path):
    flat = trimesh.creation.box(extents=[1.5, 0.0001, 1.0])
    glb = _export(tmp_path, flat, "flat.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert not res.passed
    assert any("degenerate" in r for r in res.reasons)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate'`.

- [ ] **Step 3: Implement the gate**

Create `foundry/gate.py`:

```python
"""Deterministic asset gate. Cheap, objective checks on an exported GLB before it
enters the library: watertight, polygon budget, non-degenerate, and bounds within
the lexicon's footprint/height envelope (the free ground-truth oracle).

GLB convention (Blender glTF export is Y-up): extents are [width=X, height=Y,
depth=Z]. Slice 1 has no asset-class-aware exceptions (e.g. campfire logs that
*should* intersect) — that arrives with the style grammar."""

from __future__ import annotations

from dataclasses import dataclass

import trimesh


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]


def gate_asset(
    glb_path: str,
    footprint: dict,
    height: float,
    poly_budget: int = 2000,
    tol: float = 0.15,
) -> GateResult:
    reasons: list[str] = []

    mesh = trimesh.load(glb_path, force="mesh")
    if mesh is None or mesh.is_empty:
        return GateResult(False, ["empty mesh"])

    ext = mesh.extents  # [x, y, z]
    width, h, depth = float(ext[0]), float(ext[1]), float(ext[2])

    # Non-degenerate: every dimension must have real size.
    for name, value in (("width", width), ("height", h), ("depth", depth)):
        if value < 0.01:
            reasons.append(f"degenerate {name}={value:.4f} (< 0.01)")

    # Bounds: must fit the placement envelope (upper bound with tolerance).
    if width > footprint["width"] * (1 + tol):
        reasons.append(f"width {width:.3f} exceeds footprint {footprint['width']} (+{tol:.0%})")
    if depth > footprint["depth"] * (1 + tol):
        reasons.append(f"depth {depth:.3f} exceeds footprint {footprint['depth']} (+{tol:.0%})")
    if h > height * (1 + tol):
        reasons.append(f"height {h:.3f} exceeds {height} (+{tol:.0%})")

    # Watertight (manifold-ish): every edge shared by exactly two faces.
    if not mesh.is_watertight:
        reasons.append("mesh is not watertight")

    # Polygon budget.
    n_faces = int(mesh.faces.shape[0])
    if n_faces > poly_budget:
        reasons.append(f"polygon budget exceeded: {n_faces} > {poly_budget}")

    return GateResult(len(reasons) == 0, reasons)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_gate.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/gate.py foundry/tests/test_gate.py
git commit -m "feat(foundry): deterministic GLB gate (watertight, budget, bounds)"
```

---

### Task 3: Lexicon I/O (read envelope, register path)

**Files:**
- Create: `foundry/library.py`
- Create: `foundry/tests/test_library.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `library.read_envelope(lexicon_path: str, asset_id: str) -> tuple[dict, float]` returning `({"width","depth"}, height)`; `library.register_asset(lexicon_path: str, asset_id: str, asset_path: str) -> None` (writes `path` into the entry and saves). `library.LIVE_LEXICON` constant: path to the real lexicon.

- [ ] **Step 1: Write the failing test**

Create `foundry/tests/test_library.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

from library import LIVE_LEXICON, read_envelope, register_asset


@pytest.fixture
def lexicon_copy(tmp_path):
    dst = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, dst)
    return str(dst)


def test_live_lexicon_exists():
    assert Path(LIVE_LEXICON).exists(), LIVE_LEXICON


def test_read_envelope_table(lexicon_copy):
    footprint, height = read_envelope(lexicon_copy, "table")
    assert footprint == {"width": 1.5, "depth": 1.0}
    assert height == 0.75


def test_register_writes_path(lexicon_copy):
    register_asset(lexicon_copy, "table", "res://assets/table.glb")
    data = json.loads(Path(lexicon_copy).read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == "res://assets/table.glb"


def test_register_unknown_asset_raises(lexicon_copy):
    with pytest.raises(KeyError):
        register_asset(lexicon_copy, "dragon", "res://assets/dragon.glb")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_library.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'library'`.

- [ ] **Step 3: Implement library I/O**

Create `foundry/library.py`:

```python
"""Library/lexicon integration. The foundry reads the lexicon JSON directly (no
engine import) to get the placement envelope (the gate oracle), and writes an
accepted asset's path back into the entry. This is the seam the live pipeline
later reads — but instancing the asset into a live scene is a LATER slice."""

from __future__ import annotations

import json
from pathlib import Path

# Real lexicon: repo_root/engine/devforge/spatial/asset_lexicon.json
# This file is foundry/library.py → parents[1] is repo root.
LIVE_LEXICON = str(
    Path(__file__).resolve().parents[1]
    / "engine" / "devforge" / "spatial" / "asset_lexicon.json"
)


def read_envelope(lexicon_path: str, asset_id: str) -> tuple[dict, float]:
    data = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
    entry = data["assets"][asset_id]
    fp = entry["footprint"]
    return {"width": fp["width"], "depth": fp["depth"]}, float(entry["height"])


def register_asset(lexicon_path: str, asset_id: str, asset_path: str) -> None:
    path = Path(lexicon_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if asset_id not in data["assets"]:
        raise KeyError(f"asset_id {asset_id!r} not in lexicon")
    data["assets"][asset_id]["path"] = asset_path
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_library.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/library.py foundry/tests/test_library.py
git commit -m "feat(foundry): lexicon envelope read + asset path registration"
```

---

### Task 4: Blender build script (bmesh → GLB)

**Files:**
- Create: `foundry/blender/build_asset.py`
- Create: `foundry/tests/test_build_blender.py`

**Interfaces:**
- Consumes: a spec JSON file (Task 1 format).
- Produces: a CLI invoked as `blender --background --python foundry/blender/build_asset.py -- <spec_json> <out_glb>`, writing `<out_glb>`. The exported table's bbox is `[top_width, leg_height + top_thickness, top_depth]` in GLB (Y-up) coordinates.

- [ ] **Step 1: Write the failing test (Blender integration, skips if absent)**

Create `foundry/tests/test_build_blender.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import trimesh

BLENDER = shutil.which("blender")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")


def test_build_exports_a_valid_table(tmp_path):
    out = str(tmp_path / "table.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", SPEC, out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    mesh = trimesh.load(out, force="mesh")
    ext = mesh.extents  # [width=X, height=Y, depth=Z]
    assert abs(ext[0] - 1.5) < 0.05, f"width {ext[0]}"
    assert abs(ext[2] - 1.0) < 0.05, f"depth {ext[2]}"
    assert abs(ext[1] - 0.75) < 0.05, f"height {ext[1]}"
    assert mesh.is_watertight
```

- [ ] **Step 2: Run the test to verify it fails (or skips)**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_build_blender.py -q`
Expected: with Blender installed, FAIL (`build_asset.py` missing → nonzero return / no GLB). Without Blender, SKIPPED.

- [ ] **Step 3: Implement the Blender build script**

Create `foundry/blender/build_asset.py`:

```python
"""Run INSIDE Blender:
    blender --background --python build_asset.py -- <spec_json> <out_glb>

Slice 1 builds the table from bmesh box primitives (manifold by construction).
Geometry-Nodes node-tree authoring is Slice 2; the spine is identical. Blender is
Z-up; the glTF exporter writes Y-up, so the GLB has height on Y, footprint on X/Z."""

import json
import sys

import bmesh
import bpy


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _add_box(bm, cx, cy, cz, sx, sy, sz):
    res = bmesh.ops.create_cube(bm, size=1.0)  # unit cube, -0.5..0.5
    for v in res["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz


def build_table(params):
    tw, td, tt = params["top_width"], params["top_depth"], params["top_thickness"]
    lh, lr, li = params["leg_height"], params["leg_radius"], params["leg_inset"]
    leg = lr * 2.0

    mesh = bpy.data.meshes.new("table")
    obj = bpy.data.objects.new("table", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, lh + tt / 2.0, tw, td, tt)  # top spans lh..lh+tt
    hx = tw / 2.0 - li - leg / 2.0
    hy = td / 2.0 - li - leg / 2.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            _add_box(bm, sx * hx, sy * hy, lh / 2.0, leg, leg, lh)  # legs 0..lh
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def apply_material(mesh, material_name):
    mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.40, 0.26, 0.15, 1.0)
    mesh.materials.append(mat)


def main():
    args = _argv()
    spec_path, out_glb = args[0], args[1]
    spec = json.load(open(spec_path, "r", encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = build_table(spec["params"])
    apply_material(mesh, spec.get("material", "default"))

    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=False)


main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_build_blender.py -q`
Expected: with Blender installed, PASS (1 passed). Without Blender, SKIPPED — in which case note it and proceed; the task is verified once Blender is present.

- [ ] **Step 5: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/blender/build_asset.py foundry/tests/test_build_blender.py
git commit -m "feat(foundry): headless Blender table build → GLB export"
```

---

### Task 5: Runner — full spine (compile → build → gate → register)

**Files:**
- Create: `foundry/runner.py`
- Create: `foundry/__main__.py`
- Create: `foundry/tests/test_runner.py`

**Interfaces:**
- Consumes: `compiler.compile_spec`/`load_spec`, `gate.gate_asset`/`GateResult`, `library.read_envelope`/`register_asset`.
- Produces: `runner.ForgeResult` (dataclass: `glb_path: str`, `gate` (a `GateResult`), `registered: bool`); `runner.forge(spec_path: str, lexicon_path: str, library_dir: str, blender: str = "blender") -> ForgeResult`. Registers (writes path) only when the gate passes; raises `RuntimeError` if the Blender build fails.

- [ ] **Step 1: Write the failing test (integration, skips if no Blender)**

Create `foundry/tests/test_runner.py`:

```python
import shutil
from pathlib import Path

import pytest

from library import LIVE_LEXICON
from runner import forge

BLENDER = shutil.which("blender")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")


def test_forge_table_end_to_end(tmp_path):
    lexicon = tmp_path / "asset_lexicon.json"
    shutil.copy(LIVE_LEXICON, lexicon)
    library_dir = tmp_path / "library"

    result = forge(SPEC, str(lexicon), str(library_dir))

    assert result.gate.passed, result.gate.reasons
    assert Path(result.glb_path).exists()
    assert result.glb_path.startswith(str(library_dir))
    assert result.registered

    import json
    data = json.loads(lexicon.read_text(encoding="utf-8"))
    assert data["assets"]["table"]["path"] == result.glb_path
```

- [ ] **Step 2: Run the test to verify it fails (or skips)**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_runner.py -q`
Expected: with Blender, FAIL (`No module named 'runner'`). Without Blender, SKIPPED.

- [ ] **Step 3: Implement the runner and CLI**

Create `foundry/runner.py`:

```python
"""The foundry spine: spec → compile → Blender build → gate → register.
Offline, serial, single-asset. Live-scene instancing is a later slice."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from compiler import compile_spec, load_spec
from gate import GateResult, gate_asset
from library import read_envelope, register_asset

_BUILD_SCRIPT = str(Path(__file__).resolve().parent / "blender" / "build_asset.py")


@dataclass
class ForgeResult:
    glb_path: str
    gate: GateResult
    registered: bool


def _build(spec_path: str, out_glb: str, blender: str) -> None:
    proc = subprocess.run(
        [blender, "--background", "--python", _BUILD_SCRIPT, "--", spec_path, out_glb],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not os.path.exists(out_glb):
        raise RuntimeError(f"Blender build failed:\n{proc.stderr or proc.stdout}")


def forge(spec_path: str, lexicon_path: str, library_dir: str, blender: str = "blender") -> ForgeResult:
    spec = compile_spec(load_spec(spec_path))
    footprint, height = read_envelope(lexicon_path, spec["asset_id"])

    Path(library_dir).mkdir(parents=True, exist_ok=True)
    out_glb = str(Path(library_dir) / f"{spec['asset_id']}.glb")

    _build(spec_path, out_glb, blender)
    result = gate_asset(out_glb, footprint, height)

    registered = False
    if result.passed:
        register_asset(lexicon_path, spec["asset_id"], out_glb)
        registered = True

    return ForgeResult(glb_path=out_glb, gate=result, registered=registered)
```

Create `foundry/__main__.py`:

```python
"""CLI: forge one asset.
    cd foundry && .venv/bin/python -m foundry <spec.json> <lexicon.json> <library_dir>
"""

import sys

from runner import forge


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python -m foundry <spec.json> <lexicon.json> <library_dir>")
        return 2
    result = forge(sys.argv[1], sys.argv[2], sys.argv[3])
    status = "PASS" if result.gate.passed else "FAIL"
    print(f"[{status}] {result.glb_path}  registered={result.registered}")
    for reason in result.gate.reasons:
        print(f"  - {reason}")
    return 0 if result.gate.passed else 1


sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_runner.py -q`
Expected: with Blender, PASS (1 passed). Without Blender, SKIPPED.

- [ ] **Step 5: Run the whole foundry suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/ -q`
Expected: all pure-python tests PASS; Blender integration tests PASS (if installed) or SKIP.

- [ ] **Step 6: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/runner.py foundry/__main__.py foundry/tests/test_runner.py
git commit -m "feat(foundry): runner spine compile→build→gate→register + CLI"
```

---

### Task 6: Render for eyeball verification

**Files:**
- Create: `foundry/blender/render_asset.py`
- Create: `foundry/tests/test_render_blender.py`

**Interfaces:**
- Consumes: a GLB path (Task 4/5 output).
- Produces: a CLI `blender --background --python foundry/blender/render_asset.py -- <glb> <out_png>` writing a PNG (Cycles CPU, robust headless, no GPU/display needed).

- [ ] **Step 1: Write the failing test (integration, skips if no Blender)**

Create `foundry/tests/test_render_blender.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BLENDER = shutil.which("blender")
RENDER = str(Path(__file__).resolve().parents[1] / "blender" / "render_asset.py")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")


def test_render_writes_png(tmp_path):
    glb = str(tmp_path / "table.glb")
    subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", SPEC, glb],
        capture_output=True, text=True, timeout=180, check=True,
    )
    png = str(tmp_path / "table.png")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", RENDER, "--", glb, png],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(png) and os.path.getsize(png) > 0
```

- [ ] **Step 2: Run the test to verify it fails (or skips)**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_render_blender.py -q`
Expected: with Blender, FAIL (render script missing). Without Blender, SKIPPED.

- [ ] **Step 3: Implement the render script**

Create `foundry/blender/render_asset.py`:

```python
"""Run INSIDE Blender:
    blender --background --python render_asset.py -- <glb> <out_png>

Renders a framed thumbnail of the asset with Cycles on CPU — reliable headless
with no GPU/display. Low samples/resolution: this is for eyeball verification,
not beauty."""

import math
import sys

import bpy
from mathutils import Vector


def _argv():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def main():
    glb, out_png = _argv()[0], _argv()[1]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)  # glTF import returns to Z-up in Blender

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.filepath = out_png

    target = bpy.data.objects.new("target", None)
    scene.collection.objects.link(target)
    target.location = (0.0, 0.0, 0.4)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = Vector((2.4, -2.4, 1.7))
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"

    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(40))

    bpy.ops.render.render(write_still=True)


main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_render_blender.py -q`
Expected: with Blender, PASS (1 passed). Without Blender, SKIPPED.

- [ ] **Step 5: Forge and render the table for real (manual eyeball verification)**

```bash
cd /home/mrg/dev/games/Forge/foundry
cp ../engine/devforge/spatial/asset_lexicon.json /tmp/lex_test.json
.venv/bin/python -m foundry specs/table.json /tmp/lex_test.json /tmp/forge_lib
blender --background --python blender/render_asset.py -- /tmp/forge_lib/table.glb /tmp/forge_lib/table.png
```
Expected: `[PASS] /tmp/forge_lib/table.glb registered=True`, and `/tmp/forge_lib/table.png` shows a recognizable table (flat top on four legs, wood-brown). **This PNG is the slice's eyeball-verification deliverable — hand it to the reviewer.**

- [ ] **Step 6: Commit**

```bash
cd /home/mrg/dev/games/Forge
git add foundry/blender/render_asset.py foundry/tests/test_render_blender.py
git commit -m "feat(foundry): Cycles-CPU render for asset eyeball verification"
```

---

## Self-Review

**Spec coverage (against the slice-1 section of the design spec):**
- Hand-authored generator → Task 4 (bmesh; GeoNodes deferred per Global Constraints). ✓
- Hand-written asset-spec → `foundry/specs/table.json` (Task 1). ✓
- AssetCompiler path → Task 1. ✓
- Blender headless build + export → Task 4. ✓
- Deterministic gate (manifold, poly budget, bounds vs lexicon footprint/height, ~material) → Task 2 (material-from-palette is enforced at the *spec* layer in the compiler, Task 1, since slice 1 has one material; GLB-side material validation deferred with the style grammar). ✓
- Lexicon `path` registration → Task 3 + wired in Task 5. ✓
- Live-pipeline consumption → **explicitly deferred** (Global Constraints), replaced by render verification → Task 6. ✓
- Verify by eye → Task 6 Step 5. ✓

**Placeholder scan:** no TBD/TODO; every code step has complete code; commands have expected output. ✓

**Type consistency:** `GateResult(passed, reasons)` consistent across gate.py, runner.py, tests. `forge(spec_path, lexicon_path, library_dir, blender=)` and `ForgeResult(glb_path, gate, registered)` consistent in runner.py, __main__.py, test_runner. `read_envelope`→`(footprint{"width","depth"}, height)` consistent in library.py, runner.py. `compile_spec`→`{"asset_id","generator","material","params"}` consistent in compiler.py, runner.py. ✓

**Cross-task path note:** the foundry tests run from `foundry/` (bare imports via `conftest.py`); the live lexicon is reached from foundry code as `parents[1]/engine/devforge/spatial/asset_lexicon.json`. Verified consistent across `library.py`, the tests, and the Task 6 manual command.
