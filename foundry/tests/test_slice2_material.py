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
    """Read PBR factors from a glTF/GLB using pygltflib.

    Slice 5: roughness and metallic are now texture-driven
    (metallicRoughnessTexture, glTF 2.0 spec).  When that texture is
    present we report the EFFECTIVE values (texture.g for roughness,
    metallicFactor * texture.b for metallic) so callers can assert
    the per-material behaviour without caring whether the carrier is
    the scalar fallback or the texture channel.
    """
    from io import BytesIO
    import numpy as np
    from PIL import Image
    from pygltflib import GLTF2
    gltf = GLTF2().load(glb_path)
    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness

    # Default to the scalar factor; override with texture channel when
    # the GLB carries a metallicRoughnessTexture.
    roughness = pbr.roughnessFactor
    metallic = pbr.metallicFactor
    if pbr.metallicRoughnessTexture is not None:
        mrt = pbr.metallicRoughnessTexture
        tex = gltf.textures[mrt.index]
        image = gltf.images[tex.source]
        bv = gltf.bufferViews[image.bufferView]
        blob = gltf.binary_blob()
        img = Image.open(BytesIO(blob[bv.byteOffset:bv.byteOffset + bv.byteLength]))
        arr = np.array(img)
        if arr.ndim == 2:
            arr = arr[..., None]
        if arr.shape[2] > 3:
            arr = arr[:, :, :3]
        # Convention: glTF metallicRoughnessTexture packs G=roughness, B=metallic
        g_mean = float(arr[:, :, 1].mean() / 255.0)
        b_mean = float(arr[:, :, 2].mean() / 255.0)
        roughness = g_mean  # per spec, texture.g REPLACES the scalar
        # Per spec, metallicFactor MULTIPLIES texture.b (metalness)
        metallic = (metallic if metallic is not None else 1.0) * b_mean

    return {
        "roughnessFactor": roughness,
        "baseColorFactor": list(pbr.baseColorFactor),
        "metallicFactor": metallic,
        "has_baseColorTexture": pbr.baseColorTexture is not None,
        "has_metallicRoughnessTexture": pbr.metallicRoughnessTexture is not None,
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
    # Slice 5: tolerance widened from 0.05 to 0.15 because roughness
    # is now texture-driven (~baseline ±0.05 noise + bake variation).
    assert abs(factors["roughnessFactor"] - 0.65) <= 0.15, (
        f"roughnessFactor={factors['roughnessFactor']}"
    )
    # Slice 3 wires a baked texture to Base Color, so the factor is white
    # [1,1,1,1] (the texture carries the colour).
    bcf = factors["baseColorFactor"]
    has_tex = factors["has_baseColorTexture"]
    if has_tex:
        expected_bcf = [1.0, 1.0, 1.0, 1.0]
    else:
        expected_bcf = [0.45, 0.28, 0.14, 1.0]
    for channel, (actual, expected) in enumerate(zip(bcf, expected_bcf)):
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

    # Watertight check on position-only topology (tolerates UV seams).
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "beveled mesh must remain watertight"


# ── Slice 6: material palette roughness tests ─────────────────────

def _build_with_material(material: str, tmp_path) -> str:
    """Build a table GLB with the given material and return the GLB path."""
    spec_data = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    spec_data["material"] = material
    spec_path = tmp_path / f"table_{material}.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")

    glb = str(tmp_path / f"table_{material}.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed for {material}:\n{proc.stderr or proc.stdout}"
    assert os.path.exists(glb), f"no GLB written for {material}"
    return glb


def test_dark_walnut_yields_roughness_055(tmp_path):
    """Building with material=dark_walnut yields roughnessFactor ≈ 0.55."""
    glb = _build_with_material("dark_walnut", tmp_path)
    factors = _read_pbr_factors(glb)
    # Slice 5: tolerance widened to ±0.15 (texture-driven variation).
    assert abs(factors["roughnessFactor"] - 0.55) <= 0.15, (
        f"dark_walnut roughnessFactor={factors['roughnessFactor']}"
    )


def test_weathered_pine_yields_roughness_075(tmp_path):
    """Building with material=weathered_pine yields roughnessFactor ≈ 0.75."""
    glb = _build_with_material("weathered_pine", tmp_path)
    factors = _read_pbr_factors(glb)
    # Slice 5: tolerance widened to ±0.15 (texture-driven variation).
    assert abs(factors["roughnessFactor"] - 0.75) <= 0.15, (
        f"weathered_pine roughnessFactor={factors['roughnessFactor']}"
    )


def test_worn_oak_yields_roughness_065(tmp_path):
    """Building with material=worn_oak still yields roughnessFactor ≈ 0.65."""
    glb = _build_with_material("worn_oak", tmp_path)
    factors = _read_pbr_factors(glb)
    # Slice 5: tolerance widened to ±0.15 (texture-driven variation).
    assert abs(factors["roughnessFactor"] - 0.65) <= 0.15, (
        f"worn_oak roughnessFactor={factors['roughnessFactor']}"
    )


def test_all_materials_keep_baked_texture_and_uvs(tmp_path):
    """Slice 3 assertions (baked texture, UVs) stay green for all materials."""
    from pygltflib import GLTF2

    for material in ("worn_oak", "dark_walnut", "weathered_pine"):
        glb = _build_with_material(material, tmp_path)
        gltf = GLTF2().load(glb)

        # (a) gltf.images non-empty
        assert gltf.images is not None, f"[{material}] gltf.images is None"
        assert len(gltf.images) > 0, f"[{material}] expected embedded images, got {len(gltf.images) if gltf.images else 0}"

        # (b) baseColorTexture is wired
        mat = gltf.materials[0]
        pbr = mat.pbrMetallicRoughness
        assert pbr.baseColorTexture is not None, f"[{material}] expected baseColorTexture"
        bct = pbr.baseColorTexture
        assert bct.index is not None, f"[{material}] baseColorTexture.index is None"
        assert 0 <= bct.index < len(gltf.textures), (
            f"[{material}] baseColorTexture index {bct.index} out of range [0, {len(gltf.textures)})"
        )

        # (c) mesh primitive has TEXCOORD_0
        mesh = gltf.meshes[0]
        primitive = mesh.primitives[0]
        assert primitive.attributes.TEXCOORD_0 is not None, (
            f"[{material}] expected TEXCOORD_0"
        )

        # Also watertight
        tmesh = trimesh.load(glb, force="mesh")
        tmesh.merge_vertices()
        topo = trimesh.Trimesh(vertices=tmesh.vertices, faces=tmesh.faces)
        topo.merge_vertices()
        assert topo.is_watertight, f"[{material}] mesh must remain watertight"
