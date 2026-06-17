from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List, Callable

from .engine import PreviewEngine
from .world import WorldState


# ---------------------------------------------------------------------
# Scenario Definition
# ---------------------------------------------------------------------


@dataclass
class Scenario:
    """
    Defines a simulation scenario.

    A scenario specifies:
    - parameter overrides
    - simulation length
    - optional world setup
    """

    name: str

    steps: int = 100
    dt: float = 1.0

    parameter_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    world_setup: Callable[[WorldState], None] | None = None


# ---------------------------------------------------------------------
# Scenario Result
# ---------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """
    Stores the outcome of a scenario run.
    """

    scenario_name: str

    final_world: WorldState

    metrics: Dict[str, Any]


# ---------------------------------------------------------------------
# Scenario Runner
# ---------------------------------------------------------------------


class ScenarioRunner:
    """
    Runs multiple scenarios using a preview engine.
    """

    def __init__(self, engine: PreviewEngine):

        self.engine = engine

    # ---------------------------------------------------------------

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:

        # reset engine
        self.engine.reset()

        # apply parameter overrides
        for system_name, params in scenario.parameter_overrides.items():

            for param, value in params.items():
                self.engine.set_parameter(system_name, param, value)

        # optional world initialization
        if scenario.world_setup:
            scenario.world_setup(self.engine.world)

        # run simulation
        self.engine.run(steps=scenario.steps, dt=scenario.dt)

        # collect metrics
        metrics = self.engine.metric_results()

        return ScenarioResult(
            scenario_name=scenario.name,
            final_world=self.engine.world.snapshot(),
            metrics=metrics,
        )

    # ---------------------------------------------------------------

    def run_batch(self, scenarios: List[Scenario]) -> List[ScenarioResult]:

        results = []

        for scenario in scenarios:

            result = self.run_scenario(scenario)

            results.append(result)

        return results