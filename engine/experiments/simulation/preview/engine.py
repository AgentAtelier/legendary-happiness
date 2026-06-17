from __future__ import annotations

import random
from typing import List, Dict, Type

from .world import WorldState
from .system import SimulationSystem
from .metrics import MetricsEngine
from .timeline import TimelineRecorder
from .agents import AgentEngine
from .parameters import ParameterRegistry


class PreviewEngine:
    """
    Core simulation engine for the DevForge preview system.
    """

    def __init__(self, seed: int | None = None):

        self.seed = seed if seed is not None else 0
        self.random = random.Random(self.seed)

        self.systems: List[SimulationSystem] = []

        self.world = WorldState()

        self.metrics = MetricsEngine()

        self.timeline = TimelineRecorder()

        self.agents = AgentEngine()

        self.parameters = ParameterRegistry()

        self.running = False

        self.step_count = 0

    # ----------------------------------------------------------------

    def add_system(self, system: SimulationSystem) -> None:

        self.systems.append(system)

        # register system parameters
        self.parameters.register_system(system)

    # ----------------------------------------------------------------

    def add_agent(self, agent) -> None:

        self.agents.add_agent(agent)

    # ----------------------------------------------------------------

    def add_metric(self, metric) -> None:

        self.metrics.add_metric(metric)

    # ----------------------------------------------------------------

    def remove_system(self, system_type: Type[SimulationSystem]) -> None:

        self.systems = [s for s in self.systems if not isinstance(s, system_type)]

    # ----------------------------------------------------------------

    def reset(self) -> None:

        self.random = random.Random(self.seed)

        self.world = WorldState()

        self.metrics.reset()

        self.timeline.reset()

        self.agents.reset()

        self.step_count = 0

    # ----------------------------------------------------------------

    def step(self, dt: float = 1.0) -> None:

        for system in self.systems:
            system.update(self.world, dt)

        self.agents.step(self.world)

        self.world.advance_time(dt)

        self.metrics.observe(self.world)

        self.timeline.record(self.step_count, self.world)

        self.step_count += 1

    # ----------------------------------------------------------------

    def run(self, steps: int = 100, dt: float = 1.0) -> WorldState:

        for _ in range(steps):
            self.step(dt)

        return self.world

    # ----------------------------------------------------------------

    def set_parameter(self, system_name: str, param: str, value) -> None:

        for system in self.systems:
            if system.name == system_name:
                system.set_parameters({param: value})

                self.parameters.update_parameter(system_name, param, value)

    # ----------------------------------------------------------------

    def system_parameters(self):

        return self.parameters.all_parameters()

    # ----------------------------------------------------------------

    def metric_results(self):

        return self.metrics.results()

    # ----------------------------------------------------------------

    def timeline_frames(self):

        return self.timeline.timeline()
