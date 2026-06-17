"""R5: Static Typing — function args and return types must be declared.

Phase 8 (AST): Swapped to tree-sitter-gdscript for proper multiline
signature parsing.  The AST correctly handles:

    func do_something(
        a: int,
        b: String
    ) -> void:

...and extracts typed_parameter nodes regardless of line breaks.

When tree-sitter is unavailable, falls back to regex (Tier 1, same-line only).
"""

from __future__ import annotations

from typing import List

from devforge.patch.gdscript_ast import GdscriptParser
from devforge.validation.rules.base import Rule, Violation

_parser = GdscriptParser()


class R5StaticTyping(Rule):
    """Enforce type annotations on all function arguments and return types (AST-powered)."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        violations: List[Violation] = []

        for func in _parser.iter_functions(content):
            # Check return type
            if func.return_type is None:
                violations.append(
                    Violation(
                        rule_id="R5_STATIC_TYPING",
                        message=f"Function '{func.name}' is missing return type hint "
                        f"(should be 'func {func.name}(...) -> ReturnType:')",
                        line_number=func.line_number,
                        severity="critical",
                        action="block_merge",
                    )
                )

            # Check parameter types
            for param in func.params:
                if param.get("type") is None:
                    violations.append(
                        Violation(
                            rule_id="R5_STATIC_TYPING",
                            message=f"Function '{func.name}': argument "
                            f"'{param['name']}' is missing type hint",
                            line_number=func.line_number,
                            severity="critical",
                            action="block_merge",
                        )
                    )

        return violations
