"""Mechanic evolution engine for DevForge."""

from __future__ import annotations

from typing import List, Dict, Any

from .mechanic_mutator import MechanicMutator


class MechanicEvolution:
    def __init__(self, controller):

        self.controller = controller

        self.mutator = MechanicMutator()

    # -------------------------------------------------------------

    def evolve(
        self,
        base_systems: List[Dict[str, Any]],
        generations: int = 5,
        population: int = 4,
    ):

        best_systems = base_systems

        best_score = float("inf")

        for _ in range(generations):
            candidates = self.mutator.mutate(best_systems, population)

            for systems in candidates:
                score = self._evaluate(systems)

                if score < best_score:
                    best_score = score

                    best_systems = systems

        return {
            "score": best_score,
            "systems": best_systems,
        }

    # -------------------------------------------------------------

    def _evaluate(self, systems):

        self.controller.reset()

        self.controller.engine.clear_systems()

        for system in systems:
            self.controller.add_generated_system(system)

        self.controller.run(steps=200)

        metrics = self.controller.metrics()

        score = 0

        for m in metrics.values():
            score += abs(m.value)

        return score
