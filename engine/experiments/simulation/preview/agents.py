from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Dict, Any

from .world import WorldState


# ---------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------


class SimulationAgent(ABC):
    """
    Base class for all simulation agents.

    Agents represent actors inside the world:
    - players
    - NPCs
    - enemies
    """

    name: str = "agent"

    def __init__(self):

        self.state: Dict[str, Any] = {}

    # ---------------------------------------------------------------

    def observe(self, world: WorldState) -> None:
        """
        Observe the world state.
        """
        pass

    # ---------------------------------------------------------------

    @abstractmethod
    def decide(self, world: WorldState) -> Dict[str, Any]:
        """
        Decide next action.
        """
        pass

    # ---------------------------------------------------------------

    def act(self, world: WorldState, action: Dict[str, Any]) -> None:
        """
        Execute action.
        """
        pass


# ---------------------------------------------------------------------
# Agent Engine
# ---------------------------------------------------------------------


class AgentEngine:
    """
    Manages all simulation agents.
    """

    def __init__(self):

        self.agents: List[SimulationAgent] = []

    # ---------------------------------------------------------------

    def add_agent(self, agent: SimulationAgent) -> None:

        self.agents.append(agent)

    # ---------------------------------------------------------------

    def remove_agent(self, agent: SimulationAgent) -> None:

        self.agents.remove(agent)

    # ---------------------------------------------------------------

    def step(self, world: WorldState) -> None:

        for agent in self.agents:
            agent.observe(world)

            action = agent.decide(world)

            agent.act(world, action)

    # ---------------------------------------------------------------

    def reset(self) -> None:

        self.agents.clear()
