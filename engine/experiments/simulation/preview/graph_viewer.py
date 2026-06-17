"""System graph viewer adapter."""

from __future__ import annotations


class GraphViewer:

    """
    Converts system graph into visualization format.
    """

    def build(self, graph):

        nodes = []
        edges = []

        for n in graph.get("nodes", []):

            nodes.append(
                {
                    "id": n["id"],
                    "label": n["id"],
                }
            )

        for e in graph.get("edges", []):

            edges.append(
                {
                    "source": e["from"],
                    "target": e["to"],
                    "label": ", ".join(e.get("data", [])),
                }
            )

        return {
            "nodes": nodes,
            "edges": edges,
        }