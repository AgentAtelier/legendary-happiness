from __future__ import annotations

from dataclasses import dataclass
from typing import List

from devforge.knowledge.system_graph.system_graph import (
    SystemGraph,
    GraphEdge,
)


@dataclass
class GraphDiff:

    missing_nodes: List[str]
    extra_nodes: List[str]

    missing_edges: List[GraphEdge]
    extra_edges: List[GraphEdge]


class ArchitectureDiffEngine:
    """
    Computes structural differences between two SystemGraphs.

    Used for repair planning and architecture validation.
    """

    def diff(
        self,
        expected: SystemGraph,
        actual: SystemGraph,
    ) -> GraphDiff:

        expected_nodes = set(expected.nodes.keys())
        actual_nodes = set(actual.nodes.keys())

        missing_nodes = list(expected_nodes - actual_nodes)
        extra_nodes = list(actual_nodes - expected_nodes)

        expected_edges = set(expected.edges)
        actual_edges = set(actual.edges)

        missing_edges = list(expected_edges - actual_edges)
        extra_edges = list(actual_edges - expected_edges)

        return GraphDiff(
            missing_nodes=missing_nodes,
            extra_nodes=extra_nodes,
            missing_edges=missing_edges,
            extra_edges=extra_edges,
        )