"""Operation Generator — compiles IR plan steps into raw operations."""

from __future__ import annotations

from typing import Any, Dict

from devforge.compilation.ir.plan import DevForgePlan
from devforge.infrastructure.logger import logger


class OperationGenerator:
    def generate_from_plan(self, plan: DevForgePlan) -> Dict[str, Any]:
        """Generate operations from a validated DevForgePlan."""
        return plan.compile_all()

    def generate_from_steps(
        self,
        *,
        steps: DevForgePlan | Any,
        scene: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Backwards-compatible API used by the server."""

        if isinstance(steps, DevForgePlan):
            return self.generate_from_plan(steps)

        logger.warn("op_generator", "Received non-DevForgePlan steps, returning empty")
        return {"files": [], "operations": []}
