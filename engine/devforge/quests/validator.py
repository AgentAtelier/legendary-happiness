"""Quest Validator — load quest data, build graph, run validation.

Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

import json
from typing import Any

from devforge.quests.graph import QuestGraph, QuestNode


def quests_from_data(data: list[dict]) -> list[QuestNode]:
    """Parse quest entries into QuestNode objects.

    Each dict should have: id, name, prerequisites, required_items,
    grants_items, required_flags, sets_flags.  Unknown keys are ignored.
    """
    nodes: list[QuestNode] = []
    for entry in data:
        nodes.append(
            QuestNode(
                id=str(entry.get("id", "")),
                name=entry.get("name", ""),
                prerequisites=_list_str(entry.get("prerequisites", [])),
                required_items=_list_str(entry.get("required_items", [])),
                grants_items=_list_str(entry.get("grants_items", [])),
                required_flags=_list_str(entry.get("required_flags", [])),
                sets_flags=_list_str(entry.get("sets_flags", [])),
            )
        )
    return nodes


def validate_quest_file(filepath: str) -> dict:
    """Load a quest JSON data file, build a graph, and validate it.

    Returns the QuestGraph.validate() result, or an error dict on failure.
    """
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"Could not load quest file '{filepath}': {exc}"}

    if not isinstance(data, list):
        return {"error": f"Quest file '{filepath}' must be a JSON array of quest objects"}

    quests = quests_from_data(data)
    if not quests:
        return {
            "total_quests": 0,
            "start_nodes": 0,
            "issue_count": 0,
            "critical": 0,
            "warning": 0,
            "issues": [],
        }

    graph = QuestGraph(quests)
    return graph.validate()


def _list_str(value: Any) -> list[str]:
    """Convert a value to a list of strings safely."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]
