"""Performance Sentinel — sample, store, and report Godot performance metrics.

Deterministic core (tier 0): no LLM calls.
"""

from devforge.sentinel.sentinel import PerformanceSentinel

__all__ = ["PerformanceSentinel"]
