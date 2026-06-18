import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import trimesh

from library import read_envelope, LIVE_LEXICON

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


# ── Slice 7: chair build integration ───────────────────────────────

_CHAIR_SPEC = {
    "asset_id": "chair",
    "generator": "chair",
    "material": "worn_oak",
    "params": {
        "seat_width": 0.5,
        "seat_depth": 0.5,
        "seat_thickness": 0.06,
        "leg_height": 0.45,
        "leg_radius": 0.04,
        "leg_inset": 0.05,
        "back_height": 0.35,
    },
}


def test_build_exports_a_valid_chair(tmp_path):
    """Build a chair GLB, verify extents fit the lexicon chair envelope."""
    # Write a temp spec file for the chair
    spec_path = tmp_path / "chair.json"
    spec_path.write_text(json.dumps(_CHAIR_SPEC), encoding="utf-8")

    out = str(tmp_path / "chair.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    # Read the chair envelope from the lexicon
    fp, height = read_envelope(LIVE_LEXICON, "chair")

    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    ext = mesh.extents  # [width=X, height=Y, depth=Z]

    # The bbox must fit the lexicon chair envelope (with 15% gate tolerance)
    tol = 1.15
    assert ext[0] <= fp["width"] * tol, (
        f"chair width {ext[0]:.3f} exceeds footprint {fp['width']} * {tol}"
    )
    assert ext[2] <= fp["depth"] * tol, (
        f"chair depth {ext[2]:.3f} exceeds footprint {fp['depth']} * {tol}"
    )
    assert ext[1] <= height * tol, (
        f"chair height {ext[1]:.3f} exceeds envelope {height} * {tol}"
    )

    # Watertight on position-welded topology
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "chair mesh must be watertight"


def test_chair_has_baked_texture_and_uvs(tmp_path):
    """Chair GLB has embedded texture, baseColorTexture, and UVs."""
    from pygltflib import GLTF2

    spec_path = tmp_path / "chair_tex.json"
    spec_path.write_text(json.dumps(_CHAIR_SPEC), encoding="utf-8")

    glb = str(tmp_path / "chair_tex.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(glb), "no GLB written"

    gltf = GLTF2().load(glb)

    assert gltf.images is not None
    assert len(gltf.images) > 0, "expected embedded images"

    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness
    assert pbr.baseColorTexture is not None, "expected baseColorTexture"
    bct = pbr.baseColorTexture
    assert bct.index is not None
    assert 0 <= bct.index < len(gltf.textures)

    mesh = gltf.meshes[0]
    primitive = mesh.primitives[0]
    assert primitive.attributes.TEXCOORD_0 is not None, "expected TEXCOORD_0"
