from __future__ import annotations

from abc import ABC, abstractmethod

from devforge.core.execution_plan import ExecutionPlan
from devforge.knowledge.specs.component_spec import ComponentSpec
from devforge.knowledge.specs.goal_spec import GoalSpec
from devforge.knowledge.specs.system_spec import SystemSpec
from devforge.state.world_state import WorldState


class GoalPlanner(ABC):
    @abstractmethod
    def generate_systems(self, goal: GoalSpec, world_state: WorldState) -> list[SystemSpec]:
        raise NotImplementedError


class SystemPlanner(ABC):
    @abstractmethod
    def generate_components(self, system: SystemSpec, world_state: WorldState) -> list[ComponentSpec]:
        raise NotImplementedError


class ExecutionPlanner(ABC):
    @abstractmethod
    def generate_execution_plan(
        self, component: ComponentSpec, world_state: WorldState
    ) -> ExecutionPlan:
        raise NotImplementedError
