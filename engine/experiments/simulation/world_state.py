from dataclasses import dataclass, field
from typing import Dict


@dataclass
class WorldState:

    time: float = 0.0

    entities: Dict[str, dict] = field(default_factory=dict)

    systems: Dict[str, dict] = field(default_factory=dict)

    environment: Dict[str, float] = field(
        default_factory=lambda: {
            "temperature": 20.0,
            "rain": 0.0,
            "wind": 0.0,
        }
    )

    # ─────────────────────────────────

    def advance_time(self, dt: float):

        self.time += dt