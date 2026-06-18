"""Tests for the asset quality-bump feature (hard-surface foundry).
Task 1: object-space warped stepped wood shader.
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

from gate import gate_asset

BLENDER = shutil.which("blender")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = pytest.mark.skipif(BLENDER is None, reason="blender not installed")

FOOTPRINT = {"width": 2.0, "depth": 1.5}
HEIGHT = 1.2


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
