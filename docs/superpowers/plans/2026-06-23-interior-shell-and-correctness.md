# Interior Correctness + Shell/Roof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the interior `quest` scene's flat box-shell + stretched grey textures with a Blender-generated king-post-truss room shell (stone walls, timber floor/beams, triplanar materials), rest props on the floor, and carve the NPC navmesh around furniture.

**Architecture:** Pure-Python `navmesh.py` (footprint carving) and a small floor-rest helper land first with full unit tests. Two Blender generators (`shell_materials.py` textures, `build_room_shell.py` geometry) produce a cached GLB + PBR texture set. `room_shell.py` orchestrates the cache + Blender subprocess with a Blender-unavailable fallback. `scene_compiler.py` consumes the GLB with world-space triplanar materials and the carved navmesh, falling back to the current inline box shell when no GLB is available.

**Tech Stack:** Python 3 (`foundry/.venv`), numpy, trimesh, Blender (Cycles, CPU/HIP), shapely + mapbox_earcut (2D carving), Godot 4 (headless smoke), pytest.

## Global Constraints

- **Determinism:** identical inputs → identical output; no wall-clock, no unseeded RNG. GPU/Cycles bakes are NOT bit-exact, so the **cache key is authoritative** — build once, reuse.
- **Never hard-fail a build:** Blender missing/fails → `room_shell` returns `None` → `scene_compiler` emits the existing inline box shell. Carve empty/fails → fall back to the flat navmesh quad.
- **No authored assets:** all geometry/textures are generated procedurally.
- **New deps:** `shapely`, `mapbox_earcut` added to `foundry/requirements.txt`.
- **Cache invalidation:** a module-level `GEN_VERSION` string in `room_shell.py`; bumping it invalidates all cached shells.
- **Tests:** run from `foundry/` via `.venv/bin/python -m pytest`. Pure-Python tasks are fully unit-tested by the implementer; **Blender-gated tests `pytest.importorskip`/skip when `blender` is absent** — the actual bake + visual verification is run by the orchestrator (see our testing split: CLI owns unit+smoke, orchestrator owns Blender/visual).
- **Style:** match surrounding `scene_compiler.py` conventions; keep files focused (one responsibility).

---

### Task 1: `foundry/navmesh.py` — walkable-polygon carving

**Files:**
- Create: `foundry/navmesh.py`
- Create: `foundry/tests/test_navmesh.py`
- Modify: `foundry/requirements.txt` (add `shapely`, `mapbox_earcut`)

**Interfaces:**
- Produces:
  - `Obstacle = tuple[float, float, float, float]` — `(cx, cz, half_x, half_z)` AABB footprint in XZ.
  - `carve_walkable(room_w: float, room_d: float, obstacles: list[Obstacle], agent_radius: float = 0.3, wall_margin: float = 1.2) -> tuple[list[tuple[float,float,float]], list[list[int]]]` — returns `(vertices, polygons)`; `vertices` are `(x, 0.0, z)` triples, `polygons` are triangles as index triples. Returns `([], [])` if the walkable region is empty.
  - `point_in_polygons(px: float, pz: float, vertices, polygons) -> bool` — test helper (also used by Task 6 tests).

- [ ] **Step 1: Add dependencies**

Append to `foundry/requirements.txt`:
```
shapely        # 2D polygon boolean for navmesh carving (foundry/navmesh.py)
mapbox_earcut  # triangulation of walkable polygon-with-holes
```
Install: `cd foundry && .venv/bin/pip install shapely mapbox_earcut`

- [ ] **Step 2: Write the failing tests**

```python
# foundry/tests/test_navmesh.py
import numpy as np
import pytest

pytest.importorskip("shapely")
pytest.importorskip("mapbox_earcut")

from navmesh import carve_walkable, point_in_polygons


def test_empty_obstacles_walkable_center():
    verts, polys = carve_walkable(8.0, 6.0, [])
    assert verts and polys
    # center of the room is walkable
    assert point_in_polygons(0.0, 0.0, verts, polys)
    # a point outside the inset (near the wall) is NOT walkable
    assert not point_in_polygons(0.0, 2.9, verts, polys)  # d/2=3, margin 1.2 -> edge ~1.8


def test_obstacle_carves_hole():
    # one 1x1 obstacle at the center, inflated by agent_radius -> center blocked
    obs = [(0.0, 0.0, 0.5, 0.5)]
    verts, polys = carve_walkable(8.0, 6.0, obs)
    assert not point_in_polygons(0.0, 0.0, verts, polys)   # inside the prop -> blocked
    assert point_in_polygons(2.5, 0.0, verts, polys)        # clear floor -> walkable


def test_determinism():
    obs = [(1.0, 0.5, 0.4, 0.4), (-1.5, -1.0, 0.3, 0.6)]
    a = carve_walkable(8.0, 6.0, obs)
    b = carve_walkable(8.0, 6.0, list(reversed(obs)))
    assert a == b  # sorted internally -> order-independent, identical output


def test_over_furnished_returns_empty():
    # one obstacle larger than the whole inset region -> nothing walkable
    obs = [(0.0, 0.0, 50.0, 50.0)]
    verts, polys = carve_walkable(8.0, 6.0, obs)
    assert verts == [] and polys == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_navmesh.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'navmesh'`.

- [ ] **Step 4: Implement `foundry/navmesh.py`**

```python
"""foundry.navmesh — build-time walkable navmesh carving.

carve_walkable() returns the room's walkable floor polygon (inset by the wall
margin) MINUS each prop footprint (inflated by the agent radius), triangulated
for a Godot NavigationMesh. Pure Python + deterministic. First reusable
primitive of the level-design branch.
"""
from __future__ import annotations

import numpy as np
from mapbox_earcut import triangulate_float64
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

Obstacle = tuple[float, float, float, float]  # (cx, cz, half_x, half_z)


def carve_walkable(room_w, room_d, obstacles, agent_radius=0.3, wall_margin=1.2):
    inset_w = room_w / 2.0 - wall_margin
    inset_d = room_d / 2.0 - wall_margin
    if inset_w <= 0 or inset_d <= 0:
        return [], []
    base = box(-inset_w, -inset_d, inset_w, inset_d)

    rects = []
    for cx, cz, hx, hz in sorted(obstacles):  # sorted -> order-independent
        rects.append(box(cx - hx - agent_radius, cz - hz - agent_radius,
                         cx + hx + agent_radius, cz + hz + agent_radius))
    walkable = base.difference(unary_union(rects)) if rects else base

    if walkable.is_empty or walkable.area <= 1e-6:
        return [], []

    # Normalize to a list of polygons (difference may yield a MultiPolygon)
    polys_in = list(getattr(walkable, "geoms", [walkable]))

    vertices: list[tuple[float, float, float]] = []
    polygons: list[list[int]] = []
    for poly in polys_in:
        _triangulate_into(poly, vertices, polygons)
    return vertices, polygons


def _triangulate_into(poly: Polygon, vertices, polygons):
    base_idx = len(vertices)
    rings = [list(poly.exterior.coords)[:-1]]          # drop closing dup
    rings += [list(r.coords)[:-1] for r in poly.interiors]

    flat: list[tuple[float, float]] = []
    ring_ends: list[int] = []
    for ring in rings:
        flat.extend(ring)
        ring_ends.append(len(flat))
    verts2d = np.array(flat, dtype=np.float64)
    tris = triangulate_float64(verts2d, np.array(ring_ends, dtype=np.uint32))

    for (x, z) in flat:
        vertices.append((round(float(x), 4), 0.0, round(float(z), 4)))
    for i in range(0, len(tris), 3):
        polygons.append([base_idx + int(tris[i]),
                         base_idx + int(tris[i + 1]),
                         base_idx + int(tris[i + 2])])


def point_in_polygons(px, pz, vertices, polygons) -> bool:
    for tri in polygons:
        ax, _, az = vertices[tri[0]]
        bx, _, bz = vertices[tri[1]]
        cx, _, cz = vertices[tri[2]]
        d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
        if abs(d) < 1e-12:
            continue
        a = ((bz - cz) * (px - cx) + (cx - bx) * (pz - cz)) / d
        b = ((cz - az) * (px - cx) + (ax - cx) * (pz - cz)) / d
        c = 1 - a - b
        if -1e-9 <= a <= 1 + 1e-9 and -1e-9 <= b <= 1 + 1e-9 and -1e-9 <= c <= 1 + 1e-9:
            return True
    return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_navmesh.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add foundry/navmesh.py foundry/tests/test_navmesh.py foundry/requirements.txt
git commit -m "feat(navmesh): build-time walkable carving (room minus inflated prop footprints)"
```

---

### Task 2: Floor-rest helper + prop placement (kills floating)

**Files:**
- Modify: `foundry/scene_compiler.py` (add `rest_offset`; apply at prop placement)
- Create/Modify: `foundry/tests/test_scene_compiler_rest.py`

**Interfaces:**
- Produces: `rest_offset(aabb_min_y: float) -> float` — returns `-aabb_min_y`, the Y to add to a prop transform so its base sits on the floor (y=0).
- Consumes: the per-prop AABB already computed for `collision_info` in `scene_compiler.py` (the prop's local-space minimum Y).

- [ ] **Step 1: Write the failing test**

```python
# foundry/tests/test_scene_compiler_rest.py
from scene_compiler import rest_offset

def test_rest_offset_centered_origin():
    # GLB whose origin is at its center, half-height 0.5 -> min_y = -0.5
    assert rest_offset(-0.5) == 0.5

def test_rest_offset_base_origin():
    # GLB already authored with base at origin -> min_y = 0 -> no shift
    assert rest_offset(0.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler_rest.py -q`
Expected: FAIL with `ImportError: cannot import name 'rest_offset'`.

- [ ] **Step 3: Implement the helper and apply it**

Add near the other placement helpers in `foundry/scene_compiler.py`:
```python
def rest_offset(aabb_min_y: float) -> float:
    """Y to add to a prop transform so its AABB base rests on the floor (y=0).
    Props whose origin is at their centre float without this offset."""
    return -float(aabb_min_y)
```

Then, at the prop-placement transform (the `Transform3D(... x, y, z)` line that
positions each manifest entity — locate via the `collision_info` AABB block,
~`scene_compiler.py:1150-1430`): replace the prop's `y` term with
`y + rest_offset(aabb_min_y)`, where `aabb_min_y` is the local minimum Y already
read for that entity's collision shape. Surface-mounted entities (wall
`painting`s) keep their existing Y — guard with the existing category check used
for wall-mounting.

- [ ] **Step 4: Run unit + full compiler suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler_rest.py tests/test_scene_compiler.py -q`
Expected: PASS (the rest tests pass; existing compiler tests still pass — adjust any test that asserted the old floating Y).

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler_rest.py
git commit -m "fix(scene): rest props on the floor via -aabb_min_y (no more floating)"
```

---

### Task 3: `foundry/blender/shell_materials.py` — stone + timber PBR (fixes texture quality)

> **STATUS: DONE (orchestrator, committed `0873c46`). Do not re-implement.** Textures baked at
> 1024² and committed to `foundry/godot_template/assets/shell_{stone,timber}_*.png`
> (luminance spread 0.65/0.51). Implementation differs from the sketch below (Blender 5.1
> socket names: "Factor" not "Fac"); the committed file is authoritative.

**Files:**
- Create: `foundry/blender/shell_materials.py`
- Create: `foundry/tests/test_shell_materials.py` (Blender-gated)
- Remove: `foundry/blender/build_shell_textures.py` (superseded)

**Interfaces:**
- Produces (run inside Blender): `blender --background --python shell_materials.py -- <out_dir> [res]`
  writes `shell_stone_{albedo,normal,orm}.png` and `shell_timber_{albedo,normal,orm}.png` to `<out_dir>`.
- Importable helpers: `build_stone_nodes(nodes, links, seed)` and `build_timber_nodes(nodes, links, seed)` returning `(color_socket, height_socket)`.

**Why (regression we are killing):** the old generator made a single-octave Voronoi(8)+Noise(12) ramp between `(0.45,0.45,0.47)`→`(0.30,0.30,0.32)` — ~0.15 luminance spread, zero saturation, no structure; normal strength 0.2; floor==wall==granite.

- [ ] **Step 1: Write the Blender-gated structural test**

```python
# foundry/tests/test_shell_materials.py
import os, shutil, subprocess, sys
from pathlib import Path
import pytest

blender = shutil.which("blender")
pytestmark = pytest.mark.skipif(blender is None, reason="blender not installed")

GEN = Path(__file__).resolve().parent.parent / "blender" / "shell_materials.py"

def test_generates_stone_and_timber_with_contrast(tmp_path):
    subprocess.run([blender, "--background", "--python", str(GEN), "--", str(tmp_path), "512"],
                   check=True, capture_output=True, timeout=300)
    names = ["shell_stone_albedo.png", "shell_stone_normal.png", "shell_stone_orm.png",
             "shell_timber_albedo.png", "shell_timber_normal.png", "shell_timber_orm.png"]
    for n in names:
        assert (tmp_path / n).exists(), f"missing {n}"
    # Anti-regression: albedo must have real contrast (the old grey mush had ~0.15 spread)
    from PIL import Image
    import numpy as np
    for surf in ("stone", "timber"):
        a = np.asarray(Image.open(tmp_path / f"shell_{surf}_albedo.png").convert("RGB")) / 255.0
        lum = a @ [0.2126, 0.7152, 0.0722]
        spread = float(lum.max() - lum.min())
        assert spread >= 0.30, f"{surf} albedo too flat ({spread:.2f}) — grey-mush regression"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_shell_materials.py -q`
Expected: FAIL (`shell_materials.py` missing) — or SKIP where Blender is absent (orchestrator runs it with Blender).

- [ ] **Step 3: Implement `shell_materials.py`**

Reuse the bake scaffold from the old `build_shell_textures.py` (plane + smart-UV unwrap, EMIT bake for albedo, NORMAL bake, AO→ORM pack) but replace the node graphs and raise quality. Key changes vs the old file:

```python
# stone: multi-octave + ashlar joints + real color/contrast
def build_stone_nodes(nodes, links, seed):
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping"); mp.vector_type = "TEXTURE"
    mp.inputs["Scale"].default_value = (3, 3, 3)
    mp.inputs["Location"].default_value = (seed, seed, 0)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    # large-scale tone variation (3+ octaves)
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 4.0
    n.inputs["Detail"].default_value = 8.0      # multi-octave (was 4)
    n.inputs["Roughness"].default_value = 0.65
    links.new(mp.outputs["Vector"], n.inputs["Vector"])

    # ashlar block joints: Voronoi distance -> dark mortar lines
    v = nodes.new("ShaderNodeTexVoronoi")
    v.feature = "DISTANCE_TO_EDGE"; v.inputs["Scale"].default_value = 6.0
    links.new(mp.outputs["Vector"], v.inputs["Vector"])
    joints = nodes.new("ShaderNodeValToRGB")     # narrow ramp -> thin dark joints
    j = joints.color_ramp.elements
    j[0].position = 0.0;  j[0].color = (0.05, 0.05, 0.05, 1)   # mortar (dark)
    j[1].position = 0.06; j[1].color = (1, 1, 1, 1)            # stone face
    links.new(v.outputs["Distance"], joints.inputs["Fac"])

    # stone color with CONTRAST (warm grey, spread >= 0.35)
    face = nodes.new("ShaderNodeValToRGB")
    f = face.color_ramp.elements
    f[0].position = 0.0; f[0].color = (0.34, 0.32, 0.30, 1)
    f[1].position = 1.0; f[1].color = (0.78, 0.75, 0.70, 1)
    links.new(n.outputs["Fac"], face.inputs["Fac"])

    mul = nodes.new("ShaderNodeMixRGB"); mul.blend_type = "MULTIPLY"
    mul.inputs["Fac"].default_value = 1.0
    links.new(face.outputs["Color"], mul.inputs["Color1"])
    links.new(joints.outputs["Color"], mul.inputs["Color2"])
    # height for the normal bake = joints (recessed mortar) + noise grain
    return mul.outputs["Color"], joints.outputs["Color"]


# timber: directional grain + plank seams
def build_timber_nodes(nodes, links, seed):
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping"); mp.vector_type = "TEXTURE"
    mp.inputs["Scale"].default_value = (1.0, 8.0, 1.0)   # stretch along grain
    mp.inputs["Location"].default_value = (seed, 0, 0)
    links.new(tc.outputs["Object"], mp.inputs["Vector"])

    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 6.0
    grain.inputs["Detail"].default_value = 6.0
    links.new(mp.outputs["Vector"], grain.inputs["Vector"])

    planks = nodes.new("ShaderNodeTexWave")    # plank seams across the floor
    planks.wave_type = "BANDS"; planks.inputs["Scale"].default_value = 1.5
    links.new(tc.outputs["Object"], planks.inputs["Vector"])
    seams = nodes.new("ShaderNodeValToRGB")
    s = seams.color_ramp.elements
    s[0].position = 0.0;  s[0].color = (0.08, 0.05, 0.03, 1)   # seam (dark)
    s[1].position = 0.04; s[1].color = (1, 1, 1, 1)
    links.new(planks.outputs["Color"], seams.inputs["Fac"])

    wood = nodes.new("ShaderNodeValToRGB")
    w = wood.color_ramp.elements
    w[0].position = 0.0; w[0].color = (0.20, 0.11, 0.05, 1)    # dark oak
    w[1].position = 1.0; w[1].color = (0.55, 0.36, 0.18, 1)    # light oak (spread)
    links.new(grain.outputs["Fac"], wood.inputs["Fac"])

    mul = nodes.new("ShaderNodeMixRGB"); mul.blend_type = "MULTIPLY"
    mul.inputs["Fac"].default_value = 1.0
    links.new(wood.outputs["Color"], mul.inputs["Color1"])
    links.new(seams.outputs["Color"], mul.inputs["Color2"])
    return mul.outputs["Color"], seams.outputs["Color"]
```

Bake harness requirements (in `main()`):
- Resolution from argv (default 1024).
- Normal bake: `ShaderNodeBump` strength `0.8` (was 0.2), distance `0.15`.
- AO bake pass: `scene.cycles.samples = 16` (was 1) to avoid AO noise; EMIT albedo bake can stay 1 sample.
- Two surfaces: `stone` (walls/ceiling boards) and `timber` (floor/beams), each on its own
  unit plane; save with `_save_textures(..., prefix)` using the `shell_{stone,timber}_*` names.

- [ ] **Step 4 (orchestrator): Bake + verify**

Orchestrator runs: `blender --background --python foundry/blender/shell_materials.py -- /tmp/shelltex 1024`
then `pytest tests/test_shell_materials.py -q` (contrast guard) and eyeballs the 6 PNGs.

- [ ] **Step 5: Commit**

```bash
git rm foundry/blender/build_shell_textures.py
git add foundry/blender/shell_materials.py foundry/tests/test_shell_materials.py
git commit -m "feat(shell): procedural stone+timber PBR with structure/contrast (replaces grey mush)"
```

---

### Task 4: `foundry/blender/build_room_shell.py` — king-post truss geometry

> **STATUS: DONE (orchestrator, committed `c17b60b`). Do not re-implement.** The committed file
> uses clean `mathutils.Matrix` + `create_cube(matrix=...)` beams (not the manual-trig sketch
> below) and exports a Y-up GLB with `stone`/`timber` slots, verified at 8×6×3. Interface for
> Task 5: `blender --background --python build_room_shell.py -- <out_glb> <w> <d> <wall_h> <theme> <seed>`.

**Files:**
- Create: `foundry/blender/build_room_shell.py`
- Create: `foundry/tests/test_build_room_shell.py` (Blender-gated)

**Interfaces:**
- Produces (run inside Blender): `blender --background --python build_room_shell.py -- <out_glb> <w> <d> <wall_height> <theme> <seed>` → one `.glb` with exactly two material slots named `stone` and `timber`, origin at room centre on the floor (y=0 at floor top).
- Geometry params default (override via future kwargs): `pitch_ratio=0.4`, `beam_size=0.15`, `bevel=0.01`, `trusses_per_m=0.6` (min 2 trusses), `wall_t=0.2`, `floor_t=0.1`.

- [ ] **Step 1: Write the Blender-gated test**

```python
# foundry/tests/test_build_room_shell.py
import shutil, subprocess
from pathlib import Path
import pytest

blender = shutil.which("blender")
pytestmark = pytest.mark.skipif(blender is None, reason="blender not installed")
GEN = Path(__file__).resolve().parent.parent / "blender" / "build_room_shell.py"

def test_builds_glb_with_two_material_slots(tmp_path):
    out = tmp_path / "shell.glb"
    subprocess.run([blender, "--background", "--python", str(GEN), "--",
                    str(out), "8", "6", "3", "study", "0"],
                   check=True, capture_output=True, timeout=300)
    assert out.exists() and out.stat().st_size > 0
    import trimesh
    scene = trimesh.load(str(out))
    mats = set()
    for g in (scene.geometry.values() if hasattr(scene, "geometry") else [scene]):
        m = getattr(g.visual, "material", None)
        if m is not None and getattr(m, "name", None):
            mats.add(m.name)
    assert {"stone", "timber"} <= mats, f"expected stone+timber slots, got {mats}"
```

- [ ] **Step 2: Run to verify it fails / skips**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_build_room_shell.py -q`
Expected: FAIL (missing module) where Blender present; SKIP otherwise.

- [ ] **Step 3: Implement `build_room_shell.py`**

Build with `bmesh`/box primitives (deterministic), assign two materials by name, export GLB:
```python
"""blender --background --python build_room_shell.py -- <out_glb> <w> <d> <wall_h> <theme> <seed>
Generates floor + 4 walls + king-post truss roof as one GLB with 'stone' and
'timber' material slots. Geometry only; materials are flat-named placeholders —
scene_compiler applies the real triplanar StandardMaterial3D per slot."""
import sys, bpy, bmesh

def _args():
    a = sys.argv; a = a[a.index("--")+1:]
    out, w, d, wh, theme, seed = a[0], float(a[1]), float(a[2]), float(a[3]), a[4], float(a[5])
    return out, w, d, wh, theme, seed

def _mat(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = False; m.diffuse_color = (*rgb, 1.0); return m

def _box(bm, cx, cy, cz, sx, sy, sz):
    m = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in m:
        v.co.x = v.co.x * sx + cx; v.co.y = v.co.y * sy + cy; v.co.z = v.co.z * sz + cz

def main():
    out, w, d, wh, theme, seed = _args()
    pitch_ratio, beam, wall_t, floor_t = 0.4, 0.15, 0.2, 0.1
    apex = wh + w * pitch_ratio
    n_truss = max(2, int(round(d * 0.6)))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    stone = _mat("stone", (0.6, 0.58, 0.54)); timber = _mat("timber", (0.4, 0.26, 0.13))

    # NOTE: Blender is Z-up; export converts to glTF Y-up. Build with Z as height.
    bm_stone = bmesh.new(); bm_timber = bmesh.new()
    # floor (timber), y=0 at top -> centre z = -floor_t/2
    _box(bm_timber, 0, 0, -floor_t/2, w, d, floor_t)
    # 4 walls (stone) to plate height wh
    _box(bm_stone, 0,  d/2, wh/2, w, wall_t, wh)
    _box(bm_stone, 0, -d/2, wh/2, w, wall_t, wh)
    _box(bm_stone,  w/2, 0, wh/2, wall_t, d, wh)
    _box(bm_stone, -w/2, 0, wh/2, wall_t, d, wh)
    # trusses (timber): rafters + tie-beam + king-post, repeated along Y(=d)
    import math
    ys = [(-d/2 + wall_t) + i*((d - 2*wall_t)/(n_truss-1)) for i in range(n_truss)]
    rlen = math.hypot(w/2, apex-wh); rang = math.atan2(apex-wh, w/2)
    for y in ys:
        _box(bm_timber, 0, y, wh, w, beam, beam)                  # tie-beam at plate
        _box(bm_timber, 0, y, (wh+apex)/2, beam, beam, apex-wh)   # king-post
        for sgn in (-1, 1):                                        # two rafters
            verts = bmesh.ops.create_cube(bm_timber, size=1.0)["verts"]
            for v in verts:
                v.co.x *= rlen; v.co.y *= beam; v.co.z *= beam
            for v in verts:
                x0 = v.co.x; v.co.x = sgn*(math.cos(rang)*x0) ; v.co.z = math.sin(rang)*x0
                v.co.x += sgn*w/4; v.co.y += y; v.co.z += (wh+apex)/2
    # roof boards (stone-as-slate): two sloped planes over the rafters
    for sgn in (-1, 1):
        verts = bmesh.ops.create_cube(bm_stone, size=1.0)["verts"]
        for v in verts:
            v.co.x *= rlen; v.co.y *= d; v.co.z *= 0.05
        for v in verts:
            x0 = v.co.x; v.co.x = sgn*(math.cos(rang)*x0); v.co.z = math.sin(rang)*x0
            v.co.x += sgn*w/4; v.co.z += (wh+apex)/2 + beam

    def _obj(bm, name, mat):
        me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(ob)
        me.materials.append(mat); return ob
    _obj(bm_stone, "shell_stone", stone); _obj(bm_timber, "shell_timber", timber)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True,
                              export_yup=True)

main()
```
(Rafter/board transforms are approximate — the orchestrator tunes them against screenshots; the test only asserts structure + two material slots.)

- [ ] **Step 4 (orchestrator): Build + eyeball**

Orchestrator runs the generator for `8 6 3 study 0`, loads the GLB, screenshots for the user.

- [ ] **Step 5: Commit**

```bash
git add foundry/blender/build_room_shell.py foundry/tests/test_build_room_shell.py
git commit -m "feat(shell): king-post truss room-shell GLB generator (stone+timber slots)"
```

---

### Task 5: `foundry/room_shell.py` — cache + Blender orchestration + fallback

**Files:**
- Create: `foundry/room_shell.py`
- Create: `foundry/tests/test_room_shell.py`

**Interfaces:**
- Produces: `ensure_room_shell(w, d, wall_height, theme, seed=0, cache_root=None) -> pathlib.Path | None` — returns the cached/built GLB path, or `None` if Blender is unavailable or generation fails.
- Module constant: `GEN_VERSION: str` (bump to invalidate cache).

- [ ] **Step 1: Write the failing tests (mock Blender)**

```python
# foundry/tests/test_room_shell.py
from pathlib import Path
import room_shell

def test_cache_hit_skips_blender(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(room_shell, "_run_blender", lambda *a, **k: calls.append(a) or True)
    # pre-create the cached glb so it's a hit
    key_dir = room_shell._cache_dir(8, 6, 3, "study", 0, tmp_path)
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "shell.glb").write_bytes(b"GLB")
    p = room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path)
    assert p and p.exists() and calls == []   # no blender call on hit

def test_cache_miss_calls_blender(tmp_path, monkeypatch):
    def fake(out_glb, *a, **k):
        Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
        Path(out_glb).write_bytes(b"GLB"); return True
    monkeypatch.setattr(room_shell, "_run_blender", fake)
    p = room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path)
    assert p and p.exists()

def test_blender_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(room_shell.shutil, "which", lambda _: None)
    assert room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path) is None

def test_generation_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(room_shell, "_run_blender", lambda *a, **k: False)
    assert room_shell.ensure_room_shell(8, 6, 3, "study", 0, cache_root=tmp_path) is None

def test_key_stable_and_version_sensitive(tmp_path):
    a = room_shell._cache_dir(8, 6, 3, "study", 0, tmp_path)
    b = room_shell._cache_dir(8.0, 6.0, 3.0, "study", 0, tmp_path)
    assert a == b
    c = room_shell._cache_dir(8, 6, 3, "tavern", 0, tmp_path)
    assert a != c
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_shell.py -q`
Expected: FAIL (`No module named 'room_shell'`).

- [ ] **Step 3: Implement `foundry/room_shell.py`**

```python
"""foundry.room_shell — orchestrate the Blender room-shell GLB with caching.

ensure_room_shell() returns a cached GLB for (w, d, wall_height, theme, seed),
building it via Blender on a cache miss. Returns None if Blender is unavailable
or generation fails (caller falls back to the inline box shell). The cache key
is authoritative (GPU bakes are not bit-exact)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

GEN_VERSION = "1"
_DEFAULT_CACHE = Path.home() / ".cache" / "forge" / "room_shell"
_GEN = Path(__file__).resolve().parent / "blender" / "build_room_shell.py"
_TIMEOUT = 180


def _cache_dir(w, d, wall_height, theme, seed, cache_root=None) -> Path:
    root = Path(cache_root) if cache_root else _DEFAULT_CACHE
    key = f"{round(float(w),2)}|{round(float(d),2)}|{round(float(wall_height),2)}|{theme}|{int(seed)}|{GEN_VERSION}"
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return root / h


def _run_blender(out_glb, w, d, wall_height, theme, seed) -> bool:
    blender = shutil.which("blender")
    if not blender:
        return False
    try:
        r = subprocess.run(
            [blender, "--background", "--python", str(_GEN), "--",
             str(out_glb), str(w), str(d), str(wall_height), str(theme), str(seed)],
            capture_output=True, timeout=_TIMEOUT)
        return r.returncode == 0 and Path(out_glb).exists()
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_room_shell(w, d, wall_height, theme, seed=0, cache_root=None):
    if shutil.which("blender") is None:
        return None
    d_dir = _cache_dir(w, d, wall_height, theme, seed, cache_root)
    glb = d_dir / "shell.glb"
    if glb.exists():
        return glb
    d_dir.mkdir(parents=True, exist_ok=True)
    if _run_blender(glb, w, d, wall_height, theme, seed):
        return glb
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_room_shell.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/room_shell.py foundry/tests/test_room_shell.py
git commit -m "feat(shell): room_shell cache + Blender orchestration with unavailable-fallback"
```

---

### Task 6: `scene_compiler.py` integration — GLB shell + triplanar + carved navmesh + fallback

**Files:**
- Modify: `foundry/scene_compiler.py`
- Modify: `foundry/tests/test_scene_compiler.py` (add cases)

**Interfaces:**
- Consumes: `room_shell.ensure_room_shell(...)`, `navmesh.carve_walkable(...)`, `rest_offset(...)` (Task 2).
- Produces: a `.tscn` that, when a shell GLB is available, instances it and assigns two
  triplanar `StandardMaterial3D`s (stone, timber); the `NavigationMesh` vertices/polygons come
  from `carve_walkable`. When no GLB is available, the existing inline box shell + flat navmesh
  quad are emitted unchanged.

- [ ] **Step 1: Write failing tests (inject stubs)**

```python
# add to foundry/tests/test_scene_compiler.py
def test_shell_glb_path_emits_instance_and_triplanar(monkeypatch, tmp_path):
    import scene_compiler, room_shell
    glb = tmp_path / "shell.glb"; glb.write_bytes(b"GLB")
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: glb)
    tscn = scene_compiler.compile_scene(_minimal_manifest(), room_size={"w": 8, "d": 6}, theme="study")
    assert "shell.glb" in tscn
    assert "uv1_triplanar = true" in tscn and "uv1_world_triplanar = true" in tscn

def test_no_glb_falls_back_to_box_shell(monkeypatch):
    import scene_compiler, room_shell
    monkeypatch.setattr(room_shell, "ensure_room_shell", lambda *a, **k: None)
    tscn = scene_compiler.compile_scene(_minimal_manifest(), room_size={"w": 8, "d": 6}, theme="study")
    assert "floor_vis_mesh" in tscn  # inline box shell still present

def test_navmesh_uses_carved_vertices(monkeypatch):
    import scene_compiler, navmesh
    monkeypatch.setattr(navmesh, "carve_walkable",
                        lambda *a, **k: ([(1.0, 0.0, 1.0), (2.0, 0.0, 1.0), (1.5, 0.0, 2.0)], [[0, 1, 2]]))
    tscn = scene_compiler.compile_scene(_minimal_manifest(), room_size={"w": 8, "d": 6}, theme="study")
    assert "1, 0, 1" in tscn  # carved vertex present in NavigationMesh
```
(Use the test file's existing manifest/`compile_scene` helpers; `_minimal_manifest` mirrors them.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -k "shell or navmesh" -q`
Expected: FAIL (triplanar/GLB/carved output not present yet).

- [ ] **Step 3: Implement the integration**

In `scene_compiler.py`:
1. Call `room_shell.ensure_room_shell(room_w, room_d, _ROOM_HEIGHT, theme)`. If a path is
   returned: copy it into the build's `assets/` (scaffold step) and emit a `Node3D` instancing
   it; define two `StandardMaterial3D`s (stone, timber) with
   `uv1_triplanar = true`, `uv1_world_triplanar = true`, `uv1_scale = Vector3(s, s, s)` (s≈1.0),
   and the `shell_{stone,timber}_*` textures; assign per material slot. **Remove** the inline
   `*_vis_mesh`/`ceiling_mesh` emission on this branch.
2. If `None`: emit the inline box shell, but point its materials at the **committed** textures
   — floor → `res://assets/shell_timber_*`, walls + ceiling → `res://assets/shell_stone_*`
   (triplanar too). This improves the fallback and lets the old
   `shell_{floor,wall,ceiling}_*.png` be deleted (they are obsolete).
3. Replace the hardcoded flat 2-triangle `nav_mesh` `vertices`/`polygons` with the output of
   `navmesh.carve_walkable(room_w, room_d, _prop_footprints(manifest))`, where `_prop_footprints`
   maps each collidable (non-decor) entity to `(cx, cz, half_x, half_z)` from its placement +
   AABB. If `carve_walkable` returns `([], [])`, emit the existing flat quad (logged).
4. Keep all `StaticBody3D`/`CollisionShape3D` + `NavigationRegion3D` nodes unchanged.

- [ ] **Step 4: Run the full compiler suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scene_compiler.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add foundry/scene_compiler.py foundry/tests/test_scene_compiler.py
git commit -m "feat(scene): GLB shell + triplanar materials + carved navmesh (box-shell fallback)"
```

---

### Task 7: `scaffold.py` — copy the per-room shell GLB; drop obsolete texture bake

**Context (read this):** The two texture sets are already baked and **committed** in
`foundry/godot_template/assets/shell_{stone,timber}_*.png` (Task 3, done). They ride into each
build automatically with the template copy — no scaffold bake needed. The old
`_ensure_shell_textures` baked the *old* `shell_{floor,wall,ceiling}_*` via the now-deleted
`build_shell_textures.py`, so it is **broken and must be removed**. What scaffold DOES still need:
copy the *per-room* shell **GLB** (from the `room_shell` cache) into the build's `assets/` so the
compiled scene can reference `res://assets/room_shell.glb`.

**Files:**
- Modify: `foundry/scaffold.py` (remove `_ensure_shell_textures` + its call; add GLB copy)
- Modify/Create: `foundry/tests/test_scaffold.py`

**Interfaces:**
- Consumes: a room-shell GLB path (from `room_shell.ensure_room_shell`, may be `None`).
- Produces: `room_shell.glb` present in the build's `assets/` when a path was given; the 6
  committed `shell_{stone,timber}_*` PNGs present via the normal template copy.

- [ ] **Step 1: Write the failing tests**

```python
# foundry/tests/test_scaffold.py
import scaffold

def test_copy_room_shell_glb(tmp_path):
    src = tmp_path / "cache" / "shell.glb"; src.parent.mkdir(parents=True)
    src.write_bytes(b"GLB")
    dest_assets = tmp_path / "build" / "assets"; dest_assets.mkdir(parents=True)
    scaffold._copy_room_shell(str(src), str(dest_assets))
    assert (dest_assets / "room_shell.glb").exists()

def test_copy_room_shell_glb_none_is_noop(tmp_path):
    dest_assets = tmp_path / "build" / "assets"; dest_assets.mkdir(parents=True)
    scaffold._copy_room_shell(None, str(dest_assets))   # must not raise
    assert not (dest_assets / "room_shell.glb").exists()

def test_no_ensure_shell_textures_symbol():
    # the broken old baker is gone
    assert not hasattr(scaffold, "_ensure_shell_textures")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scaffold.py -q`
Expected: FAIL (`_copy_room_shell` missing; `_ensure_shell_textures` still present).

- [ ] **Step 3: Implement**

Remove `_ensure_shell_textures` and its call site entirely. Add:
```python
def _copy_room_shell(glb_path, dest_assets_dir):
    """Copy the per-room shell GLB into the build's assets as room_shell.glb.
    No-op when glb_path is None (compiler falls back to the inline box shell)."""
    if not glb_path:
        return
    import shutil
    from pathlib import Path
    Path(dest_assets_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy(glb_path, str(Path(dest_assets_dir) / "room_shell.glb"))
```
Call `_copy_room_shell(shell_glb_path, dest_assets_dir)` in `scaffold_project` where the shell
path is known (the compiler passes it through, or scaffold calls `room_shell.ensure_room_shell`
with the room dims/theme). Also delete the obsolete `foundry/godot_template/assets/shell_floor_*`,
`shell_wall_*`, `shell_ceiling_*` PNGs (the box fallback now uses stone/timber — Task 6).

- [ ] **Step 4: Run to verify it passes**

Run: `cd foundry && .venv/bin/python -m pytest tests/test_scaffold.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add foundry/scaffold.py foundry/tests/test_scaffold.py
git rm foundry/godot_template/assets/shell_floor_*.png foundry/godot_template/assets/shell_wall_*.png foundry/godot_template/assets/shell_ceiling_*.png 2>/dev/null || true
git commit -m "chore(scaffold): copy per-room shell GLB; drop obsolete shell-texture bake"
```

---

### Task 8: Full-suite gate + end-to-end build (orchestrator)

**Files:** none (verification only).

- [ ] **Step 1: Full unit suite**

Run: `cd foundry && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_godot_smoke.py`
Expected: all pass (prior 1268 + new tests).

- [ ] **Step 2 (orchestrator): End-to-end scene + smoke + screenshots**

Build the study scene (27B model) → `godot --headless` smoke → render screenshots of the shell,
truss, prop resting, and a quick NPC path to confirm carving. Hand screenshots to the user for the
visual verdict. Restore `asset_lexicon.json` is NOT needed (quest path uses a /tmp copy).

- [ ] **Step 3: Commit any tuning** (bevel/tile/pitch) made from screenshot feedback, then stop.

---

## Self-Review

**Spec coverage:** C1 truss geometry → Task 4; C2 materials → Task 3; C3 cache/fallback → Task 5;
C4 compiler integration (triplanar + box fallback) → Task 6 (+ scaffold names → Task 7); C5
floating → Task 2; C6 navmesh carving → Task 1 (lib) + Task 6 (wiring). Determinism/caching →
Tasks 1/4/5. Testing strategy → each task + Task 8. Out-of-scope items intentionally have no tasks.

**Placeholder scan:** Blender node-graph + truss transforms are concrete but flagged "tune against
screenshots" (orchestrator step), not TODOs. No "add error handling"/"TBD" left.

**Type consistency:** `carve_walkable`/`point_in_polygons` (Task 1) used in Task 6 tests with the
same signatures; `ensure_room_shell`/`_cache_dir`/`_run_blender` (Task 5) match their tests;
`rest_offset` (Task 2) consumed in Task 6; texture names `shell_{stone,timber}_*` consistent across
Tasks 3/6/7.
