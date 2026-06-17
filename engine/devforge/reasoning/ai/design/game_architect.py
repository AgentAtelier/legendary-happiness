from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.knowledge.default_patterns import load_default_patterns


class GameArchitect:

    def __init__(self):

        self.patterns = load_default_patterns()

    # ─────────────────────────────────

    def synthesize(self, prompt: str, llm):

        graph = SystemGraph()

        # match patterns
        matches = self.patterns.match(prompt)

        for pattern in matches:

            for entity in pattern.get("entities", []):
                graph.add_entity(entity)

            for system in pattern.get("systems", []):
                graph.add_system(system)

            for signal in pattern.get("signals", []):

                graph.add_signal(
                    signal["name"],
                    signal["source"],
                    signal["target"],
                )

        return graph