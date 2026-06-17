from __future__ import annotations

from typing import List, Set

from devforge.knowledge.system_graph.system_graph import (
    SystemGraph,
    EdgeType,
)


class DependencyResolver:
    """
    Resolves dependency relationships inside the SystemGraph.
    """

    def __init__(self, graph: SystemGraph):

        self.graph = graph

    # ---------------------------------------------------------
    # Direct dependencies
    # ---------------------------------------------------------

    def dependencies(self, node_id: str) -> Set[str]:

        deps: Set[str] = set()

        for edge in self.graph.edges:

            if edge.source == node_id and edge.type == EdgeType.DEPENDS_ON:
                deps.add(edge.target)

        return deps

    # ---------------------------------------------------------
    # Reverse dependencies
    # ---------------------------------------------------------

    def dependents(self, node_id: str) -> Set[str]:

        dependents: Set[str] = set()

        for edge in self.graph.edges:

            if edge.target == node_id and edge.type == EdgeType.DEPENDS_ON:
                dependents.add(edge.source)

        return dependents

    # ---------------------------------------------------------
    # Transitive dependency resolution
    # ---------------------------------------------------------

    def resolve_all(self, node_id: str) -> Set[str]:

        visited: Set[str] = set()
        stack = [node_id]

        while stack:

            current = stack.pop()

            for dep in self.dependencies(current):

                if dep not in visited:
                    visited.add(dep)
                    stack.append(dep)

        return visited

    # ---------------------------------------------------------
    # Missing dependency detection
    # ---------------------------------------------------------

    def find_missing(self) -> List[str]:

        missing = []

        for edge in self.graph.edges:

            if edge.type != EdgeType.DEPENDS_ON:
                continue

            if edge.target not in self.graph.nodes:

                missing.append(
                    f"Missing dependency: {edge.source} -> {edge.target}"
                )

        return missing

    # ---------------------------------------------------------
    # Build order (topological sort)
    # ---------------------------------------------------------

    def build_order(self) -> List[str]:

        # simple wrapper around graph ordering

        try:
            return self.graph.topological_order()
        except Exception:
            return []