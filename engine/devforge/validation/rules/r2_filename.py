"""R2: Filename Convention — snake_case only.

From validator_design.md: Must match ^[a-z][a-z0-9_]*\\.gd$
"""

from __future__ import annotations

import os
import re
from typing import List

from devforge.validation.rules.base import Rule, Violation

FILENAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.gd$")


class R2Filename(Rule):
    """Enforce snake_case naming for .gd files."""

    def check(self, file_path: str, content: str) -> List[Violation]:
        basename = os.path.basename(file_path)

        if not FILENAME_PATTERN.match(basename):
            return [
                Violation(
                    rule_id="R2_FILENAME",
                    message=f"Filename '{basename}' does not match snake_case "
                    f"convention (^[a-z][a-z0-9_]*\\.gd$)",
                    severity="critical",
                    action="block_merge",
                )
            ]
        return []
