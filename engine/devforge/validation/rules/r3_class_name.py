"""R3: Class Name Convention — PascalCase required.

Phase 8 (AST): Swapped from regex to tree-sitter-gdscript AST parsing
for reliable class_name_statement extraction.
Falls back to regex (Tier 1) when tree-sitter is unavailable.
"""

from __future__ import annotations

from typing import List

from devforge.patch.gdscript_ast import GdscriptParser
from devforge.validation.rules.base import Rule, Violation

# Shared parser instance (thread-safe: tree-sitter Parser is not thread-safe,
# but our usage is single-threaded in the validator pipeline)
_parser = GdscriptParser()


class R3ClassName(Rule):
    """Enforce PascalCase for class_name declarations (AST-powered)."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        violations: List[Violation] = []

        result = _parser.get_class_name(content)
        if result is None:
            return violations

        name, line_num = result

        # Must start with uppercase letter, rest alphanumeric
        if not (name[0].isupper() and name.isalnum()):
            violations.append(
                Violation(
                    rule_id="R3_CLASS_NAME",
                    message=f"class_name '{name}' is not PascalCase (should match [A-Z][a-zA-Z0-9]*)",
                    line_number=line_num,
                    severity="critical",
                    action="block_merge",
                )
            )

        return violations
