from __future__ import annotations

from typing import Dict, List, Any

from .timeline import TimelineFrame
from .world import WorldState


# ---------------------------------------------------------------------
# Time Series Builder
# ---------------------------------------------------------------------


def build_environment_timeseries(
    frames: List[TimelineFrame],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build time series data for environment variables.
    """

    result: Dict[str, List[Dict[str, Any]]] = {}

    for frame in frames:

        world = frame.world

        for key, value in world.environment.items():

            if key not in result:
                result[key] = []

            result[key].append(
                {
                    "time": frame.time,
                    "value": value,
                }
            )

    return result


# ---------------------------------------------------------------------
# Event Timeline
# ---------------------------------------------------------------------


def build_event_timeline(
    frames: List[TimelineFrame],
) -> List[Dict[str, Any]]:
    """
    Collect events across the timeline.
    """

    events: List[Dict[str, Any]] = []

    for frame in frames:

        for event in frame.world.events:

            events.append(
                {
                    "time": event["time"],
                    "type": event["type"],
                    "payload": event["payload"],
                }
            )

    return events


# ---------------------------------------------------------------------
# World Snapshot
# ---------------------------------------------------------------------


def build_world_snapshot(world: WorldState) -> Dict[str, Any]:
    """
    Build a UI-friendly snapshot of the world state.
    """

    return {
        "time": world.time,
        "environment": dict(world.environment),
        "entities": dict(world.entities),
        "systems": dict(world.systems),
    }


# ---------------------------------------------------------------------
# Parameter View
# ---------------------------------------------------------------------


def build_parameter_view(parameters) -> Dict[str, Any]:
    """
    Convert parameter registry into UI-friendly format.
    """

    output: Dict[str, Any] = {}

    for system_name, params in parameters.items():

        output[system_name] = []

        for param in params.values():

            output[system_name].append(
                {
                    "name": param.name,
                    "value": param.value,
                    "min": param.min_value,
                    "max": param.max_value,
                    "step": param.step,
                    "description": param.description,
                }
            )

    return output