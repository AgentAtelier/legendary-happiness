"""LLM-guided mechanic mutation engine."""

from __future__ import annotations

import random
from copy import deepcopy
from typing import List, Dict, Any


class MechanicMutator:
    """
    Generates new mechanic variants.

    Initially uses heuristic mutations.
    Later can be replaced with LLM proposals.
    """

    # -------------------------------------------------------------

    def mutate(self, systems: List[Dict[str, Any]], count: int = 4):

        candidates = []

        for _ in range(count):

            mutated = deepcopy(systems)

            mutation = random.choice(
                [
                    self._adjust_parameter,
                    self._add_rule,
                    self._remove_rule,
                ]
            )

            mutation(mutated)

            candidates.append(mutated)

        return candidates

    # -------------------------------------------------------------

    def _adjust_parameter(self, systems):

        system = random.choice(systems)

        config = system.get("config")

        if not config:
            return

        key = random.choice(list(config.keys()))

        value = config[key]

        noise = random.uniform(-0.15, 0.15)

        config[key] = max(0, value + noise)

    # -------------------------------------------------------------

    def _add_rule(self, systems):

        system = random.choice(systems)

        rules = system.setdefault("rules", [])

        new_rule = {
            "type": "environment_delta",
            "target": random.choice(["rain", "wind", "temperature"]),
            "delta": random.uniform(-0.02, 0.05),
        }

        rules.append(new_rule)

    # -------------------------------------------------------------

    def _remove_rule(self, systems):

        system = random.choice(systems)

        rules = system.get("rules")

        if not rules:
            return

        if len(rules) > 1:
            rules.pop(random.randrange(len(rules)))