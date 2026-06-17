from devforge.reasoning.agents.agent import Agent


class PlannerAgent(Agent):

    def __init__(self):

        super().__init__("planner")

    def run(self, context):

        graph = context["system_graph"]

        steps = [{"action": "build", "target": node_id}
                 for node_id in graph.topological_order()]

        return {
            "execution_plan": steps
        }