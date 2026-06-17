from __future__ import annotations

from devforge.reasoning.ai.repair.error_parser import ParsedError


class FaultLocalizer:
    """Minimal fault localizer that currently returns the parsed error unchanged."""

    def localize(self, error: ParsedError) -> ParsedError:
        return error
