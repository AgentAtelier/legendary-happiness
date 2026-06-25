"""Unit tests for foundry.proxy — WS-5 deterministic voxel proxy."""

from pathlib import Path

import numpy as np
import pytest

try:
    import trimesh
    _HAS_TRIMESH = True
except ImportError:
    _HAS_TRIMESH = False

from proxy import (
    _compute_grid,
    _hash_points,
    _load_watertight,
    _sample_voxels,
    _write_ply,
    voxelize_glb,
)

# ── helpers ─────────────────────────────────────────────────────

def _make_box_mesh(tmp_path: Path) -> str:
    """Create a simple box mesh GLB for testing."""
    if not _HAS_TRIMESH:
        pytest.skip("trimesh not available")
    box = trimesh.creation.box(extents=(1.0, 0.5, 0.3))
    path = tmp_path / "test_box.glb"
    box.export(str(path))
    return str(path)


def _read_ply_ascii(ply_path: str) -> np.ndarray:
    """Read ASCII PLY vertex positions back into an (N, 3) array."""
    with open(ply_path, encoding="utf-8") as f:
        lines = f.readlines()
    header_end = next(i for i, line in enumerate(lines) if line.strip() == "end_header")
    pts = []
    for line in lines[header_end + 1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return np.array(pts)


# ── voxelisation end-to-end ─────────────────────────────────────

@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_voxelize_glb_produces_ply(tmp_path):
    """voxelize_glb writes a valid PLY file with points inside the mesh."""
    glb = _make_box_mesh(tmp_path)
    out = tmp_path / "out.ply"
    n = voxelize_glb(glb, str(out), resolution=16, seed=42)
    assert out.exists()
    assert n > 0

    pts = _read_ply_ascii(str(out))
    assert len(pts) == n
    assert pts.shape[1] == 3
    # All points should be within the padded AABB of the box (1.0 x 0.5 x 0.3)
    mesh = trimesh.load(glb, force="mesh")
    # With pad=0.05 and extents ~1.0, bbox should be [-0.55, -0.30, -0.20] to [0.55, 0.30, 0.20] approx
    assert pts[:, 0].min() >= -0.7 and pts[:, 0].max() <= 0.7
    assert pts[:, 1].min() >= -0.45 and pts[:, 1].max() <= 0.45
    assert pts[:, 2].min() >= -0.35 and pts[:, 2].max() <= 0.35


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_voxelize_determinism(tmp_path):
    """Same mesh + resolution → byte-identical PLY output."""
    glb = _make_box_mesh(tmp_path)
    out1 = tmp_path / "out1.ply"
    out2 = tmp_path / "out2.ply"

    n1 = voxelize_glb(glb, str(out1), resolution=20, seed=42)
    n2 = voxelize_glb(glb, str(out2), resolution=20, seed=42)

    assert n1 == n2
    assert out1.read_bytes() == out2.read_bytes()


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_voxelize_resolution_scaling(tmp_path):
    """Higher resolution produces more voxels."""
    glb = _make_box_mesh(tmp_path)
    n_low = voxelize_glb(glb, str(tmp_path / "low.ply"), resolution=8, seed=42)
    n_high = voxelize_glb(glb, str(tmp_path / "high.ply"), resolution=16, seed=42)
    # 16³ has 8x the total grid points of 8³; inside count should scale roughly
    assert n_high > n_low


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_voxelize_no_trimesh_raises(tmp_path):
    """Graceful error when trimesh is unavailable."""
    glb = _make_box_mesh(tmp_path)
    out = tmp_path / "out.ply"

    import proxy as proxy_mod
    original = proxy_mod._HAS_TRIMESH
    try:
        proxy_mod._HAS_TRIMESH = False
        with pytest.raises(RuntimeError, match="trimesh"):
            proxy_mod.voxelize_glb(glb, str(out), resolution=8)
    finally:
        proxy_mod._HAS_TRIMESH = original


# ── _load_watertight ────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_load_watertight_returns_trimesh(tmp_path):
    """_load_watertight returns a trimesh.Trimesh for a valid GLB."""
    glb = _make_box_mesh(tmp_path)
    mesh = _load_watertight(glb)
    assert isinstance(mesh, trimesh.Trimesh)


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_load_watertight_missing_file():
    """_load_watertight raises on missing GLB."""
    with pytest.raises((FileNotFoundError, OSError, ValueError)):
        _load_watertight("/nonexistent/path/mesh.glb")


# ── _compute_grid ───────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_compute_grid_returns_tuple_of_three():
    """_compute_grid returns (bbox_lo, bbox_hi, voxel_size)."""
    mesh = trimesh.creation.box(extents=(1.0, 0.5, 0.3))
    result = _compute_grid(mesh, resolution=16, pad=0.05)
    assert len(result) == 3
    bbox_lo, bbox_hi, voxel_size = result
    assert bbox_lo.shape == (3,)
    assert bbox_hi.shape == (3,)
    assert isinstance(voxel_size, float)
    assert voxel_size > 0
    # Padded bbox should be larger than original
    assert (bbox_lo < mesh.bounds[0]).all()
    assert (bbox_hi > mesh.bounds[1]).all()


# ── _sample_voxels ──────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_sample_voxels_all_inside_box():
    """All returned points are within the padded bbox."""
    mesh = trimesh.creation.box(extents=(1.0, 0.5, 0.3))
    res = 16
    bbox_lo, bbox_hi, voxel_size = _compute_grid(mesh, resolution=res, pad=0.05)
    pts = _sample_voxels(mesh, bbox_lo, bbox_hi, res, voxel_size)
    assert len(pts) > 0
    for dim in range(3):
        assert (pts[:, dim] >= bbox_lo[dim]).all()
        assert (pts[:, dim] <= bbox_hi[dim]).all()


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_sample_voxels_within_mesh_contains():
    """Sampled voxels are verified inside the mesh via trimesh.contains()."""
    mesh = trimesh.creation.box(extents=(1.0, 0.5, 0.3))
    res = 12
    bbox_lo, bbox_hi, voxel_size = _compute_grid(mesh, resolution=res, pad=0.05)
    pts = _sample_voxels(mesh, bbox_lo, bbox_hi, res, voxel_size)
    # Re-verify with contains
    assert mesh.contains(pts).all()


# ── _write_ply ─────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_write_ply_header_format(tmp_path):
    """_write_ply produces valid ASCII PLY with correct header."""
    pts = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    out = tmp_path / "test.ply"
    _write_ply(str(out), pts)

    content = out.read_text(encoding="utf-8")
    assert content.startswith("ply\n")
    assert "format ascii 1.0" in content
    assert "element vertex 2" in content
    assert "property float x" in content
    assert "property float y" in content
    assert "property float z" in content
    assert "end_header" in content


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_write_ply_determinism(tmp_path):
    """Same points → byte-identical PLY."""
    pts = np.array([[1.123456, 2.654321, 3.0], [0.1, 0.2, 0.3]])
    out1 = tmp_path / "a.ply"
    out2 = tmp_path / "b.ply"
    _write_ply(str(out1), pts)
    _write_ply(str(out2), pts)
    assert out1.read_bytes() == out2.read_bytes()


@pytest.mark.skipif(not _HAS_TRIMESH, reason="trimesh not installed")
def test_write_ply_empty_points(tmp_path):
    """_write_ply handles zero-point arrays gracefully."""
    pts = np.empty((0, 3))
    out = tmp_path / "empty.ply"
    _write_ply(str(out), pts)
    content = out.read_text(encoding="utf-8")
    assert "element vertex 0" in content


# ── _hash_points ─────────────────────────────────────────────────

def test_hash_points_deterministic():
    """Same array → same hash."""
    pts = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    assert _hash_points(pts) == _hash_points(pts)


def test_hash_points_different_arrays_differ():
    """Different arrays produce different hashes."""
    a = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    b = np.array([[1.0, 2.0, 3.1]], dtype=np.float32)
    assert _hash_points(a) != _hash_points(b)
