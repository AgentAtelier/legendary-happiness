"""Slice 2 integration test: beveled table with stylized PBR wood material.

Asserts:
  (a) exported material PBR factors: roughnessFactor ≈ 0.65, baseColorFactor ≈
      [0.45, 0.28, 0.14, 1.0], metallicFactor ≈ 0
  (b) beveled triangle count is meaningfully higher than the un-beveled slice-1
      table (~60 triangles)
"""

import json
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


def _read_pbr_factors(glb_path: str) -> dict:
    """Read PBR factors from a glTF/GLB using pygltflib (float factors)."""
    from pygltflib import GLTF2
    gltf = GLTF2().load(glb_path)
    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness
    return {
        "roughnessFactor": pbr.roughnessFactor,
        "baseColorFactor": list(pbr.baseColorFactor),
        "metallicFactor": pbr.metallicFactor,
    }


def test_table_has_bevel_and_pbr_material(tmp_path):
    """Build the table and verify:
    - PBR factors match the stylized wood spec
    - Triangle count is clearly greater than the un-beveled baseline (~60)
    """
    # Write a copy of the spec so the test is self-contained
    spec_data = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    spec_path = tmp_path / "table.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")

    glb = str(tmp_path / "table.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(glb), "no GLB written"

    # --- (a) PBR material factors ---
    factors = _read_pbr_factors(glb)
    assert abs(factors["roughnessFactor"] - 0.65) <= 0.05, (
        f"roughnessFactor={factors['roughnessFactor']}"
    )
    # Target base color: [0.45, 0.28, 0.14, 1.0]
    bcf = factors["baseColorFactor"]
    for channel, (actual, expected) in enumerate(zip(bcf, [0.45, 0.28, 0.14, 1.0])):
        assert abs(actual - expected) <= 0.05, (
            f"baseColorFactor[{channel}]={actual}, expected ≈ {expected}"
        )
    assert abs(factors["metallicFactor"] - 0.0) <= 0.01, (
        f"metallicFactor={factors['metallicFactor']}"
    )

    # --- (b) Bevel triangle count ---
    mesh = trimesh.load(glb, force="mesh")
    mesh.merge_vertices()
    n_faces = mesh.faces.shape[0]
    # Un-beveled slice-1 table is 60 triangles. Beveled must be clearly higher.
    assert n_faces > 80, (
        f"Expected beveled table to have >80 triangles (got {n_faces}); "
        "un-beveled baseline is 60"
    )
    assert mesh.is_watertight, "beveled mesh must remain watertight"
