"""Rule interface — shared types and utilities for the deterministic validator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Violation:
    """A single rule violation returned by ``Rule.check()``.

    Mirrors WorldForge Gate1's Violation with severity and action fields.
    """

    rule_id: str
    message: str
    line_number: int | None = None
    severity: str = "critical"  # "critical", "high", "warning"
    action: str = "block_merge"  # "block_merge" or "flag_for_review"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "line_number": self.line_number,
            "severity": self.severity,
            "action": self.action,
        }


class Rule(ABC):
    """Stateless rule that checks a GDScript file for violations.

    Every rule must implement::

        def check(self, file_path: str, content: str) -> List[Violation]
    """

    @abstractmethod
    def check(self, file_path: str, content: str) -> List[Violation]:
        """Check a file for violations of this rule.

        Args:
            file_path: Relative path to the file being checked.
            content: Full proposed content of the file (in-memory string).

        Returns:
            List of Violation objects (empty if the file passes).
        """
        ...

    @staticmethod
    def strip_comment(line: str) -> str:
        """Remove # comment from a line, respecting string literals.

        Shared utility used by R4, R6, and other rules that need
        to filter out comments before pattern matching.
        """
        in_string = False
        string_char = ""
        i = 0
        while i < len(line):
            ch = line[i]
            if in_string:
                if ch == "\\" and i + 1 < len(line):
                    i += 2
                    continue
                if ch == string_char:
                    in_string = False
            elif ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == "#":
                return line[:i]
            i += 1
        return line
