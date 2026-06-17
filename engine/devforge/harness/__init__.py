"""Test Harness — generate test scaffolds from GDScript function signatures.

Deterministic core (tier 0): no LLM calls.
"""

from devforge.harness.scaffolder import TestScaffolder, scaffold_file

__all__ = ["TestScaffolder", "scaffold_file"]
