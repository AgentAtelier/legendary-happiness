"""Shared Godot resource/mesh/shape/material template dicts.

Used by ArchitectureCompiler (props→SetPropertyStep), OpsPlanner
(prompt examples), and CompletenessChecker (scaffold defaults).

Single source of truth — update here and all consumers stay in sync.
"""

from __future__ import annotations

from typing import Dict

# ── Mesh resources (for MeshInstance3D.mesh) ────────────────────
# Maps the grammar-bounded "mesh" prop value → Godot resource dict.
MESH_RESOURCES: Dict[str, dict] = {
    "box": {"__class__": "BoxMesh", "size": {"x": 1, "y": 1, "z": 1}},
    "sphere": {"__class__": "SphereMesh", "radius": 1, "height": 2},
    "capsule": {"__class__": "CapsuleMesh", "radius": 0.5, "height": 2},
    "plane": {"__class__": "PlaneMesh", "size": {"x": 10, "y": 10}},
    "cylinder": {
        "__class__": "CylinderMesh",
        "top_radius": 0.5,
        "bottom_radius": 0.5,
        "height": 2,
    },
}

# ── Shape resources (for CollisionShape3D.shape) ───────────────
SHAPE_RESOURCES: Dict[str, dict] = {
    "box": {"__class__": "BoxShape3D", "size": {"x": 1, "y": 1, "z": 1}},
    "sphere": {"__class__": "SphereShape3D", "radius": 0.5},
    "capsule": {"__class__": "CapsuleShape3D", "radius": 0.5, "height": 2},
    "cylinder": {"__class__": "CylinderShape3D", "radius": 0.5, "height": 2},
}

# ── Material template (for material_override on MeshInstance3D) ─
def make_material(r: float, g: float, b: float, a: float = 1.0) -> dict:
    """Build a StandardMaterial3D resource dict with the given albedo color."""
    return {
        "__class__": "StandardMaterial3D",
        "albedo_color": {"r": r, "g": g, "b": b, "a": a},
    }


# Default red material used as a scaffold fallback.
DEFAULT_MATERIAL = make_material(1.0, 0.0, 0.0)
