"""Unit tests for foundry.hunyuan_postprocess — decimate / scale-normalize / cache."""

from __future__ import annotations

import os

import pytest

trimesh = pytest.importorskip("trimesh")

from hunyuan_postprocess import (  # noqa: E402
    content_cache_key,
    decimate,
    scale_normalize,
    sit_on_ground,
)


def test_decimate_reduces_or_noops():
    m = trimesh.creation.icosphere(subdivisions=4)  # ~5120 faces
    out = decimate(m, 500)
    # With a decimation backend → <= 500; without → graceful no-op (unchanged).
    assert len(out.faces) <= 500 or len(out.faces) == len(m.faces)


def test_decimate_noop_when_under_budget():
    m = trimesh.creation.box()
    out = decimate(m, 10_000)
    assert len(out.faces) == len(m.faces)


def test_scale_normalize_fits_target():
    m = trimesh.creation.box(extents=[4.0, 2.0, 6.0])
    scale_normalize(m, (1.0, 0.75, 1.0))
    for e, t in zip(m.extents, (1.0, 0.75, 1.0)):
        assert e <= t + 1e-6


def test_scale_normalize_preserves_aspect():
    m = trimesh.creation.box(extents=[2.0, 1.0, 2.0])
    scale_normalize(m, (1.0, 1.0, 1.0))
    ext = m.extents
    # aspect 2:1:2 preserved
    assert abs(ext[0] / ext[1] - 2.0) < 1e-4
    assert abs(ext[2] / ext[1] - 2.0) < 1e-4


def test_sit_on_ground():
    m = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    m.apply_translation([0, 5.0, 0])
    sit_on_ground(m)
    assert abs(m.bounds[0][1]) < 1e-6  # min Y at 0


def test_cache_key_deterministic_and_distinct():
    a = content_cache_key(proxy_hash="abc", seed=1, model_version="omni-2.1")
    b = content_cache_key(proxy_hash="abc", seed=1, model_version="omni-2.1")
    c = content_cache_key(proxy_hash="xyz", seed=1, model_version="omni-2.1")
    assert a == b and len(a) == 16
    assert a != c


_MUG = "/home/mrg/dev/hunyuan-spike/Hunyuan3D-Omni/omni_inference_results/3domni_voxel/1c1ff58afbf4455ca80228d280f86aef.glb"  # noqa: E501  path


@pytest.mark.skipif(not os.path.exists(_MUG), reason="Hunyuan sample mesh absent")
def test_real_hunyuan_mesh_decimates_and_fits_envelope():
    mesh = trimesh.load(_MUG, force="mesh")
    raw_faces = len(mesh.faces)
    mesh = decimate(mesh, 2000)
    scale_normalize(mesh, (0.12, 0.12, 0.12))  # a ~12 cm mug
    sit_on_ground(mesh)
    assert len(mesh.faces) <= raw_faces
    for e in mesh.extents:
        assert e <= 0.12 + 1e-4
    assert abs(mesh.bounds[0][1]) < 1e-5
