import os
import shutil
import subprocess
from pathlib import Path

import pytest

BLENDER = shutil.which("blender")
RENDER = str(Path(__file__).resolve().parents[1] / "blender" / "render_asset.py")
BUILD = str(Path(__file__).resolve().parents[1] / "blender" / "build_asset.py")
SPEC = str(Path(__file__).resolve().parents[1] / "specs" / "table.json")

pytestmark = [pytest.mark.skipif(BLENDER is None, reason="blender not installed"), pytest.mark.blender]


def test_render_writes_png(tmp_path):
    glb = str(tmp_path / "table.glb")
    subprocess.run(
        [BLENDER, "--background", "--python", BUILD, "--", SPEC, glb],
        capture_output=True, text=True, timeout=180, check=True,
    )
    png = str(tmp_path / "table.png")
    proc = subprocess.run(
        [BLENDER, "--background", "--python", RENDER, "--", glb, png],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert os.path.exists(png) and os.path.getsize(png) > 0
