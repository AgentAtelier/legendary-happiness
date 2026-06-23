"""Blender-gated structural test for the king-post truss room-shell generator.

Skips where Blender is unavailable; the orchestrator runs the real build +
screenshots. Asserts the GLB exists with two named material slots and sane
dimensions — not pixel-exact geometry (tuned visually).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

blender = shutil.which("blender")
pytestmark = pytest.mark.skipif(blender is None, reason="blender not installed")

GEN = Path(__file__).resolve().parent.parent / "blender" / "build_room_shell.py"


def test_builds_glb_with_two_material_slots(tmp_path):
    out = tmp_path / "shell.glb"
    subprocess.run(
        [blender, "--background", "--python", str(GEN), "--",
         str(out), "8", "6", "3", "study", "0"],
        check=True, capture_output=True, timeout=300,
    )
    assert out.exists() and out.stat().st_size > 0

    import trimesh
    scene = trimesh.load(str(out))
    geos = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
    mats = {getattr(getattr(g.visual, "material", None), "name", None) for g in geos}
    assert {"stone", "timber"} <= mats, f"expected stone+timber slots, got {mats}"

    # sane footprint: ~ w x d at the base, ridge well above the 3 m walls
    lo, hi = scene.bounds
    assert 7.5 <= (hi[0] - lo[0]) <= 9.0      # width ~8 (+walls)
    assert hi[1] >= 5.5                         # ridge (apex) above plate height


def test_truss_count_scales_with_depth(tmp_path):
    import trimesh
    counts = {}
    for depth in ("4", "10"):
        out = tmp_path / f"s{depth}.glb"
        subprocess.run(
            [blender, "--background", "--python", str(GEN), "--",
             str(out), "8", depth, "3", "study", "0"],
            check=True, capture_output=True, timeout=300,
        )
        scene = trimesh.load(str(out))
        geos = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
        counts[depth] = sum(len(g.vertices) for g in geos)
    assert counts["10"] > counts["4"]  # deeper room -> more trusses -> more verts


def test_window_opening_builds(tmp_path):
    import json
    out = tmp_path / "shellw.glb"
    windows = json.dumps([{"wall": "E", "center": 0.5, "width": 1.2, "height": 1.4, "sill": 1.2}])
    subprocess.run(
        [blender, "--background", "--python", str(GEN), "--",
         str(out), "8", "6", "3", "study", "0", windows],
        check=True, capture_output=True, timeout=300,
    )
    assert out.exists() and out.stat().st_size > 0
    import trimesh
    scene = trimesh.load(str(out))
    geos = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
    mats = {getattr(getattr(g.visual, "material", None), "name", None) for g in geos}
    assert {"stone", "timber"} <= mats
