from __future__ import annotations

from typing import Dict, Any, List, Type

from .system import SimulationSystem, SystemConfig
from .world import WorldState


# ---------------------------------------------------------------------
# Dynamic Config Builder
# ---------------------------------------------------------------------


def build_config(config_data: Dict[str, Any]) -> SystemConfig:
    """
    Dynamically build a SystemConfig object from dictionary data.
    """

    class DynamicConfig(SystemConfig):
        pass

    config = DynamicConfig()

    for key, value in config_data.items():
        setattr(config, key, value)

    return config


# ---------------------------------------------------------------------
# Dynamic Simulation System
# ---------------------------------------------------------------------


class GeneratedSystem(SimulationSystem):
    """
    Simulation system generated from DevForge pipeline output.
    """

    def __init__(
        self,
        name: str,
        config: SystemConfig,
        logic: Dict[str, Any],
    ):
        super().__init__(config)

        self.name = name

        self.logic = logic

    # ---------------------------------------------------------------

    def update(self, world: WorldState, dt: float):

        # Example rule-based simulation

        for rule in self.logic.get("rules", []):
            if rule["type"] == "environment_delta":
                key = rule["target"]

                delta = rule.get("delta", 0)

                world.environment[key] = world.environment.get(key, 0) + delta

            elif rule["type"] == "event_probability":
                import random

                if random.random() < rule.get("chance", 0):
                    world.record_event(
                        rule.get("event", "event"),
                        {},
                    )


# ---------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------


class PreviewAdapter:
    """
    Converts DevForge generated systems into preview simulation systems.
    """

    # ---------------------------------------------------------------

    def create_system(self, data: Dict[str, Any]) -> SimulationSystem:

        name = data.get("name", "generated_system")

        config_data = data.get("config", {})

        logic = data.get("logic", {})

        config = build_config(config_data)

        return GeneratedSystem(name, config, logic)

    # ---------------------------------------------------------------

    def create_systems(
        self,
        systems: List[Dict[str, Any]],
    ) -> List[SimulationSystem]:

        result = []

        for system in systems:
            result.append(self.create_system(system))

        return result
