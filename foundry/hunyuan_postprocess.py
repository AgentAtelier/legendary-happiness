"""foundry.hunyuan_postprocess — make raw Hunyuan meshes gate-passable + cacheable.

Raw Hunyuan-Omni output is high-poly, arbitrary scale, and untextured. This module
is the bridge from that to a usable library base:

  * ``decimate`` — reduce to the poly budget (we don't need 512³ detail).
  * ``scale_normalize`` — center + uniformly scale to fit the lexicon envelope
    (so a generated "table" ends up ~0.75 m tall, matching the procedural world).
  * ``content_cache_key`` — a stable hash of (proxy, seed, model) so identical
    specs reuse the cached GLB → deterministic builds despite neural generation.

Pure (trimesh + stdlib); no GPU, no Hunyuan import. The slow neural step runs
elsewhere (the idle asset server); this turns its output into a shippable asset.
"""

from __future__ import annotations

import hashlib
import json

import trimesh


def decimate(mesh: trimesh.Trimesh, max_faces: int) -> trimesh.Trimesh:
    """Return *mesh* reduced to at most *max_faces* (no-op if already under, or
    if no decimation backend is available)."""
    if len(mesh.faces) <= max_faces:
        return mesh
    try:
        out = mesh.simplify_quadric_decimation(face_count=max_faces)
        return out if out is not None and len(out.faces) > 0 else mesh
    except Exception:
        return mesh


def scale_normalize(
    mesh: trimesh.Trimesh,
    target: tuple[float, float, float],
    *,
    center: bool = True,
) -> trimesh.Trimesh:
    """Center the mesh and uniformly scale it to FIT within *target* (w, h, d),
    preserving aspect ratio (the most-constraining dimension decides the scale).

    Mutates and returns *mesh*.
    """
    if center:
        mesh.apply_translation(-mesh.bounds.mean(axis=0))
    ext = mesh.extents
    factors = [t / e for t, e in zip(target, ext) if e > 1e-9]
    s = min(factors) if factors else 1.0
    mesh.apply_scale(s)
    return mesh


def sit_on_ground(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Shift the mesh up so its lowest point is at Y=0 (props rest on the floor)."""
    min_y = float(mesh.bounds[0][1])
    mesh.apply_translation([0.0, -min_y, 0.0])
    return mesh


def content_cache_key(*, proxy_hash: str, seed: int, model_version: str,
                      extra: str = "") -> str:
    """Stable 16-char content-address for a generated asset."""
    blob = json.dumps(
        {"p": proxy_hash, "s": int(seed), "m": model_version, "x": extra},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
