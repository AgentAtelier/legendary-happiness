"""Scenario experiment runner for the DevForge Preview Lab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any

from devforge.simulation.preview.engine import PreviewEngine
from devforge.simulation.preview.scenarios import Scenario, ScenarioRunner


@dataclass
class ExperimentResult:
    """Stores the result of a scenario experiment."""

    scenario_name: str
    metrics: Dict[str, Any]


class ExperimentRunner:
    """
    Runs multiple scenarios and compares their outcomes.

    Used for:
    - gameplay balancing
    - mechanic evaluation
    - AI design feedback
    """

    def __init__(self, engine: PreviewEngine):

        self.engine = engine
        self.runner = ScenarioRunner(engine)

    # ----------------------------------------------------------------

    def run(self, scenarios: List[Scenario]) -> List[ExperimentResult]:

        results: List[ExperimentResult] = []

        for scenario in scenarios:

            result = self.runner.run_scenario(scenario)

            results.append(
                ExperimentResult(
                    scenario_name=scenario.name,
                    metrics=result.metrics,
                )
            )

        return results

    # ----------------------------------------------------------------

    def compare(self, scenarios: List[Scenario]) -> Dict[str, Dict[str, Any]]:
        """
        Run scenarios and return comparison table.

        Output format:

        {
            "baseline": {metric: value},
            "stormy": {metric: value}
        }
        """

        results = self.run(scenarios)

        comparison: Dict[str, Dict[str, Any]] = {}

        for r in results:

            comparison[r.scenario_name] = {
                name: metric.value
                for name, metric in r.metrics.items()
            }

        return comparison