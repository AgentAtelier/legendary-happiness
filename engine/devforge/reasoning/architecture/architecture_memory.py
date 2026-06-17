from __future__ import annotations

from typing import List

from devforge.knowledge.system_graph.system_graph import SystemGraph


class ArchitectureMemory:
    """
    Provides semantic recall of previously created architecture.

    Uses the SystemGraph to identify relevant systems that
    may be reused for the current prompt.
    """

    def __init__(self, graph: SystemGraph):

        self.graph = graph

    # ---------------------------------------------------------

    def find_relevant_systems(self, prompt: str) -> List[str]:

        prompt_lower = prompt.lower()

        matches: List[str] = []

        for node in self.graph.nodes.values():

            if node.type.value != "system":
                continue

            name = node.name.lower()

            if name in prompt_lower:
                matches.append(node.name)

        return matches

    # ---------------------------------------------------------

    def build_context(self, prompt: str) -> str:

        systems = self.find_relevant_systems(prompt)

        if not systems:
            return ""

        lines = ["## Known Systems"]

        for s in systems:
            lines.append(f"- {s}")

        return "\n".join(lines)