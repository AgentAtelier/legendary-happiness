from __future__ import annotations

from devforge.compilation.ir.plan import DevForgePlan
from devforge.compilation.ir.steps.base import PlanStep
from devforge.knowledge.system_graph.system_graph import SystemGraph


class ExecutionPlanner:
    """
    Determines safe execution order for plan steps.

    Uses the SystemGraph dependency ordering when possible.
    """

    def __init__(self, system_graph: SystemGraph):

        self.system_graph = system_graph

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_execution(self, plan: DevForgePlan) -> DevForgePlan:

        if not isinstance(plan, DevForgePlan):
            return plan

        if not plan.steps:
            return plan

        ordered_nodes = self.system_graph.topological_order()

        priority = {node: i for i, node in enumerate(ordered_nodes)}

        def step_key(step: PlanStep):

            # Determine target identifier
            target = None

            if hasattr(step, "node"):
                target = getattr(step, "node")

            elif hasattr(step, "name"):
                target = getattr(step, "name")

            elif hasattr(step, "path"):
                target = getattr(step, "path")

            if target is None:
                return 9999

            return priority.get(target, 9999)

        plan.steps.sort(key=step_key)

        return plan
