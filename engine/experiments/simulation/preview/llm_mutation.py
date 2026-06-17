"""Future LLM mutation interface."""

from typing import List, Dict, Any


class LLMMechanicMutation:
    """
    Interface for LLM-driven mechanic proposals.

    Later this can call Claude/GPT to propose system changes.
    """

    def propose(self, systems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:

        # placeholder
        return systems
