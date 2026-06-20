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


# ── Task 2: Stone material build test ─────────────────────────────

_GRANITE_SPEC = {
    "asset_id": "table",
    "generator": "table",
    "material": "rough_granite",
    "params": {
        "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
        "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
    },
}


def test_build_granite_table_passes_gate(tmp_path):
    """A table built with rough_granite builds, exports, and passes the gate."""
    spec_path = tmp_path / "granite_table.json"
    spec_path.write_text(json.dumps(_GRANITE_SPEC), encoding="utf-8")

    out = str(tmp_path / "granite_table.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    # Gate check with table envelope
    from gate import gate_asset
    res = gate_asset(out, {"width": 2.0, "depth": 1.5}, 1.2)
    assert res.passed, f"gate failed: {res.reasons}"

    # Verify watertight
    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "granite table mesh must be watertight"


def test_granite_texture_is_grey_and_low_saturation(tmp_path):
    """The granite baked texture has mean colour in the grey range
    and lower saturation than wood."""
    import numpy as np
    from io import BytesIO
    from PIL import Image
    from pygltflib import GLTF2

    spec_path = tmp_path / "granite_tex.json"
    spec_path.write_text(json.dumps(_GRANITE_SPEC), encoding="utf-8")

    glb = str(tmp_path / "granite_tex.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

    gltf = GLTF2().load(glb)
    # Slice 4 invariant: walk the glTF texture chain to the baseColor image
    # rather than reading gltf.images[0] directly — after the NORMAL bake
    # the GLB carries two images and Blender's emission ordering isn't
    # guaranteed, so the baseColor image may no longer be at index 0.
    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness
    bct = pbr.baseColorTexture
    assert bct is not None and bct.index is not None, (
        "expected baseColorTexture to be present (slice 3 contract)"
    )
    tex_bc = gltf.textures[bct.index]
    image = gltf.images[tex_bc.source]
    buffer_view = gltf.bufferViews[image.bufferView]
    blob = gltf.binary_blob()
    image_data = blob[buffer_view.byteOffset:buffer_view.byteOffset + buffer_view.byteLength]
    img = Image.open(BytesIO(image_data))
    arr = np.array(img)

    if len(arr.shape) == 3 and arr.shape[2] >= 3:
        rgb = arr[:, :, :3].astype(np.float64) / 255.0
        mean_r = float(rgb[:, :, 0].mean())
        mean_g = float(rgb[:, :, 1].mean())
        mean_b = float(rgb[:, :, 2].mean())

        # Mean colour is in the grey range (channels close together)
        max_channel_diff = max(abs(mean_r - mean_g), abs(mean_g - mean_b), abs(mean_r - mean_b))
        assert max_channel_diff < 0.08, (
            f"granite texture not grey enough: R={mean_r:.3f} G={mean_g:.3f} B={mean_b:.3f}, "
            f"max channel diff={max_channel_diff:.3f}"
        )

        # Overall brightness in a mid-grey range
        mean_lum = float((mean_r + mean_g + mean_b) / 3.0)
        assert 0.20 < mean_lum < 0.55, (
            f"granite mean luminance {mean_lum:.3f} out of expected [0.20, 0.55]"
        )


# ── Task 3: Metal material build test ─────────────────────────────

_IRON_SPEC = {
    "asset_id": "table",
    "generator": "table",
    "material": "wrought_iron",
    "params": {
        "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
        "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
    },
}


def test_build_iron_table_passes_gate(tmp_path):
    """A table built with wrought_iron builds, exports, and passes the gate."""
    spec_path = tmp_path / "iron_table.json"
    spec_path.write_text(json.dumps(_IRON_SPEC), encoding="utf-8")

    out = str(tmp_path / "iron_table.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    from gate import gate_asset
    res = gate_asset(out, {"width": 2.0, "depth": 1.5}, 1.2)
    assert res.passed, f"gate failed: {res.reasons}"

    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "iron table mesh must be watertight"


def test_iron_table_metallic_factor_is_one(tmp_path):
    """A table built with wrought_iron has effective metallic ≈ 1.0 AND
    effective roughness ≈ 0.45 in the exported GLB.

    Slice 5: roughness and metallic are texture-driven via
    ``metallicRoughnessTexture``.  Per glTF 2.0 the effective metallic
    = ``metallicFactor * texture.b``; effective roughness = texture.g.
    For wrought_iron the texture packs metallic=1.0 in B and the
    baseline roughness (0.45) modulated in G, so the effective
    behaviour is preserved.
    """
    from io import BytesIO
    import numpy as np
    from PIL import Image
    from pygltflib import GLTF2

    spec_path = tmp_path / "iron_metallic.json"
    spec_path.write_text(json.dumps(_IRON_SPEC), encoding="utf-8")

    glb = str(tmp_path / "iron_metallic.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(glb), "no GLB written"

    gltf = GLTF2().load(glb)
    mat = gltf.materials[0]
    pbr = mat.pbrMetallicRoughness

    # metallicRoughnessTexture MUST be present (slice 5 contract).
    assert pbr.metallicRoughnessTexture is not None, (
        "wrought_iron GLB must carry metallicRoughnessTexture (slice 5)"
    )
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

    # glTF packing: G=roughness, B=metallic.
    b_mean = float(arr[:, :, 2].mean() / 255.0)  # metallic channel
    g_mean = float(arr[:, :, 1].mean() / 255.0)  # roughness channel
    scalar_mf = pbr.metallicFactor if pbr.metallicFactor is not None else 1.0

    effective_metallic = scalar_mf * b_mean
    assert abs(effective_metallic - 1.0) <= 0.05, (
        f"effective metallic = metallicFactor({scalar_mf}) * texture.b({b_mean:.3f}) "
        f"= {effective_metallic:.3f}; expected ≈ 1.0 for wrought_iron"
    )
    # Roughness tolerance widened to ±0.15 to absorb ±0.05 texture noise
    # + bake variation observed in slice 5.
    assert abs(g_mean - 0.45) <= 0.15, (
        f"texture.G roughness mean ({g_mean:.3f}) deviates from baseline "
        f"0.45 by more than ±0.15"
    )


# ── Task 4: Shelf generator build test ─────────────────────────────

_SHELF_SPEC = {
    "asset_id": "shelf",
    "generator": "shelf",
    "material": "worn_oak",
    "params": {
        "width": 1.0, "depth": 0.3, "height": 1.2,
        "board_thickness": 0.04, "n_shelves": 3, "side_thickness": 0.03,
    },
}


def test_build_shelf_passes_gate(tmp_path):
    """A shelf builds, exports, and passes the gate vs the shelf envelope."""
    spec_path = tmp_path / "shelf.json"
    spec_path.write_text(json.dumps(_SHELF_SPEC), encoding="utf-8")

    out = str(tmp_path / "shelf.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    # Gate check with shelf envelope (footprint 1.0×0.3, height 1.2, +15% tol)
    from gate import gate_asset
    res = gate_asset(out, {"width": 1.0, "depth": 0.3}, 1.2)
    assert res.passed, f"gate failed: {res.reasons}"

    # Watertight
    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "shelf mesh must be watertight"


# ── Task 5: Cabinet generator build test ───────────────────────────

_CABINET_SPEC = {
    "asset_id": "cabinet",
    "generator": "cabinet",
    "material": "worn_oak",
    "params": {
        "width": 0.8, "depth": 0.5, "height": 1.5,
        "panel_thickness": 0.04, "base_height": 0.08,
    },
}


def test_build_cabinet_passes_gate(tmp_path):
    """A cabinet builds, exports, and passes the gate vs the cabinet envelope."""
    spec_path = tmp_path / "cabinet.json"
    spec_path.write_text(json.dumps(_CABINET_SPEC), encoding="utf-8")

    out = str(tmp_path / "cabinet.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), out],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(out), "no GLB written"

    # Gate check with cabinet envelope (footprint 0.8×0.5, height 1.6, +15% tol)
    from gate import gate_asset
    res = gate_asset(out, {"width": 0.8, "depth": 0.5}, 1.6)
    assert res.passed, f"gate failed: {res.reasons}"

    # Watertight
    mesh = trimesh.load(out, force="mesh")
    mesh.merge_vertices()
    topo = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    topo.merge_vertices()
    assert topo.is_watertight, "cabinet mesh must be watertight"


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


def test_rug_builds_and_passes_gate(tmp_path):
    from gate import gate_asset
    spec = {"asset_id": "rug", "generator": "rug", "material": "worn_oak",
            "age": 0.2, "params": {"width": 2.0, "depth": 1.4, "thickness": 0.02}}
    sp = tmp_path / "rug.json"; sp.write_text(json.dumps(spec))
    out = tmp_path / "rug.glb"
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(sp), str(out)],
        capture_output=True, text=True, timeout=180,
    )
    assert out.exists(), proc.stderr[-2000:] or proc.stdout[-2000:]
    fp, h = read_envelope(LIVE_LEXICON, "rug")
    result = gate_asset(str(out), fp, h)
    assert result.passed, result.reasons
