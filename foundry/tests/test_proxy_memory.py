"""Regression tests for the proxy.py OOM incident (2026-06-23).

The host was OOM-killed because `mesh.contains()` was called on the whole
resolution³ grid at once; without embreex, trimesh's fallback allocates
O(points × faces) with no ceiling. These lock in the bounded-memory fix +
the resolution / div-by-zero / output-dir guards the WS-5 review flagged.
"""

from __future__ import annotations

import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")

from proxy import _chunk_size, _contains_chunked, voxelize_glb  # noqa: E402


def test_contains_chunked_matches_single_call():
    mesh = trimesh.creation.icosphere(subdivisions=3)
    pts = np.random.RandomState(0).uniform(-1.5, 1.5, (6000, 3))
    chunked = _contains_chunked(mesh, pts)
    single = mesh.contains(pts)
    assert chunked.dtype == bool
    assert (chunked == single).all()


def test_chunk_size_shrinks_with_face_count():
    # peak memory ~ batch * faces, so batch must shrink as faces grow
    assert _chunk_size(100) >= _chunk_size(100_000)
    assert _chunk_size(10_000_000) >= 1  # never zero
    assert _chunk_size(1) <= 8192        # and capped


def test_high_resolution_is_clamped(tmp_path):
    m = trimesh.creation.box()
    g = tmp_path / "b.glb"
    m.export(str(g))
    out = tmp_path / "b.ply"
    n = voxelize_glb(str(g), str(out), resolution=100_000)  # absurd → clamped, no OOM
    assert out.exists() and n >= 0


def test_resolution_one_no_div_by_zero(tmp_path):
    m = trimesh.creation.box()
    g = tmp_path / "b.glb"
    m.export(str(g))
    out = tmp_path / "b.ply"
    voxelize_glb(str(g), str(out), resolution=1)  # previously ZeroDivisionError
    assert out.exists()


def test_creates_missing_output_dir(tmp_path):
    m = trimesh.creation.box()
    g = tmp_path / "b.glb"
    m.export(str(g))
    out = tmp_path / "a" / "b" / "c.ply"  # parent dirs do not exist
    voxelize_glb(str(g), str(out))
    assert out.exists()
