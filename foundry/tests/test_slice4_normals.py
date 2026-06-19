"""Slice 4: NORMAL map bake integration test.

Slice 3 baked only baseColor (albedo×AO via Cycles EMIT).  Slice 4 adds a
second bake pass — a tangent-space NORMAL map driven by the SAME
procedural signal that produces the colour (Wave for wood,
Voronoi.distance for stone, Noise for metal).  The glTF exporter should
emit a ``normalTexture`` alongside ``baseColorTexture``.

Test asserts PRESENCE/structure only (per the slice's quality bar:
"build the PLUMBING + a plausible first pass, NOT final-look shader
authoring — that is the user's job").
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


def test_table_has_baked_normal_texture(tmp_path):
    """Build the table with the canonical test spec; assert the exported
    GLB exposes a normalTexture and at least two embedded images (the
    existing baseColor image + the new normal image).
    """
    # Copy spec for a self-contained build.
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

    # (a) At least two embedded images — baseColor + normal.
    assert gltf.images is not None, "gltf.images is None"
    assert len(gltf.images) >= 2, (
        f"expected ≥2 embedded images (baseColor + normal), "
        f"got {len(gltf.images)}"
    )

    # (b) material has a normalTexture bound to a valid texture entry.
    mat = gltf.materials[0]
    assert mat.normalTexture is not None, "expected normalTexture to be present"
    nt = mat.normalTexture
    assert nt.index is not None, "normalTexture.index is None"
    assert 0 <= nt.index < len(gltf.textures), (
        f"normalTexture.index {nt.index} out of range [0, {len(gltf.textures)})"
    )

    # The normalTexture must reference an image, not a sampler-only stub.
    tex = gltf.textures[nt.index]
    assert tex.source is not None, "normalTexture bound texture has no source image"
    assert 0 <= tex.source < len(gltf.images), (
        f"normalTexture.source {tex.source} out of image range [0, {len(gltf.images)})"
    )

    # The baseColor image is still present (slice-3 contract preserved).
    pbr = mat.pbrMetallicRoughness
    assert pbr.baseColorTexture is not None, "baseColorTexture missing after slice 4"
    bct = pbr.baseColorTexture
    assert bct.index is not None and 0 <= bct.index < len(gltf.textures)
    tex_bc = gltf.textures[bct.index]
    assert tex_bc.source is not None and 0 <= tex_bc.source < len(gltf.images)

    # The normal image is NOT the same byte buffer as the baseColor image
    # (two distinct images mean two distinct bake passes).
    assert nt.index != bct.index or tex.source != tex_bc.source, (
        "normal and baseColor images look identical — "
        "normal bake probably didn't happen"
    )

    # (c) Gate still passes — the bump wiring doesn't bloat geometry or
    # disturb the watertight check.
    from gate import gate_asset
    res = gate_asset(glb, {"width": 2.0, "depth": 1.5}, 1.2)
    assert res.passed, f"gate failed: {res.reasons}"


def test_chair_has_baked_normal_texture(tmp_path):
    """Chair build (different family) also gains a normalTexture — proves
    the family dispatch covers more than the table path."""
    spec = {
        "asset_id": "chair",
        "generator": "chair",
        "material": "worn_oak",
        "params": {
            "seat_width": 0.5, "seat_depth": 0.5, "seat_thickness": 0.06,
            "leg_height": 0.45, "leg_radius": 0.04, "leg_inset": 0.05,
            "back_height": 0.35,
        },
    }
    spec_path = tmp_path / "chair.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    glb = str(tmp_path / "chair.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed:\n{proc.stderr or proc.stdout}"
    assert os.path.exists(glb), "no GLB written"

    gltf = GLTF2().load(glb)
    mat = gltf.materials[0]
    assert mat.normalTexture is not None, "chair expected normalTexture"
    nt = mat.normalTexture
    assert nt.index is not None and 0 <= nt.index < len(gltf.textures)
    tex = gltf.textures[nt.index]
    assert 0 <= tex.source < len(gltf.images)
    assert len(gltf.images) >= 2, "chair expected ≥2 embedded images"


def test_iron_table_has_baked_normal_texture(tmp_path):
    """Wrought-iron (metal family, separate colour builder) also gains a
    normal map sourced from the metal's noise.Fac."""
    spec = {
        "asset_id": "table",
        "generator": "table",
        "material": "wrought_iron",
        "params": {
            "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
            "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
        },
    }
    spec_path = tmp_path / "iron.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    glb = str(tmp_path / "iron.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed:\n{proc.stderr or proc.stdout}"

    gltf = GLTF2().load(glb)
    mat = gltf.materials[0]
    assert mat.normalTexture is not None, "iron expected normalTexture"
