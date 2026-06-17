"""Project Navigator — search the project for files, symbols, and signals.

Deterministic core (tier 0): no LLM calls.
"""

from devforge.navigator.navigator import ProjectNavigator, search_project

__all__ = ["ProjectNavigator", "search_project"]
