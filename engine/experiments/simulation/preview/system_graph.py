"""System dependency graph builder for the Preview Lab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Any


@dataclass
class SystemNode:
    name: str
    inputs: Set[str]
    outputs: Set[str]


class SystemGraph:
    """
    Represents relationships between simulation systems.

    Nodes = systems
    Edges = data flow between systems
    """

    def __init__(self):

        self.nodes: Dict[str, SystemNode] = {}

    # -------------------------------------------------------------

    def add_system(self, name: str, inputs: List[str], outputs: List[str]):

        self.nodes[name] = SystemNode(
            name=name,
            inputs=set(inputs),
            outputs=set(outputs),
        )

    # -------------------------------------------------------------

    def build_edges(self):

        edges = []

        for a in self.nodes.values():
            for b in self.nodes.values():
                if a.name == b.name:
                    continue

                if a.outputs.intersection(b.inputs):
                    edges.append(
                        {
                            "from": a.name,
                            "to": b.name,
                            "data": list(a.outputs.intersection(b.inputs)),
                        }
                    )

        return edges

    # -------------------------------------------------------------

    def export(self):

        nodes = [
            {
                "id": n.name,
                "inputs": list(n.inputs),
                "outputs": list(n.outputs),
            }
            for n in self.nodes.values()
        ]

        edges = self.build_edges()

        return {
            "nodes": nodes,
            "edges": edges,
        }
