"""Repair planner: converts compiler/runtime errors into patch steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class RepairStep:
    """A minimal step compatible with PatchEngine."""

    step_id: str
    operation_type: str
    target_file: str
    payload: dict


@dataclass
class RepairPlan:
    """Collection of repair steps."""

    steps: List[RepairStep]


class RepairPlanner:
    """
    Convert parsed errors into patchable repair plans.
    """

    def plan_repair(self, error, file_content: str, step) -> RepairPlan | None:
        """
        Generate a repair plan for a given error.
        """

        if not error:
            return None

        # Example strategy: syntax error fix
        if error.type == "syntax_error":
            return self._fix_syntax_error(error, file_content)

        # Example strategy: unknown identifier
        if error.type == "unknown_identifier":
            return self._fix_missing_symbol(error, file_content)

        # fallback
        return None

    # ------------------------------------------------------------

    def _fix_syntax_error(self, error, file_content: str) -> RepairPlan | None:
        """
        Attempt minimal syntax repair.
        """

        line = error.line
        lines = file_content.splitlines()

        if line - 1 >= len(lines):
            return None

        broken_line = lines[line - 1]

        # Example: missing colon after function
        if broken_line.strip().startswith("func") and not broken_line.strip().endswith(":"):
            fixed = broken_line + ":"
            lines[line - 1] = fixed

        else:
            return None

        new_content = "\n".join(lines)

        step = RepairStep(
            step_id="repair_syntax",
            operation_type="replace_file",
            target_file=error.file,
            payload={"content": new_content},
        )

        return RepairPlan([step])

    # ------------------------------------------------------------

    def _fix_missing_symbol(self, error, file_content: str) -> RepairPlan | None:
        """
        Attempt simple missing variable fix.
        """

        symbol = error.symbol

        insertion = f"\nvar {symbol} = null\n"

        new_content = insertion + file_content

        step = RepairStep(
            step_id="repair_symbol",
            operation_type="replace_file",
            target_file=error.file,
            payload={"content": new_content},
        )

        return RepairPlan([step])
