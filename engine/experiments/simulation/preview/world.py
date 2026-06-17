from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any
import copy


@dataclass
class WorldState:
    """
    Represents the full state of the simulated world.
    """

    time: float = 0.0

    entities: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    environment: Dict[str, float] = field(
        default_factory=lambda: {
            "temperature": 20.0,
            "rain": 0.0,
            "wind": 0.0,
        }
    )

    systems: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    events: List[Dict[str, Any]] = field(default_factory=list)

    # ----------------------------------------------------------------

    def advance_time(self, dt: float) -> None:
        self.time += dt

    # ----------------------------------------------------------------

    def snapshot(self) -> "WorldState":
        """
        Create a deep copy snapshot of the world.
        Useful for timeline replay and branching.
        """
        return copy.deepcopy(self)

    # ----------------------------------------------------------------

    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append(
            {
                "time": self.time,
                "type": event_type,
                "payload": payload,
            }
        )
