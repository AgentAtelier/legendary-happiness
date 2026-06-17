from devforge.reasoning.agents.agent import Agent
from devforge.reasoning.ai.design.game_architect import GameArchitect


class ArchitectAgent(Agent):

    def __init__(self, llm=None):

        super().__init__("architect", llm)

        self.architect = GameArchitect()

    def run(self, context):

        prompt = context["prompt"]

        graph = self.architect.synthesize(prompt, self.llm)

        return {
            "system_graph": graph
        }