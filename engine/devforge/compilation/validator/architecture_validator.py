from __future__ import annotations

from typing import List

from devforge.knowledge.system_graph.system_graph import (
    SystemGraph,
    NodeType,
    EdgeType,
)


class ArchitectureValidator:
    """
    Performs structural validation of the project architecture.
    """

    def validate(self, graph: SystemGraph) -> List[str]:

        issues: List[str] = []

        issues += self._check_entities_have_scripts(graph)
        issues += self._check_orphan_scripts(graph)
        issues += self._check_dependencies(graph)

        return issues

    # ---------------------------------------------------------
    # Entity controller check
    # ---------------------------------------------------------

    def _check_entities_have_scripts(
        self,
        graph: SystemGraph,
    ) -> List[str]:

        problems: List[str] = []

        for node in graph.nodes.values():

            if node.type != NodeType.ENTITY:
                continue

            has_script = False

            for edge in graph.edges:

                if (
                    edge.source == node.id
                    and edge.type == EdgeType.USES
                ):
                    has_script = True
                    break

            if not has_script:

                problems.append(
                    f"Entity '{node.name}' has no script"
                )

        return problems

    # ---------------------------------------------------------
    # Orphan script detection
    # ---------------------------------------------------------

    def _check_orphan_scripts(
        self,
        graph: SystemGraph,
    ) -> List[str]:

        problems: List[str] = []

        for node in graph.nodes.values():

            if node.type != NodeType.SCRIPT:
                continue

            used = False

            for edge in graph.edges:

                if edge.target == node.id:
                    used = True
                    break

            if not used:

                problems.append(
                    f"Script '{node.name}' is not attached to any entity"
                )

        return problems

    # ---------------------------------------------------------
    # Dependency checks
    # ---------------------------------------------------------

    def _check_dependencies(
        self,
        graph: SystemGraph,
    ) -> List[str]:

        problems: List[str] = []

        for edge in graph.edges:

            if edge.type != EdgeType.DEPENDS_ON:
                continue

            if edge.target not in graph.nodes:

                problems.append(
                    f"Dependency missing: {edge.source} -> {edge.target}"
                )

        return problems