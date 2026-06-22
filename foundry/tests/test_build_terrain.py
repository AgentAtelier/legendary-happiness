"""Blender build test for the exterior terrain generator.

Terrain is an open displaced ground plane (not a watertight prop): it must build,
span the requested extent, and carry real relief from the shared terrain_field.
Skipped when Blender isn't installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

trimesh = pytest.importorskip("trimesh")

BLENDER = shutil.which("blender")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")

TERRAIN = {
    "asset_id": "terrain", "generator": "terrain", "material": "rough_granite",
    "params": {"extent": 40.0, "resolution": 48, "amplitude": 1.5,
               "base_frequency": 0.05, "octaves": 4, "seed": 7},
}


def test_terrain_builds_with_relief(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(TERRAIN))
    out = str(tmp_path / "terrain.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no terrain GLB written"

    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    ext = mesh.extents  # glTF/Godot axes: [X, Y=height, Z]
    horiz = max(ext[0], ext[2])
    assert horiz > 35.0, f"terrain should span ~40 m; extents={ext}"
    assert ext[1] > 0.3, f"terrain is too flat (no relief); height span={ext[1]}"
    assert ext[1] < 4.0, f"terrain relief exceeds amplitude bounds; height span={ext[1]}"


def test_flat_terrain_is_flat(tmp_path):
    """amplitude=0 → a flat ground plane (height span ≈ 0)."""
    spec = dict(TERRAIN)
    spec["params"] = dict(TERRAIN["params"], amplitude=0.0)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    out = str(tmp_path / "flat.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    assert mesh.extents[1] < 0.05, f"flat terrain should have ~0 height span; got {mesh.extents[1]}"
