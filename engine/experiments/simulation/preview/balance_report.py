"""Balance report generator."""

from __future__ import annotations

from typing import Dict, Any


class BalanceReport:

    """
    Generates a structured design report.
    """

    def generate(
        self,
        metrics,
        critique,
        suggestions,
        graph,
    ) -> Dict[str, Any]:

        report = {
            "summary": self._summary(metrics),
            "issues": critique,
            "suggestions": suggestions,
            "system_complexity": self._complexity(graph),
        }

        return report

    # ---------------------------------------------------------

    def _summary(self, metrics):

        summary = {}

        for name, metric in metrics.items():

            summary[name] = metric.value

        return summary

    # ---------------------------------------------------------

    def _complexity(self, graph):

        nodes = graph.get("nodes", [])

        edges = graph.get("edges", [])

        return {
            "systems": len(nodes),
            "interactions": len(edges),
        }