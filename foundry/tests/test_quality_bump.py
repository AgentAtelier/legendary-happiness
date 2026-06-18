"""Tests for the asset quality-bump feature (hard-surface foundry).
Task 1: object-space warped stepped wood shader.
Task 2: entropy age knob — break the CAD silhouette.
"""

import json
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image
from pygltflib import GLTF2

from compiler import SpecError, compile_spec
from gate import gate_asset

BLENDER = shutil.which("blender")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")

FOOTPRINT = {"width": 2.0, "depth": 1.5}
HEIGHT = 1.2


# ── Helpers ───────────────────────────────────────────────────────

def _build(tmp_path, spec_dict, name="table.glb"):
    """Build a GLB from a spec dict. Returns path to the GLB."""
    spec_path = tmp_path / f"{name}_spec.json"
    spec_path.write_text(json.dumps(spec_dict), encoding="utf-8")
    glb = str(tmp_path / name)
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed:\n{proc.stderr or proc.stdout}"
    assert os.path.exists(glb), "no GLB written"
    return glb


def _load_mesh(glb_path):
    """Load a GLB as a trimesh object with merged vertices."""
    mesh = trimesh.load(glb_path, force="mesh")
    mesh.merge_vertices()
    return mesh


def _extract_texture_array(glb_path):
    """Load a GLB and return the first embedded image as a numpy array (RGB or L)."""
    gltf = GLTF2().load(glb_path)
    assert gltf.images is not None and len(gltf.images) > 0, "no embedded images"
    image = gltf.images[0]
    buffer_view = gltf.bufferViews[image.bufferView]
    blob = gltf.binary_blob()
    image_data = blob[buffer_view.byteOffset:buffer_view.byteOffset + buffer_view.byteLength]
    img = Image.open(BytesIO(image_data))
    return np.array(img)


# ── Task 1: Wood shader quality ──────────────────────────────────

def test_table_passes_gate_after_wood_shader_changes(tmp_path):
    """Building a table with the new wood shader still passes the gate
    (watertight, within bounds, under poly budget)."""
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

    # Gate check with a generous envelope (the default table fits easily).
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert res.passed, f"gate failed: {res.reasons}"


def test_baked_texture_is_non_uniform_and_not_axis_periodic(tmp_path):
    """The baked wood texture is not a uniform colour and not a single
    axis-aligned periodic pattern (no stripey corduroy)."""
    spec_data = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    spec_path = tmp_path / "table_tex.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")

    glb = str(tmp_path / "table_tex.glb")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", str(spec_path), glb],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender build failed:\n{proc.stderr or proc.stdout}"

    arr = _extract_texture_array(glb)

    # Convert to grayscale if colour.
    if len(arr.shape) == 3 and arr.shape[2] >= 3:
        grey = arr[:, :, :3].mean(axis=2)
    else:
        grey = arr.astype(np.float64)

    # ── Non-uniform: variance must be above a small threshold ──
    variance = float(grey.var())
    assert variance > 0.001, (
        f"texture too uniform (variance={variance:.6f}); "
        f"likely a flat colour or degenerate shader"
    )

    # ── Not axis-aligned periodic ──────────────────────────────
    # If the pattern were pure X-axis stripes (parallel to Y), every Y-row
    # would be nearly identical → row variance near zero.  Likewise for
    # Y-axis stripes.  Both axis variances must be meaningful.
    col_var = float(grey.var(axis=0).mean())  # per-column variance
    row_var = float(grey.var(axis=1).mean())  # per-row variance

    assert col_var > 0.0005, (
        f"column variance too low ({col_var:.6f}); "
        f"texture may be axis-aligned periodic (X-stripes)"
    )
    assert row_var > 0.0005, (
        f"row variance too low ({row_var:.6f}); "
        f"texture may be axis-aligned periodic (Y-stripes)"
    )


# ── Task 2: Entropy age knob ─────────────────────────────────────

# ── Compiler-level age validation (no Blender needed) ────────────

_AGE_SPEC = {
    "asset_id": "table",
    "generator": "table",
    "material": "worn_oak",
    "age": 0.5,
    "params": {
        "top_width": 1.5, "top_depth": 1.0, "top_thickness": 0.08,
        "leg_height": 0.67, "leg_radius": 0.06, "leg_inset": 0.1,
    },
}


def test_age_valid_compiles():
    """A spec with valid age compiles and the age is preserved."""
    out = compile_spec(_AGE_SPEC)
    assert out["age"] == 0.5


def test_age_missing_defaults_to_015():
    """Missing age defaults to 0.15."""
    s = dict(_AGE_SPEC)
    del s["age"]
    out = compile_spec(s)
    assert out["age"] == 0.15


def test_age_below_015_rejected():
    """age below 0.15 is rejected."""
    s = dict(_AGE_SPEC)
    s["age"] = 0.0
    with pytest.raises(SpecError, match="out of range"):
        compile_spec(s)


def test_age_above_1_rejected():
    """age above 1.0 is rejected."""
    s = dict(_AGE_SPEC)
    s["age"] = 5.0
    with pytest.raises(SpecError, match="out of range"):
        compile_spec(s)


def test_age_non_numeric_rejected():
    """Non-numeric age is rejected."""
    s = dict(_AGE_SPEC)
    s["age"] = "old"
    with pytest.raises(SpecError, match="age must be a number"):
        compile_spec(s)


# ── Blender-dependent entropy tests ──────────────────────────────


def test_deformed_mesh_passes_gate(tmp_path):
    """A table built with age=1.0 (max entropy) still passes the gate."""
    spec = dict(_AGE_SPEC)
    spec["age"] = 1.0
    glb = _build(tmp_path, spec, "aged_table.glb")
    res = gate_asset(glb, FOOTPRINT, HEIGHT)
    assert res.passed, f"gate failed for aged table: {res.reasons}"


def test_entropy_is_deterministic(tmp_path):
    """Two builds from the same spec produce identical meshes."""
    spec = dict(_AGE_SPEC)
    spec["age"] = 0.8

    glb1 = _build(tmp_path, spec, "det1.glb")
    glb2 = _build(tmp_path, spec, "det2.glb")

    m1 = _load_mesh(glb1)
    m2 = _load_mesh(glb2)

    # Same vertex count
    assert m1.vertices.shape == m2.vertices.shape, (
        f"vertex count mismatch: {m1.vertices.shape} vs {m2.vertices.shape}"
    )

    # Vertices within floating-point epsilon
    assert np.allclose(m1.vertices, m2.vertices, atol=1e-6), (
        "vertex positions differ between two builds of the same spec"
    )


def test_age_changes_vertex_positions(tmp_path):
    """age=0.15 vs age=1.0 produce measurably different vertex positions.

    The RMS vertex displacement between the two meshes must be above a
    small threshold — age must actually perturb the geometry."""
    spec_low = dict(_AGE_SPEC)
    spec_low["age"] = 0.15
    spec_high = dict(_AGE_SPEC)
    spec_high["age"] = 1.0

    glb_low = _build(tmp_path, spec_low, "low_age.glb")
    glb_high = _build(tmp_path, spec_high, "high_age.glb")

    m_low = _load_mesh(glb_low)
    m_high = _load_mesh(glb_high)

    assert m_low.vertices.shape == m_high.vertices.shape, (
        f"vertex count mismatch: {m_low.vertices.shape} vs {m_high.vertices.shape}"
    )

    # RMS vertex displacement
    diff = np.linalg.norm(m_high.vertices - m_low.vertices, axis=1)
    rms = float(diff.mean())

    assert rms > 0.0005, (
        f"RMS vertex displacement ({rms:.6f}) between age=0.15 and age=1.0 too small; "
        f"age may not be deforming the mesh"
    )
