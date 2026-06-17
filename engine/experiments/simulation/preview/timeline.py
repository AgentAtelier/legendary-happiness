from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .world import WorldState


# ---------------------------------------------------------------------
# Timeline Frame
# ---------------------------------------------------------------------


@dataclass
class TimelineFrame:
    """
    Represents a single frame in the simulation timeline.
    """

    step: int
    time: float
    world: WorldState


# ---------------------------------------------------------------------
# Timeline Recorder
# ---------------------------------------------------------------------


class TimelineRecorder:
    """
    Records world state snapshots during simulation.

    Enables:
    - replay
    - timeline scrubbing
    - visualization
    - debugging
    """

    def __init__(self):

        self.frames: List[TimelineFrame] = []

    # ---------------------------------------------------------------

    def reset(self) -> None:

        self.frames.clear()

    # ---------------------------------------------------------------

    def record(self, step: int, world: WorldState) -> None:

        snapshot = world.snapshot()

        frame = TimelineFrame(
            step=step,
            time=snapshot.time,
            world=snapshot,
        )

        self.frames.append(frame)

    # ---------------------------------------------------------------

    def get_frame(self, index: int) -> TimelineFrame | None:

        if index < 0 or index >= len(self.frames):
            return None

        return self.frames[index]

    # ---------------------------------------------------------------

    def last_frame(self) -> TimelineFrame | None:

        if not self.frames:
            return None

        return self.frames[-1]

    # ---------------------------------------------------------------

    def frame_count(self) -> int:

        return len(self.frames)

    # ---------------------------------------------------------------

    def timeline(self) -> List[TimelineFrame]:

        return self.frames
