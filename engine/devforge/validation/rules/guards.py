"""Pre-Execution Guards — cheap checks to reject invalid inputs early.

Guard 1: Empty File — reject empty or whitespace-only content.
Guard 2: Extension Check — only .gd files accepted.
Guard 3: Massive File — reject files over 2000 lines (too large for safe processing).
"""

from __future__ import annotations

from typing import List

from devforge.validation.rules.base import Rule, Violation

MAX_LINES_MASSIVE = 2000


class GuardEmptyFile(Rule):
    """Reject empty or whitespace-only file content."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        if not content or not content.strip():
            return [
                Violation(
                    rule_id="GUARD_EMPTY_FILE",
                    message=f"File '{file_path}' is empty — cannot validate",
                    severity="critical",
                    action="block_merge",
                )
            ]
        return []


class GuardExtensionCheck(Rule):
    """Reject files that don't end with .gd."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        if not file_path.endswith(".gd"):
            return [
                Violation(
                    rule_id="GUARD_EXTENSION",
                    message=f"File '{file_path}' is not a GDScript file — wrong extension",
                    severity="critical",
                    action="block_merge",
                )
            ]
        return []


class GuardMassiveFile(Rule):
    """Reject files over 2000 lines."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        line_count = content.count("\n") + 1
        if line_count > MAX_LINES_MASSIVE:
            return [
                Violation(
                    rule_id="GUARD_MASSIVE_FILE",
                    message=f"File '{file_path}' has {line_count} lines "
                    f"(max {MAX_LINES_MASSIVE}) — too large for safe processing",
                    severity="critical",
                    action="block_merge",
                )
            ]
        return []
