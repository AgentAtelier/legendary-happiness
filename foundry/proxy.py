"""foundry.proxy — deterministic box-mesh → voxel proxy for Hunyuan conditioning.

WS-5: Converts a procedural generator's output mesh (GLB) into a .ply point cloud
that the orchestrator's Hunyuan-Omni pipeline consumes as voxel/bbox conditioning.

Pure Python (trimesh + numpy), fully deterministic for a given (glb_path, seed) pair.

Usage:
    from proxy import voxelize_glb
    voxelize_glb("path/to/mesh.glb", "path/to/output.ply", resolution=64, seed=42)
The .ply contains only vertex positions (x, y, z) — the voxel centres inside the mesh.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import trimesh
    _HAS_TRIMESH = True
except ImportError:
    _HAS_TRIMESH = False


# ── safety bounds (incident 2026-06-23: unbounded contains() OOM-killed the host) ──
_MAX_RESOLUTION = 96          # 96³ ≈ 884k grid points (~21 MB) — caps the grid array
_PROXY_FACE_CAP = 20_000      # decimate denser meshes before point-in-mesh testing
_CONTAINS_BUDGET = 8_000_000  # max (batch × faces) per contains() call (~64 MB peak)


def _chunk_size(n_faces: int) -> int:
    """Points per contains() batch, sized so ``batch × faces`` stays under budget."""
    return max(256, min(8192, _CONTAINS_BUDGET // max(1, int(n_faces))))


def _contains_chunked(mesh, points: np.ndarray) -> np.ndarray:
    """``mesh.contains()`` in face-aware batches so peak memory is BOUNDED
    regardless of grid size or mesh complexity. Without embreex, trimesh's
    fallback allocates O(points × faces); doing the whole grid at once is what
    OOM-killed the host on 2026-06-23."""
    n_faces = len(getattr(mesh, "faces", ())) or 1
    batch = _chunk_size(n_faces)
    out = np.zeros(len(points), dtype=bool)
    for i in range(0, len(points), batch):
        out[i:i + batch] = mesh.contains(points[i:i + batch])
    return out


def _decimate_to_cap(mesh):
    """Reduce very dense meshes before containment (keeps ``batch × faces`` bounded
    even in the pathological case); a coarse proxy doesn't need fine detail."""
    try:
        if len(mesh.faces) <= _PROXY_FACE_CAP:
            return mesh
        out = mesh.simplify_quadric_decimation(face_count=_PROXY_FACE_CAP)
        return out if out is not None and len(out.faces) > 0 else mesh
    except Exception:
        return mesh


# ── voxelisation ─────────────────────────────────────────────────

def voxelize_glb(
    glb_path: str,
    out_ply: str,
    *,
    resolution: int = 64,
    seed: Optional[int] = None,
    pad: float = 0.05,
) -> int:
    """Convert a GLB mesh into an ASCII .ply voxel point cloud.

    The mesh is watertight-checked, then a resolution³ grid is sampled;
    only points inside the mesh surface are emitted.  The same mesh +
    resolution always produces byte-identical output (no wall-clock or
    unseeded RNG in the pipeline).

    Args:
        glb_path: Path to the input GLB/GLTF mesh.
        out_ply: Path to write the ASCII PLY.
        resolution: Number of sample slices per axis (default 64 → 64³ grid).
        seed: Reserved; accepted for API consistency (currently unused).
        pad: Fraction of max extent added to each side of the AABB (default 0.05).

    Returns:
        Number of voxel points written to the PLY file.
    """
    _ = seed  # reserved — deterministic by construction

    # Safety clamp: cap the grid so it can never materialize a multi-GB array
    # (incident 2026-06-23: a huge resolution³ grid + faces OOM-killed the host).
    resolution = max(2, min(int(resolution), _MAX_RESOLUTION))
    os.makedirs(os.path.dirname(os.path.abspath(out_ply)) or ".", exist_ok=True)

    mesh = _load_watertight(glb_path)
    bbox_lo, bbox_hi, voxel_size = _compute_grid(mesh, resolution, pad)
    points = _sample_voxels(mesh, bbox_lo, bbox_hi, resolution, voxel_size)
    _write_ply(out_ply, points)
    return len(points)


# ── internal helpers ─────────────────────────────────────────────

def _load_watertight(glb_path: str) -> "trimesh.Trimesh":
    """Load a GLB and return a single watertight Trimesh.

    Raises RuntimeError if trimesh is unavailable; warns (but does not
    fail) if the mesh appears non-watertight.
    """
    if not _HAS_TRIMESH:
        raise RuntimeError("trimesh is required for proxy voxelisation.  "
                           "Install with: pip install trimesh")

    scene_or_mesh = trimesh.load(glb_path, force="mesh")

    if isinstance(scene_or_mesh, trimesh.Scene):
        # Concatenate all geometry into one mesh
        geometries = list(scene_or_mesh.geometry.values())
        if not geometries:
            raise ValueError(f"No geometry found in GLB: {glb_path}")
        mesh = trimesh.util.concatenate(geometries)
    else:
        mesh = scene_or_mesh

    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Expected Trimesh, got {type(mesh)} from {glb_path}")

    if not mesh.is_watertight:
        # Non-fatal warning — contains() may still work well enough
        import warnings
        warnings.warn(f"Mesh {glb_path} is not watertight; voxel containment may be unreliable.")

    return _decimate_to_cap(mesh)


def _compute_grid(
    mesh: "trimesh.Trimesh",
    resolution: int,
    pad: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Compute padded AABB and voxel size for the given mesh.

    Returns (bbox_lo, bbox_hi, voxel_size) where voxel_size is the
    spacing along the largest axis.
    """
    bbox_lo = mesh.bounds[0].copy()
    bbox_hi = mesh.bounds[1].copy()
    extent = bbox_hi - bbox_lo
    padding = extent.max() * pad
    bbox_lo -= padding
    bbox_hi += padding

    # Voxel size derived from the largest axis
    voxel_size = (bbox_hi - bbox_lo).max() / (resolution - 1)
    return bbox_lo, bbox_hi, voxel_size


def _sample_voxels(
    mesh: "trimesh.Trimesh",
    bbox_lo: np.ndarray,
    bbox_hi: np.ndarray,
    resolution: int,
    voxel_size: float,
) -> np.ndarray:
    """Generate a resolution³ grid and return points inside the mesh.

    Points are offset by half a voxel so they sit at voxel centres.
    """
    # Per-axis linspace — spacing varies per axis if mesh is non-cubic
    xs = np.linspace(bbox_lo[0] + voxel_size / 2, bbox_hi[0] - voxel_size / 2, resolution)
    ys = np.linspace(bbox_lo[1] + voxel_size / 2, bbox_hi[1] - voxel_size / 2, resolution)
    zs = np.linspace(bbox_lo[2] + voxel_size / 2, bbox_hi[2] - voxel_size / 2, resolution)

    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    points = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])

    inside = _contains_chunked(mesh, points)
    return points[inside]


def _write_ply(out_path: str, points: np.ndarray) -> None:
    """Write a minimal ASCII .ply point cloud.

    ASCII PLY is chosen over binary for readability and determinism —
    the same point array always produces byte-identical output.
    """
    n = len(points)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("end_header\n")
        for p in points:
            f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")


def _hash_points(points: np.ndarray) -> str:
    """Return a deterministic hex digest for a point array (testing)."""
    raw = points.astype(np.float32).tobytes()
    return hashlib.sha256(raw).hexdigest()[:16]
