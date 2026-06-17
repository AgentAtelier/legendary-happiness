"""R6: Node Safety — no string literals in get_node() calls.

Phase 8 (AST): Swapped to tree-sitter-gdscript for reliable get_node()
detection.  The AST finds call nodes with identifier=get_node and
checks for string literal arguments — handles multiline calls correctly.

When tree-sitter is unavailable, falls back to regex (Tier 1, same-line only).
"""

from __future__ import annotations

import re
from typing import List

from devforge.patch.gdscript_ast import GdscriptParser
from devforge.validation.rules.base import Rule, Violation

_parser = GdscriptParser()

# Tier 1 fallback: match get_node("string literal") on same line
_GET_NODE_STRING_RE = re.compile(r"get_node\s*\(\s*(['\"])")


class R6NodeSafety(Rule):
    """Block string literals inside get_node() calls (AST-powered)."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        violations: List[Violation] = []

        if _parser.has_ast:
            root = _parser.parse(content)
            for line, msg in _parser.find_get_node_violations(root):
                violations.append(
                    Violation(
                        rule_id="R6_NODE_SAFETY",
                        message=msg,
                        line_number=line,
                        severity="critical",
                        action="block_merge",
                    )
                )
        else:
            # Tier 1 fallback
            for line_num, line in enumerate(content.splitlines(), start=1):
                code = self.strip_comment(line)
                if _GET_NODE_STRING_RE.search(code):
                    violations.append(
                        Violation(
                            rule_id="R6_NODE_SAFETY",
                            message="get_node() with string literal detected — "
                            "use $NodePath notation or @onready var instead",
                            line_number=line_num,
                            severity="critical",
                            action="block_merge",
                        )
                    )

        return violations
