"""Deterministic asset gate. Cheap, objective checks on an exported GLB before it
enters the library: watertight, polygon budget, non-degenerate, and bounds within
the lexicon's footprint/height envelope (the free ground-truth oracle).

GLB convention (Blender glTF export is Y-up): extents are [width=X, height=Y,
depth=Z]. Slice 1 has no asset-class-aware exceptions (e.g. campfire logs that
*should* intersect) — that arrives with the style grammar."""

from __future__ import annotations

from dataclasses import dataclass

import trimesh


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]


def gate_asset(
    glb_path: str,
    footprint: dict,
    height: float,
    poly_budget: int = 2000,
    tol: float = 0.15,
) -> GateResult:
    reasons: list[str] = []

    mesh = trimesh.load(glb_path, force="mesh")
    if mesh is None or mesh.is_empty:
        return GateResult(False, ["empty mesh"])

    ext = mesh.extents  # [x, y, z]
    width, h, depth = float(ext[0]), float(ext[1]), float(ext[2])

    # Non-degenerate: every dimension must have real size.
    for name, value in (("width", width), ("height", h), ("depth", depth)):
        if value < 0.01:
            reasons.append(f"degenerate {name}={value:.4f} (< 0.01)")

    # Bounds: must fit the placement envelope (upper bound with tolerance).
    if width > footprint["width"] * (1 + tol):
        reasons.append(f"width {width:.3f} exceeds footprint {footprint['width']} (+{tol:.0%})")
    if depth > footprint["depth"] * (1 + tol):
        reasons.append(f"depth {depth:.3f} exceeds footprint {footprint['depth']} (+{tol:.0%})")
    if h > height * (1 + tol):
        reasons.append(f"height {h:.3f} exceeds {height} (+{tol:.0%})")

    # Watertight (manifold-ish): every edge shared by exactly two faces.
    if not mesh.is_watertight:
        reasons.append("mesh is not watertight")

    # Polygon budget.
    n_faces = int(mesh.faces.shape[0])
    if n_faces > poly_budget:
        reasons.append(f"polygon budget exceeded: {n_faces} > {poly_budget}")

    return GateResult(len(reasons) == 0, reasons)
