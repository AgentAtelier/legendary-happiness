from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Pattern:
    name: str
    description: str
    entities: List[str]
    scripts: List[str]
    dependencies: List[str]


class PatternLibrary:
    """
    Repository of reusable architecture patterns.

    These help the planner by suggesting known structures
    instead of forcing the LLM to invent architecture.
    """

    def __init__(self):

        self.patterns: Dict[str, Pattern] = {}

        self._register_builtin_patterns()

    # --------------------------------------------------------
    # Registration
    # --------------------------------------------------------

    def register(self, pattern: Pattern):

        self.patterns[pattern.name] = pattern

    # --------------------------------------------------------
    # Lookup
    # --------------------------------------------------------

    def find_relevant(self, prompt: str) -> List[Pattern]:

        prompt_lower = prompt.lower()

        matches: List[Pattern] = []

        for pattern in self.patterns.values():
            if pattern.name.lower() in prompt_lower:
                matches.append(pattern)

            for entity in pattern.entities:
                if entity.lower() in prompt_lower:
                    matches.append(pattern)

        return list(set(matches))

    # --------------------------------------------------------
    # Built-in patterns
    # --------------------------------------------------------

    def _register_builtin_patterns(self):

        self.register(
            Pattern(
                name="PlayerController",
                description="Basic player entity with movement controller",
                entities=["Player"],
                scripts=["player_controller.gd"],
                dependencies=["InputSystem"],
            )
        )

        self.register(
            Pattern(
                name="CameraFollow",
                description="Camera that follows player",
                entities=["Camera"],
                scripts=["camera_follow.gd"],
                dependencies=["Player"],
            )
        )

        self.register(
            Pattern(
                name="EnemyAI",
                description="Basic enemy AI behavior",
                entities=["Enemy"],
                scripts=["enemy_ai.gd"],
                dependencies=["NavigationSystem"],
            )
        )
