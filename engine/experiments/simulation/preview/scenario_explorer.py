"""Scenario exploration engine."""

from __future__ import annotations

import random
from typing import Dict, Any, List


class ScenarioExplorer:

    """
    Explores parameter spaces through repeated simulations.
    """

    def __init__(self, controller):

        self.controller = controller

    # ---------------------------------------------------------

    def explore(
        self,
        parameter_ranges: Dict[str, Dict[str, tuple]],
        runs: int = 50,
    ) -> List[Dict[str, Any]]:

        results = []

        for _ in range(runs):

            params = self._sample_parameters(parameter_ranges)

            self._apply_parameters(params)

            self.controller.reset()

            self.controller.run(steps=200)

            metrics = self.controller.metrics()

            results.append(
                {
                    "parameters": params,
                    "metrics": {
                        name: metric.value
                        for name, metric in metrics.items()
                    },
                }
            )

        return results

    # ---------------------------------------------------------

    def _sample_parameters(self, ranges):

        params = {}

        for system, plist in ranges.items():

            params[system] = {}

            for name, (low, high) in plist.items():

                params[system][name] = random.uniform(low, high)

        return params

    # ---------------------------------------------------------

    def _apply_parameters(self, params):

        for system, values in params.items():

            for name, value in values.items():

                self.controller.set_parameter(
                    system,
                    name,
                    value,
                )