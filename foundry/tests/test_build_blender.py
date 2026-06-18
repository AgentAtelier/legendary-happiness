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
    # Blender 5.x glTF exporter emits per-face vertices; merge them so
    # extents checks work on proper shared-vertex topology.
    mesh.merge_vertices()
    ext = mesh.extents  # [width=X, height=Y, depth=Z]
    assert abs(ext[0] - 1.5) < 0.05, f"width {ext[0]}"
    assert abs(ext[2] - 1.0) < 0.05, f"depth {ext[2]}"
    assert abs(ext[1] - 0.75) < 0.05, f"height {ext[1]}"

    # Watertight check on position-only topology (tolerates UV seams).
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight
