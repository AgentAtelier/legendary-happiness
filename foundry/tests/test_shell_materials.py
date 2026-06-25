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
pytestmark = [pytest.mark.skipif(blender is None, reason="blender not installed"), pytest.mark.blender]

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
    import numpy as np
    from PIL import Image
    for surf in ("wall", "roof", "timber"):
        a = np.asarray(Image.open(tmp_path / f"shell_{surf}_albedo.png").convert("RGB")) / 255.0
        lum = a @ [0.2126, 0.7152, 0.0722]
        spread = float(lum.max() - lum.min())
        assert spread >= 0.30, f"{surf} albedo too flat ({spread:.2f}) — grey-mush regression"

    # Task 4: shell-contrast — assert a non-trivial normal map is produced
    for surf in ("wall", "roof", "timber"):
        n_img = np.asarray(Image.open(tmp_path / f"shell_{surf}_normal.png").convert("RGB"))
        # Normal maps should have variation (not all the same flat colour)
        n_spread = float(n_img.std())
        assert n_spread > 5.0, (
            f"{surf} normal map too uniform (std={n_spread:.1f}) — "
            f"non-trivial normal depth required"
        )

    # Task 2: wall vs ceiling/roof — materials differ
    wall_a = np.asarray(Image.open(tmp_path / "shell_wall_albedo.png").convert("RGB")) / 255.0
    roof_a = np.asarray(Image.open(tmp_path / "shell_roof_albedo.png").convert("RGB")) / 255.0
    wall_mean = float(wall_a.mean(axis=(0, 1)) @ [0.2126, 0.7152, 0.0722])
    roof_mean = float(roof_a.mean(axis=(0, 1)) @ [0.2126, 0.7152, 0.0722])
    assert abs(wall_mean - roof_mean) > 0.05, (
        f"Task 2: wall and roof albedo too similar "
        f"(wall={wall_mean:.3f}, roof={roof_mean:.3f}) — should differ"
    )
