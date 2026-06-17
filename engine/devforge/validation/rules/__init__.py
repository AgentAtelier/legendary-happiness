"""Tier 1 Rule Registry — all deterministic validation rules.

Import everything here so the orchestrator can iterate over all rules.
"""

from devforge.validation.rules.base import Rule, Violation
from devforge.validation.rules.guards import (
    GuardEmptyFile,
    GuardExtensionCheck,
    GuardMassiveFile,
)
from devforge.validation.rules.r1_line_count import R1LineCount
from devforge.validation.rules.r2_filename import R2Filename
from devforge.validation.rules.r3_class_name import R3ClassName
from devforge.validation.rules.r4_syntax_sanity import R4SyntaxSanity
from devforge.validation.rules.r5_static_typing import R5StaticTyping
from devforge.validation.rules.r6_node_safety import R6NodeSafety

# All rules in execution order (guards first, then R1→R6)
ALL_RULES: list[type[Rule]] = [
    GuardEmptyFile,
    GuardExtensionCheck,
    GuardMassiveFile,
    R1LineCount,
    R2Filename,
    R3ClassName,
    R4SyntaxSanity,
    R5StaticTyping,
    R6NodeSafety,
]

__all__ = [
    "Rule",
    "Violation",
    "ALL_RULES",
    "GuardEmptyFile",
    "GuardExtensionCheck",
    "GuardMassiveFile",
    "R1LineCount",
    "R2Filename",
    "R3ClassName",
    "R4SyntaxSanity",
    "R5StaticTyping",
    "R6NodeSafety",
]
