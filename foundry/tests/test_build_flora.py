"""Blender build tests for the exterior flora generators (tree/rock/shrub).

Each must export a GLB that is position-welded watertight (the gate's contract)
and within the polygon budget. Skipped when Blender isn't installed.
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


def _build(spec: dict, tmp_path: Path) -> str:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    out = str(tmp_path / "out.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"
    return out


def _load_welded(out: str):
    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    return topo, mesh


TREE = {
    "asset_id": "tree", "generator": "tree", "material": "weathered_pine",
    "params": {"trunk_height": 0.6, "trunk_radius": 0.08,
               "foliage_height": 1.5, "foliage_radius": 0.55, "tiers": 3},
}
ROCK = {
    "asset_id": "rock", "generator": "rock", "material": "rough_granite",
    "params": {"radius": 0.4, "roughness": 0.22, "subdivisions": 2},
}
SHRUB = {
    "asset_id": "shrub", "generator": "shrub", "material": "worn_oak",
    "params": {"radius": 0.32, "lobes": 4},
}


def test_tree_builds_watertight(tmp_path):
    topo, mesh = _load_welded(_build(TREE, tmp_path))
    assert topo.is_watertight, "tree not watertight"
    assert mesh.faces.shape[0] <= 2000
    assert mesh.extents[1] > 1.5  # a tree is tall


def test_rock_builds_watertight(tmp_path):
    topo, mesh = _load_welded(_build(ROCK, tmp_path))
    assert topo.is_watertight, "rock not watertight"
    assert mesh.faces.shape[0] <= 2000


def test_shrub_builds_watertight(tmp_path):
    topo, mesh = _load_welded(_build(SHRUB, tmp_path))
    assert topo.is_watertight, "shrub not watertight"
    assert mesh.faces.shape[0] <= 2000
