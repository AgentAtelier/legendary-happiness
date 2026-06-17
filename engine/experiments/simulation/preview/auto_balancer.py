"""Automatic gameplay balancing system."""

from __future__ import annotations

import random
from typing import Dict, Any

from .scenarios import Scenario


class AutoBalancer:
    """
    Automatically tunes system parameters to reach target metrics.
    """

    def __init__(self, controller):

        self.controller = controller

    # -------------------------------------------------------------

    def balance(
        self,
        targets: Dict[str, float],
        iterations: int = 10,
    ):

        best_score = float("inf")

        best_params = None

        for _ in range(iterations):

            self._randomize_parameters()

            self.controller.reset()

            self.controller.run(steps=200)

            metrics = self.controller.metrics()

            score = self._score(metrics, targets)

            if score < best_score:

                best_score = score

                best_params = self._current_parameters()

        if best_params:

            self._apply_parameters(best_params)

        return {
            "score": best_score,
            "parameters": best_params,
        }

    # -------------------------------------------------------------

    def _score(self, metrics, targets):

        score = 0

        for name, target in targets.items():

            if name not in metrics:
                continue

            value = metrics[name].value

            score += abs(value - target)

        return score

    # -------------------------------------------------------------

    def _randomize_parameters(self):

        params = self.controller.parameters()

        for system, plist in params.items():

            for p in plist:

                new_value = random.uniform(
                    p.get("min", 0),
                    p.get("max", 1),
                )

                self.controller.set_parameter(
                    system,
                    p["name"],
                    new_value,
                )

    # -------------------------------------------------------------

    def _current_parameters(self):

        params = self.controller.parameters()

        output = {}

        for system, plist in params.items():

            output[system] = {
                p["name"]: p["value"]
                for p in plist
            }

        return output

    # -------------------------------------------------------------

    def _apply_parameters(self, parameters):

        for system, values in parameters.items():

            for name, value in values.items():

                self.controller.set_parameter(
                    system,
                    name,
                    value,
                )