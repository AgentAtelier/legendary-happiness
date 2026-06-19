"""Slice 3 integration test: baked procedural wood texture with valid UVs.

Asserts:
  (a) gltf.images is non-empty (a texture was embedded),
  (b) material[0].pbrMetallicRoughness.baseColorTexture is not None,
  (c) the mesh primitive has a TEXCOORD_0 attribute (UVs exist).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pygltflib import GLTF2

BLENDER = shutil.which("blender")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")


def test_table_has_baked_texture_and_uvs(tmp_path):
    """Build the table and verify the GLB has an embedded baked texture,
    baseColorTexture is wired, and UVs exist on the mesh primitive."""
    # Write a copy of the spec so the test is self-contained
    spec_data = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    spec_path = tmp_path / "table.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")

    glb = str(tmp_path / "table.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed:\n{proc.stderr or proc.stdout}"
    assert os.path.exists(glb), "no GLB written"

    gltf = GLTF2().load(glb)

    # (a) gltf.images non-empty — a texture was embedded
    assert gltf.images is not None, "gltf.images is None"
    assert len(gltf.images) > 0, f"expected embedded images, got {len(gltf.images) if gltf.images else 0}"

    # (b) baseColorTexture is wired
    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness
    assert pbr.baseColorTexture is not None, "expected baseColorTexture to be present"
    bct = pbr.baseColorTexture
    assert bct.index is not None, "baseColorTexture.index is None"
    assert 0 <= bct.index < len(gltf.textures), (
        f"baseColorTexture index {bct.index} out of range [0, {len(gltf.textures)})"
    )

    # (c) mesh primitive has TEXCOORD_0 attribute
    mesh = gltf.meshes[0]
    primitive = mesh.primitives[0]
    assert primitive.attributes.TEXCOORD_0 is not None, (
        "expected TEXCOORD_0 in primitive attributes"
    )
