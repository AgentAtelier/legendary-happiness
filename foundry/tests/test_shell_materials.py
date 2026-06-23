"""Blender-gated regression test for the room-shell texture generator.

Guards against the old failure mode (single-octave grey Voronoi ramp, ~0.15
luminance spread, no structure). Skips where Blender is unavailable; the
orchestrator runs the real bake.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

blender = shutil.which("blender")
pytestmark = pytest.mark.skipif(blender is None, reason="blender not installed")

GEN = Path(__file__).resolve().parent.parent / "blender" / "shell_materials.py"


def test_generates_stone_and_timber_with_contrast(tmp_path):
    subprocess.run(
        [blender, "--background", "--python", str(GEN), "--", str(tmp_path), "512"],
        check=True, capture_output=True, timeout=300,
    )
    names = [f"shell_{s}_{m}.png" for s in ("stone", "timber")
             for m in ("albedo", "normal", "orm")]
    for n in names:
        assert (tmp_path / n).exists(), f"missing {n}"

    # Anti-regression: albedo must have real contrast (old grey mush ~0.15 spread)
    from PIL import Image
    import numpy as np
    for surf in ("stone", "timber"):
        a = np.asarray(Image.open(tmp_path / f"shell_{surf}_albedo.png").convert("RGB")) / 255.0
        lum = a @ [0.2126, 0.7152, 0.0722]
        spread = float(lum.max() - lum.min())
        assert spread >= 0.30, f"{surf} albedo too flat ({spread:.2f}) — grey-mush regression"
