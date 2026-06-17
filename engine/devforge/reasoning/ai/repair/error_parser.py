"""Error parser: converts Godot validation output into structured errors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class ParsedError:
    """Structured representation of a compiler/runtime error."""

    file: str
    line: int
    message: str
    error_type: str
    symbol: str | None = None

    @property
    def type(self) -> str:
        """Alias used by runtime / repair planner."""
        return self.error_type


class ErrorParser:
    """
    Parse Godot output logs into structured error objects
    that the repair system can understand.
    """

    GODOT_ERROR_PATTERN = re.compile(r"(?P<file>.*\.gd):(?P<line>\d+)\s*-\s*(?P<message>.+)")

    UNKNOWN_IDENTIFIER_PATTERN = re.compile(r"Identifier\s+'(?P<symbol>\w+)'\s+not\s+declared")

    def parse_report(self, report) -> List[ParsedError]:
        """
        Extract structured errors from a GodotRunner report.
        """

        if not report or not report.raw_output:
            return []

        return self.parse_report_from_text(report.raw_output)

    def parse_report_from_text(self, raw_output: str) -> List[ParsedError]:
        """
        Extract structured errors from raw Godot log text.

        Used by the MCP executor which receives logs as plain strings
        rather than a structured report object.
        """
        if not raw_output or not raw_output.strip():
            return []

        errors: List[ParsedError] = []

        lines = raw_output.splitlines()

        for line in lines:
            match = self.GODOT_ERROR_PATTERN.search(line)

            if not match:
                continue

            file = match.group("file")
            line_number = int(match.group("line"))
            message = match.group("message")

            error_type = "syntax_error"
            symbol = None

            unknown_match = self.UNKNOWN_IDENTIFIER_PATTERN.search(message)
            if unknown_match:
                error_type = "unknown_identifier"
                symbol = unknown_match.group("symbol")

            errors.append(
                ParsedError(
                    file=file,
                    line=line_number,
                    message=message,
                    error_type=error_type,
                    symbol=symbol,
                )
            )

        return errors
