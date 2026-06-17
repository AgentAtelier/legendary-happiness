from devforge.reasoning.agents.agent import Agent
from devforge.reasoning.ai.repair.repair_planner import RepairPlanner


class RepairAgent(Agent):

    def __init__(self):

        super().__init__("repair")

        self.repair = RepairPlanner()

    def run(self, context):

        errors = context.get("errors")

        if not errors:
            return {}

        plan = self.repair.plan_repair(errors)

        return {
            "repair_plan": plan
        }