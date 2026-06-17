from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from .system import SimulationSystem


# ---------------------------------------------------------------------
# Parameter Definition
# ---------------------------------------------------------------------


@dataclass
class ParameterSpec:
    """
    Describes a tunable simulation parameter.

    Used by the preview UI to build controls automatically.
    """

    name: str
    value: Any

    min_value: Optional[float] = None
    max_value: Optional[float] = None

    step: Optional[float] = None

    description: Optional[str] = None


# ---------------------------------------------------------------------
# Parameter Registry
# ---------------------------------------------------------------------


class ParameterRegistry:
    """
    Collects and manages tunable parameters from devforge.simulation systems.
    """

    def __init__(self):

        self.parameters: Dict[str, Dict[str, ParameterSpec]] = {}

    # ---------------------------------------------------------------

    def register_system(self, system: SimulationSystem) -> None:
        """
        Extract parameters from a system configuration.
        """

        system_name = system.name

        params = system.parameters()

        specs: Dict[str, ParameterSpec] = {}

        for name, value in params.items():
            specs[name] = ParameterSpec(
                name=name,
                value=value,
            )

        self.parameters[system_name] = specs

    # ---------------------------------------------------------------

    def update_parameter(
        self,
        system_name: str,
        param_name: str,
        value: Any,
    ) -> None:

        if system_name not in self.parameters:
            return

        if param_name not in self.parameters[system_name]:
            return

        self.parameters[system_name][param_name].value = value

    # ---------------------------------------------------------------

    def system_parameters(self, system_name: str) -> Dict[str, ParameterSpec]:

        return self.parameters.get(system_name, {})

    # ---------------------------------------------------------------

    def all_parameters(self) -> Dict[str, Dict[str, ParameterSpec]]:

        return self.parameters
