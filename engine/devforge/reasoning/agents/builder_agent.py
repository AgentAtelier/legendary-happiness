from devforge.reasoning.agents.agent import Agent
from devforge.compilation.pipeline.operation_generator import OperationGenerator


class BuilderAgent(Agent):

    def __init__(self):

        super().__init__("builder")

        self.generator = OperationGenerator()

    def run(self, context):

        steps = context["execution_plan"]

        scene = context["scene_tree"]

        result = self.generator.generate_from_steps(
            steps=steps,
            scene=scene,
        )

        return result