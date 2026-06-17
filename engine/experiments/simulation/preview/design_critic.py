"""AI Design Critic for DevForge Preview Lab."""

from __future__ import annotations

from typing import Dict, Any, List


class DesignCritic:
    """
    Analyzes simulation results and produces design feedback.
    """

    def analyze(
        self,
        metrics: Dict[str, Any],
        events: List[dict],
        timeline: Dict[str, list],
        graph: Dict[str, Any],
    ) -> List[dict]:

        feedback = []

        feedback.extend(self._analyze_metrics(metrics))

        feedback.extend(self._analyze_events(events))

        feedback.extend(self._analyze_graph(graph))

        return feedback

    # -------------------------------------------------------------

    def _analyze_metrics(self, metrics):

        issues = []

        for name, metric in metrics.items():
            value = metric.value

            if name == "rain_volatility" and value > 0.5:
                issues.append(
                    {
                        "type": "balance",
                        "message": f"Rain volatility too high ({value:.2f})",
                    }
                )

            if name == "resource_loss_rate" and value > 0.4:
                issues.append(
                    {
                        "type": "balance",
                        "message": "Resources deplete too quickly",
                    }
                )

        return issues

    # -------------------------------------------------------------

    def _analyze_events(self, events):

        issues = []

        flood_count = sum(1 for e in events if e["type"] == "flood")

        if flood_count > 5:
            issues.append(
                {
                    "type": "cascade",
                    "message": "Flood cascade detected",
                }
            )

        return issues

    # -------------------------------------------------------------

    def _analyze_graph(self, graph):

        issues = []

        edges = graph.get("edges", [])

        if len(edges) > 10:
            issues.append(
                {
                    "type": "complexity",
                    "message": "System interaction network very dense",
                }
            )

        return issues
