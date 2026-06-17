from __future__ import annotations

from typing import List, Dict

from devforge.knowledge.system_graph.diff_engine import GraphDiff


class RepairSuggestionEngine:
    """
    Converts graph differences into suggested operations.
    """

    def suggest(self, diff: GraphDiff) -> List[Dict]:

        operations: List[Dict] = []

        # Missing nodes
        for node_id in diff.missing_nodes:

            operations.append(
                {
                    "type": "create_node",
                    "id": node_id,
                }
            )

        # Missing edges
        for edge in diff.missing_edges:

            operations.append(
                {
                    "type": "create_edge",
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.type.value,
                }
            )

        return operations