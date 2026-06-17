"""Deterministic scene audit rules.

Each rule is a function ``(graph: SceneGraph, props_lookup) -> list[Violation]``.
Rules tolerate malformed input — never raise.  No LLM anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from devforge.knowledge.scene.scene_graph import SceneGraph, SceneNode

# ── Godot type constants ────────────────────────────────────────

# Mirrors Godot's CollisionObject3D subclass hierarchy (engine v4.x).
# When Godot adds a new CollisionObject3D subclass, add it here.
COLLISION_OBJECT_TYPES: set[str] = {
    "CharacterBody3D",
    "RigidBody3D",
    "StaticBody3D",
    "AnimatableBody3D",
    "Area3D",
    "VehicleBody3D",
}

SHAPE_TYPES: set[str] = {"CollisionShape3D", "CollisionPolygon3D"}


# ── Violation data class ────────────────────────────────────────


@dataclass
class Violation:
    """A rule violation found during scene audit."""

    rule_id: str  # "R1".."R5"
    severity: str  # "CRITICAL" | "WARNING" | "INFO"
    node_path: str  # "/root/Main/Player"
    message: str  # what is wrong, one sentence, names the node
    suggestion: str  # how to fix it, one sentence, concrete

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "node_path": self.node_path,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# ── Helpers ─────────────────────────────────────────────────────


def _parent_path(node_path: str) -> str:
    """Return the parent path of a scene node path.

    ``/root/Main/Player/Cam`` → ``/root/Main/Player``.
    ``/root`` → ``""`` (no parent — ``find_by_path`` returns None).
    """
    idx = node_path.rfind("/")
    return node_path[:idx] if idx > 0 else ""


def _siblings(graph: SceneGraph, parent_path: str) -> list[SceneNode]:
    """Return all direct children of *parent_path*."""
    parent = graph.find_by_path(parent_path)
    if parent is None:
        return []
    return parent.children


# ── Rules ───────────────────────────────────────────────────────


def rule_r1(
    graph: SceneGraph,
    props_lookup: Callable[[str], dict | None] | None,
) -> list[Violation]:
    """R1: Every CollisionShape3D/CollisionPolygon3D must have a parent
    whose type is in ``COLLISION_OBJECT_TYPES``."""
    violations: list[Violation] = []
    for node in graph.all_nodes():
        if node.type not in SHAPE_TYPES:
            continue
        parent = graph.find_by_path(_parent_path(node.path))
        parent_type = parent.type if parent else "N/A"
        if parent is None or parent.type not in COLLISION_OBJECT_TYPES:
            violations.append(
                Violation(
                    rule_id="R1",
                    severity="CRITICAL",
                    node_path=node.path,
                    message=(
                        f"{node.type} '{node.name}' has parent type "
                        f"'{parent_type}' — must be a CollisionObject3D subclass"
                    ),
                    suggestion=(
                        f"Move '{node.name}' under a "
                        f"{', '.join(sorted(COLLISION_OBJECT_TYPES))} node, "
                        f"or change the parent type."
                    ),
                )
            )
    return violations


def rule_r2(
    graph: SceneGraph,
    props_lookup: Callable[[str], dict | None] | None,
) -> list[Violation]:
    """R2: Every node of a ``COLLISION_OBJECT_TYPES`` type must have at
    least one direct child of type CollisionShape3D or CollisionPolygon3D."""
    violations: list[Violation] = []
    for node in graph.all_nodes():
        if node.type not in COLLISION_OBJECT_TYPES:
            continue
        has_shape = any(child.type in SHAPE_TYPES for child in node.children)
        if not has_shape:
            violations.append(
                Violation(
                    rule_id="R2",
                    severity="CRITICAL",
                    node_path=node.path,
                    message=(
                        f"{node.type} '{node.name}' has no CollisionShape3D "
                        f"or CollisionPolygon3D child — it will fall through "
                        f"the world or pass through other bodies."
                    ),
                    suggestion=(f"Add a CollisionShape3D child to '{node.name}' and assign a Shape3D resource."),
                )
            )
    return violations


def rule_r3(
    graph: SceneGraph,
    props_lookup: Callable[[str], dict | None] | None,
) -> list[Violation]:
    """R3: If the scene contains exactly one Camera3D, its ``current``
    property must be truthy."""
    cameras = [n for n in graph.all_nodes() if n.type == "Camera3D"]

    if len(cameras) != 1:
        return []  # zero or multiple cameras — not actionable

    camera = cameras[0]

    if props_lookup is None:
        return [
            Violation(
                rule_id="R3",
                severity="INFO",
                node_path=camera.path,
                message="R3 skipped (no property access available)",
                suggestion=("Enable live property access (WO-004) or check manually that Camera3D.current is enabled."),
            )
        ]

    props = props_lookup(camera.path)
    if props is None:
        props = {}

    is_current = props.get("current", False)
    if not is_current:
        return [
            Violation(
                rule_id="R3",
                severity="WARNING",
                node_path=camera.path,
                message=(
                    f"Camera3D '{camera.name}' is the only camera in the "
                    f"scene but 'current' is not enabled — the game view "
                    f"may show the wrong camera or be black."
                ),
                suggestion=(
                    f"Enable 'current' on Camera3D '{camera.name}' in the "
                    f"Inspector, or call camera.current = true in a script."
                ),
            )
        ]
    return []


def rule_r4(
    graph: SceneGraph,
    props_lookup: Callable[[str], dict | None] | None,
) -> list[Violation]:
    """R4: Every MeshInstance3D must have a non-null ``mesh`` property."""
    violations: list[Violation] = []
    meshes = [n for n in graph.all_nodes() if n.type == "MeshInstance3D"]

    if props_lookup is None:
        return [
            Violation(
                rule_id="R4",
                severity="INFO",
                node_path="/",
                message="R4 skipped (no property access available)",
                suggestion=(
                    "Enable live property access (WO-004) or check manually that MeshInstance3D.mesh is assigned."
                ),
            )
        ]

    for mesh in meshes:
        props = props_lookup(mesh.path)
        if props is None:
            props = {}
        if props.get("mesh") is None:
            violations.append(
                Violation(
                    rule_id="R4",
                    severity="WARNING",
                    node_path=mesh.path,
                    message=(f"MeshInstance3D '{mesh.name}' has no mesh assigned — it renders nothing."),
                    suggestion=(f"Assign a Mesh resource to '{mesh.name}' in the Inspector, or add one via code."),
                )
            )
    return violations


def rule_r5(
    graph: SceneGraph,
    props_lookup: Callable[[str], dict | None] | None,
) -> list[Violation]:
    """R5: No two sibling nodes may share the same name."""
    violations: list[Violation] = []
    # Collect all parent paths that have children
    parent_paths: set[str] = set()
    for node in graph.all_nodes():
        if node.children:
            parent_paths.add(node.path)

    for pp in parent_paths:
        kids = _siblings(graph, pp)
        seen: dict[str, SceneNode] = {}
        for child in kids:
            name = getattr(child, "name", None)
            if name is None:
                continue  # malformed — skip
            if name in seen:
                # Report only once per duplicate name per parent
                if seen[name] is not None:
                    violations.append(
                        Violation(
                            rule_id="R5",
                            severity="WARNING",
                            node_path=seen[name].path,
                            message=(
                                f"Sibling name conflict: two nodes named "
                                f"'{name}' under '{pp}' — Godot silently "
                                f"renames on instancing, breaking NodePath refs."
                            ),
                            suggestion=(f"Rename one of the '{name}' nodes under '{pp}' to a unique name."),
                        )
                    )
                    seen[name] = None  # sentinel: already reported
            else:
                seen[name] = child
    return violations


# ── Rule registry ───────────────────────────────────────────────

ALL_RULES = [rule_r1, rule_r2, rule_r3, rule_r4, rule_r5]
