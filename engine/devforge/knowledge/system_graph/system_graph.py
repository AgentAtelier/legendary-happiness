"""System Graph — tracks the architecture of the game project.

This is the single source of truth for what systems, entities, and
scripts exist in the project and how they relate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class NodeType(str, Enum):
    SYSTEM = "system"
    ENTITY = "entity"
    SCRIPT = "script"


class EdgeType(str, Enum):
    USES = "uses"
    DEPENDS_ON = "depends_on"
    CONTROLS = "controls"


@dataclass
class GraphNode:
    id: str
    name: str
    type: NodeType
    metadata: Dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: EdgeType


class SystemGraph:
    """In-memory graph of the game architecture."""

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []

    def add_node(self, node_id: str, name: str, node_type: NodeType, **metadata) -> GraphNode:
        node = GraphNode(id=node_id, name=name, type=node_type, metadata=metadata)
        self.nodes[node_id] = node
        return node

    def add_edge(self, source: str, target: str, edge_type: EdgeType) -> GraphEdge:
        edge = GraphEdge(source=source, target=target, type=edge_type)
        self.edges.append(edge)
        return edge

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if e.source != node_id and e.target != node_id]

    def get_systems(self) -> List[GraphNode]:
        return [n for n in self.nodes.values() if n.type == NodeType.SYSTEM]

    def get_entities(self) -> List[GraphNode]:
        return [n for n in self.nodes.values() if n.type == NodeType.ENTITY]

    def topological_order(self) -> List[str]:
        """Return nodes in dependency order."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}

        for edge in self.edges:
            if edge.type == EdgeType.DEPENDS_ON and edge.target in in_degree:
                in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for edge in self.edges:
                if edge.source == current and edge.type == EdgeType.DEPENDS_ON:
                    in_degree[edge.target] -= 1
                    if in_degree[edge.target] == 0:
                        queue.append(edge.target)

        # Add any remaining (disconnected) nodes
        for nid in self.nodes:
            if nid not in result:
                result.append(nid)

        return result

    def build_context(self) -> str:
        """Build a text representation for LLM context."""
        if not self.nodes:
            return "(empty architecture)"

        lines = []

        systems = self.get_systems()
        if systems:
            lines.append("Systems:")
            for s in systems:
                lines.append(f"  - {s.name}")

        entities = self.get_entities()
        if entities:
            lines.append("Entities:")
            for e in entities:
                lines.append(f"  - {e.name} ({e.metadata.get('node_type', 'Node3D')})")

        if self.edges:
            lines.append("Connections:")
            for edge in self.edges:
                src = self.nodes.get(edge.source)
                tgt = self.nodes.get(edge.target)
                if src and tgt:
                    lines.append(f"  - {src.name} --[{edge.type.value}]--> {tgt.name}")

        return "\n".join(lines)

    DEFAULT_PATH: Path = Path(".devforge/project_graph.json")

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: {"name": n.name, "type": n.type.value, "metadata": n.metadata}
                      for nid, n in self.nodes.items()},
            "edges": [{"source": e.source, "target": e.target, "type": e.type.value}
                      for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SystemGraph":
        g = cls()
        for nid, ndata in data.get("nodes", {}).items():
            g.add_node(
                node_id=nid,
                name=ndata["name"],
                node_type=NodeType(ndata["type"]),
                **ndata.get("metadata", {}),
            )
        for edata in data.get("edges", []):
            g.add_edge(
                source=edata["source"],
                target=edata["target"],
                edge_type=EdgeType(edata["type"]),
            )
        return g

    def save(self, path: Optional[Path] = None) -> None:
        """Save graph to disk as JSON."""
        path = path or self.DEFAULT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SystemGraph":
        """Load graph from disk, returning empty graph if file missing."""
        path = path or cls.DEFAULT_PATH
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
