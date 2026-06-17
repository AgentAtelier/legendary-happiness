from .plan import DevForgePlan


class PlanValidationError(Exception):
    pass


def validate_plan(plan: DevForgePlan) -> None:
    """
    Structural validation of a DevForgePlan.
    """

    if not plan.steps:
        raise PlanValidationError("Plan contains no steps")

    for step in plan.steps:
        if not step.action:
            raise PlanValidationError("Plan step missing action")

        if not step.target:
            raise PlanValidationError("Plan step missing target")