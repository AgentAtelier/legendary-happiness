from __future__ import annotations

from devforge.compilation.ir.plan import DevForgePlan
from devforge.compilation.ir.steps.scene_steps import (
    CreateEntityStep,
    CreateScriptStep,
    AttachScriptStep,
)


class PlanVerifier:
    """
    Verifies that a DevForgePlan is internally consistent
    before compilation begins.
    """

    # ---------------------------------------------------------

    def verify(self, plan: DevForgePlan) -> DevForgePlan:

        if not plan.steps:
            return plan

        created_nodes = set()
        created_scripts = set()

        verified_steps = []

        for step in plan.steps:

            # ---------------------------------------------
            # Track node creation
            # ---------------------------------------------

            if isinstance(step, CreateEntityStep):

                node_path = f"{step.parent}/{step.name}"

                created_nodes.add(node_path)

                verified_steps.append(step)

                continue

            # ---------------------------------------------
            # Track scripts
            # ---------------------------------------------

            if isinstance(step, CreateScriptStep):

                created_scripts.add(step.path)

                verified_steps.append(step)

                continue

            # ---------------------------------------------
            # Validate script attachments
            # ---------------------------------------------

            if isinstance(step, AttachScriptStep):

                if step.script not in created_scripts:
                    continue

                if step.node not in created_nodes:
                    continue

                verified_steps.append(step)

                continue

            # ---------------------------------------------
            # Default
            # ---------------------------------------------

            verified_steps.append(step)

        plan.steps = verified_steps

        return plan