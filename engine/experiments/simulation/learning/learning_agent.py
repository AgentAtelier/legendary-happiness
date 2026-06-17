from devforge.reasoning.agents.agent import Agent
from devforge.learning.learning_engine import LearningEngine


class LearningAgent(Agent):

    def __init__(self):

        super().__init__("learning")

        self.engine = LearningEngine()

    def run(self, context):

        prompt = context.get("prompt")

        architecture = context.get("system_graph")

        operations = context.get("operations", [])

        success = context.get("status") == "ok"

        self.engine.learn(
            prompt,
            architecture,
            operations,
            success,
        )

        return {}