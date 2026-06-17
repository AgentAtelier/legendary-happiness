"""Scene Graph — wraps the serialized Godot scene tree.

Provides node lookup, path resolution, and type queries that
the validator and completeness checker need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# REVIEW (Issue 2): VALID_GODOT_TYPES now lives in godot_node_types as the
# single source of truth (also used to generate arch_planner.gbnf's
# godot-type enum). Re-exported here for backward compatibility.
from devforge.knowledge.scene.godot_node_types import (  # noqa: F401
    VALID_GODOT_TYPES,
)


@dataclass
class SceneNode:
    name: str
    type: str
    path: str
    children: List["SceneNode"] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    signals: List[str] = field(default_factory=list)


class SceneGraph:
    """Parsed representation of the Godot scene tree."""

    def __init__(self, scene_data: Dict[str, Any]):
        name = scene_data.get("name", "Node")
        # In Godot, the edited scene root is at /root/NodeName
        root_path = f"/root/{name}"
        self.root = self._parse_node(scene_data, root_path)
        self._index: Dict[str, SceneNode] = {}
        # Also index under /root for convenience
        self._build_index(self.root)
        self._index["/root"] = self.root

    def _parse_node(self, data: Dict[str, Any], path: str) -> SceneNode:
        name = data.get("name", "Node")
        node_type = data.get("type", "Node")

        node = SceneNode(
            name=name,
            type=node_type,
            path=path,
        )

        for child_data in data.get("children", []):
            child_name = child_data.get("name", "Node")
            child_path = f"{path}/{child_name}"
            child = self._parse_node(child_data, child_path)
            node.children.append(child)

        return node

    def _build_index(self, node: SceneNode) -> None:
        self._index[node.path] = node
        for child in node.children:
            self._build_index(child)

    def find_by_path(self, path: str) -> Optional[SceneNode]:
        return self._index.get(path)

    def find_by_name(self, name: str) -> Optional[SceneNode]:
        """Find a node by its name (case-insensitive), returning the first match.

        Used by the architecture compiler to resolve connection targets
        (entity names) to full scene paths for signal wiring (T1).
        """
        name_lower = name.lower()
        for node in self._index.values():
            if node.name.lower() == name_lower:
                return node
        return None

    def has_path(self, path: str) -> bool:
        return path in self._index

    def has_node_type(self, node_type: str) -> bool:
        return any(n.type == node_type for n in self._index.values())

    def all_paths(self) -> List[str]:
        return list(self._index.keys())

    def all_nodes(self) -> List[SceneNode]:
        return list(self._index.values())

    def to_text(self, max_nodes: int = 100) -> str:
        lines = []
        count = 0

        def walk(node: SceneNode, depth: int = 0):
            nonlocal count
            if count >= max_nodes:
                return
            indent = "  " * depth
            lines.append(f"{indent}- {node.name} ({node.type})")
            count += 1
            for child in node.children:
                walk(child, depth + 1)

        walk(self.root)
        if count >= max_nodes:
            lines.append("... (truncated)")
        return "\n".join(lines)

    @staticmethod
    def is_valid_godot_type(type_name: str) -> bool:
        return type_name in VALID_GODOT_TYPES
