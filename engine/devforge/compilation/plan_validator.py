from __future__ import annotations

from typing import Any


class PlanValidationError(Exception):
    pass


VALID_OPERATIONS = {
    "create_file",
    "delete_file",
    "modify_file",
    "repair_file",
    "noop",
}


class PlanValidator:
    def validate(self, plan: Any) -> None:
        steps = getattr(plan, "steps", None)
        if not isinstance(steps, list):
            raise PlanValidationError("plan.steps must be a list")

        step_ids: set[str] = set()
        for step in steps:
            step_id = getattr(step, "step_id", None)
            if not isinstance(step_id, str) or not step_id:
                raise PlanValidationError("Each step must have a non-empty step_id")
            if step_id in step_ids:
                raise PlanValidationError(f"Duplicate step_id: {step_id}")
            step_ids.add(step_id)

            operation_type = getattr(step, "operation_type", None)
            if operation_type not in VALID_OPERATIONS:
                raise PlanValidationError(f"Invalid operation_type: {operation_type}")

        for step in steps:
            for dependency in getattr(step, "depends_on", []) or []:
                if dependency not in step_ids:
                    raise PlanValidationError(f"Step '{step.step_id}' depends on unknown step '{dependency}'")
                if dependency == step.step_id:
                    raise PlanValidationError(f"Step '{step.step_id}' cannot depend on itself")

        self._validate_acyclic(steps)

    def _validate_acyclic(self, steps: list[Any]) -> None:
        graph = {step.step_id: list(getattr(step, "depends_on", []) or []) for step in steps}
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise PlanValidationError(f"Cycle detected involving step '{step_id}'")

            visiting.add(step_id)
            for dep in graph[step_id]:
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in graph:
            visit(step_id)
