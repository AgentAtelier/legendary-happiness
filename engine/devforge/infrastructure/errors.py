from __future__ import annotations


class StepExecutionError(RuntimeError):
    """Raised when a step fails during plan execution."""

    def __init__(self, step_id: str, error_type: str, message: str):
        self.step_id = step_id
        self.error_type = error_type
        self.message = message
        super().__init__(f"Step '{step_id}' failed ({error_type}): {message}")
