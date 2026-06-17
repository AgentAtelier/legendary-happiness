"""Design suggestion engine."""

from __future__ import annotations

from typing import List, Dict, Any


class DesignSuggestionEngine:
    """
    Generates improvement suggestions for mechanics.
    """

    def suggest(
        self,
        metrics,
        critique,
        graph,
        memory,
    ) -> List[Dict[str, Any]]:

        suggestions = []

        suggestions.extend(self._metric_suggestions(metrics))

        suggestions.extend(self._critique_suggestions(critique))

        suggestions.extend(self._graph_suggestions(graph))

        return suggestions

    # ---------------------------------------------------------

    def _metric_suggestions(self, metrics):

        output = []

        for name, metric in metrics.items():
            value = metric.value

            if name == "rain_volatility" and value > 0.5:
                output.append(
                    {
                        "type": "parameter_adjustment",
                        "message": "Reduce rain_variation parameter",
                        "suggested_value": value * 0.6,
                    }
                )

        return output

    # ---------------------------------------------------------

    def _critique_suggestions(self, critique):

        output = []

        for issue in critique:
            if issue["type"] == "cascade":
                output.append(
                    {
                        "type": "mechanic_addition",
                        "message": "Introduce damping mechanic to prevent cascades",
                    }
                )

        return output

    # ---------------------------------------------------------

    def _graph_suggestions(self, graph):

        edges = graph.get("edges", [])

        output = []

        if len(edges) > 8:
            output.append(
                {
                    "type": "complexity_reduction",
                    "message": "Consider simplifying system interactions",
                }
            )

        return output
