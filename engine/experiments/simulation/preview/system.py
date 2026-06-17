from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from typing import Any, Dict


@dataclass
class SystemConfig:
    """
    Base configuration object for simulation systems.

    Subclasses define tunable parameters that will be exposed
    to the preview UI automatically.
    """

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def update(self, values: Dict[str, Any]) -> None:
        for key, value in values.items():
            if hasattr(self, key):
                setattr(self, key, value)


class SimulationSystem(ABC):
    """
    Base class for all preview simulation systems.

    Systems implement mechanics like weather, disasters,
    resource generation, NPC behavior, etc.
    """

    name: str = "system"

    def __init__(self, config: SystemConfig | None = None):
        self.config = config or SystemConfig()

    def parameters(self) -> Dict[str, Any]:
        return self.config.to_dict()

    def set_parameters(self, values: Dict[str, Any]) -> None:
        self.config.update(values)

    @abstractmethod
    def update(self, world: "WorldState", dt: float) -> None:
        """
        Called every simulation step.
        """
        pass