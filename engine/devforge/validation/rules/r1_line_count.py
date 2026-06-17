"""R1: File Length — reject files over 500 lines.

From invariants.md: "No single script shall exceed 500 lines."
"""

from __future__ import annotations

from typing import List

from devforge.validation.rules.base import Rule, Violation

MAX_LINES = 500


class R1LineCount(Rule):
    """Block files exceeding MAX_LINES (default 500)."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        line_count = content.count("\n") + 1

        if line_count > MAX_LINES:
            return [
                Violation(
                    rule_id="R1_LINE_COUNT",
                    message=f"File exceeds {MAX_LINES} lines (has {line_count}) — split into smaller files",
                    severity="critical",
                    action="block_merge",
                )
            ]
        return []
