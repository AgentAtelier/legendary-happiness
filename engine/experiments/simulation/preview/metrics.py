from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any

from .world import WorldState


# ---------------------------------------------------------------------
# Metric Result
# ---------------------------------------------------------------------


@dataclass
class MetricResult:
    """
    Represents the output of a metric calculation.
    """

    name: str
    value: Any
    description: str | None = None


# ---------------------------------------------------------------------
# Metric Base Class
# ---------------------------------------------------------------------


class SimulationMetric:
    """
    Base class for all simulation metrics.

    Metrics analyze the world state during or after simulation
    and produce useful design insights.
    """

    name: str = "metric"

    def reset(self) -> None:
        """
        Reset internal state before simulation begins.
        """
        pass

    def observe(self, world: WorldState) -> None:
        """
        Called every simulation step.
        """
        pass

    def result(self) -> MetricResult:
        """
        Return final metric result.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------
# Metric Engine
# ---------------------------------------------------------------------


class MetricsEngine:
    """
    Collects and computes simulation metrics.
    """

    def __init__(self):

        self.metrics: List[SimulationMetric] = []

    # ---------------------------------------------------------------

    def add_metric(self, metric: SimulationMetric) -> None:
        self.metrics.append(metric)

    # ---------------------------------------------------------------

    def reset(self) -> None:

        for metric in self.metrics:
            metric.reset()

    # ---------------------------------------------------------------

    def observe(self, world: WorldState) -> None:

        for metric in self.metrics:
            metric.observe(world)

    # ---------------------------------------------------------------

    def results(self) -> Dict[str, MetricResult]:

        output: Dict[str, MetricResult] = {}

        for metric in self.metrics:
            result = metric.result()
            output[result.name] = result

        return output