"""Blender HIP lighting-bake test.

Bakes a tiny floor+box scene and asserts the exported GLB carries baked vertex
colours (COLOR_0). Skipped when Blender isn't installed. (Cycles GPU bakes are
not bit-deterministic run-to-run — fine, since the *cache key* is deterministic
in lighting_bake; we bake once and reuse.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BLENDER = shutil.which("blender")
BAKE = str(Path(__file__).resolve().parents[1] / "blender" / "bake_lighting.py")

pytestmark = [pytest.mark.skipif(BLENDER is None, reason="blender not installed"), pytest.mark.blender]

_DESC = {
    "placements": [
        {"primitive": "plane", "size": 8.0, "location": [0, 0, 0], "subdivide": 5},
        {"primitive": "box", "size": 1.0, "location": [0, 0, 0.5], "subdivide": 4},
    ],
    "sun": {"direction": [0.3, -0.6, -0.7], "energy": 3.0, "color": [1, 0.95, 0.9]},
    "sky": {"top": [0.4, 0.55, 0.85], "horizon": [0.6, 0.6, 0.6], "ambient_energy": 0.5},
    "tier": 2, "samples": 16,
}


def test_bake_produces_vertex_colored_glb(tmp_path):
    desc_p = tmp_path / "desc.json"
    desc_p.write_text(json.dumps(_DESC))
    out = tmp_path / "out"
    out.mkdir()
    r = subprocess.run(
        [BLENDER, "-b", "--python", BAKE, "--", str(desc_p), str(out)],
        capture_output=True, text=True, timeout=400,
    )
    assert r.returncode == 0, (r.stderr or r.stdout)[-2000:]
    glb = out / "baked.glb"
    assert glb.exists(), "no baked GLB written"
    data = glb.read_bytes()
    assert b"COLOR_0" in data, "baked GI not exported as vertex colours"
    assert len(data) > 1000
