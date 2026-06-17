from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from devforge.knowledge.system_graph.system_graph import (
    EdgeType,
    NodeType,
    SystemGraph,
)


@dataclass
class LearnedPattern:
    name: str
    nodes: List[str]
    relations: List[str]


class StructuralPatternLearner:
    """
    Learns reusable architecture patterns from the SystemGraph.
    """

    def __init__(self):

        self.patterns: Dict[str, LearnedPattern] = {}

    # ---------------------------------------------------------
    # Pattern discovery
    # ---------------------------------------------------------

    def learn(self, graph: SystemGraph):

        discovered = self._detect_entity_script_patterns(graph)

        for pattern in discovered:
            if pattern.name not in self.patterns:
                self.patterns[pattern.name] = pattern

    # ---------------------------------------------------------
    # Pattern detection
    # ---------------------------------------------------------

    def _detect_entity_script_patterns(
        self,
        graph: SystemGraph,
    ) -> List[LearnedPattern]:

        patterns: List[LearnedPattern] = []

        for edge in graph.edges:
            if edge.type != EdgeType.USES:
                continue

            source = graph.nodes.get(edge.source)
            target = graph.nodes.get(edge.target)

            if not source or not target:
                continue

            if source.type == NodeType.ENTITY and target.type == NodeType.SCRIPT:
                pattern_name = "EntityControllerPattern"

                pattern = LearnedPattern(
                    name=pattern_name,
                    nodes=[source.name, target.name],
                    relations=["entity_uses_script"],
                )

                patterns.append(pattern)

        return patterns

    # ---------------------------------------------------------
    # Pattern export
    # ---------------------------------------------------------

    def build_context(self) -> str:

        if not self.patterns:
            return "## Learned Patterns\n(none yet)"

        lines = ["## Learned Patterns"]

        for p in self.patterns.values():
            lines.append(f"- {p.name}")
            lines.append(f"  nodes: {p.nodes}")
            lines.append(f"  relations: {p.relations}")

        return "\n".join(lines)
