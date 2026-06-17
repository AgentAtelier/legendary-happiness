"""Dialogue Engine — schema-constrained dialogue trees fed by Lorekeeper.

Deterministic core (tier 0): no LLM calls. Structures dialogue as data
(branching trees with conditions, speakers, and choices), validated against
Lorekeeper schemas. The dialogue_ui template renders the output.

Dialogue files are JSON arrays of dialogue node objects:
    { id, speaker_id, text, conditions, choices: [{ text, next_id, conditions }] }

Referential integrity: every speaker_id references a real NPC in the Lorekeeper;
every next_id points to a real dialogue node or a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from devforge.infrastructure.logger import logger


# ── Dialogue data model ──────────────────────────────────────────


@dataclass
class DialogueChoice:
    """A player response choice in a dialogue node."""

    text: str                          # "Tell me about the dragon."
    next_id: str = ""                  # target node ID, or "" for terminal
    conditions: dict[str, Any] = field(default_factory=dict)  # e.g. {"has_item": "sword", "quest_completed": "q1"}

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"text": self.text}
        if self.next_id:
            d["next_id"] = self.next_id
        if self.conditions:
            d["conditions"] = self.conditions
        return d


@dataclass
class DialogueNode:
    """A single node in a dialogue tree."""

    id: str                            # "npc_eldrin_greeting"
    speaker_id: str                    # "eldrin" (references NPC schema)
    text: str                          # "Well met, traveler. What brings you to these parts?"
    conditions: dict[str, Any] = field(default_factory=dict)  # conditions to show this node
    choices: list[DialogueChoice] = field(default_factory=list)
    emotion: str = "neutral"           # hint for portrait/animation
    is_terminal: bool = False          # dialogue ends after this node

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "id": self.id,
            "speaker_id": self.speaker_id,
            "text": self.text,
        }
        if self.conditions:
            d["conditions"] = self.conditions
        if self.choices:
            d["choices"] = [c.to_dict() for c in self.choices]
        if self.emotion != "neutral":
            d["emotion"] = self.emotion
        if self.is_terminal:
            d["is_terminal"] = True
        return d


@dataclass
class DialogueTree:
    """A complete dialogue tree for an NPC or conversation."""

    id: str                            # "eldrin_main"
    name: str                          # "Eldrin — Main Conversation"
    start_node_id: str                 # "npc_eldrin_greeting"
    nodes: list[DialogueNode] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_node_id": self.start_node_id,
            "version": self.version,
            "nodes": [n.to_dict() for n in self.nodes],
        }


# ── Validation ───────────────────────────────────────────────────


@dataclass
class DialogueIssue:
    """A problem found during dialogue validation."""

    issue_type: str       # "missing_speaker", "dead_end", "orphan_node", "duplicate_id", "missing_start"
    node_id: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"issue_type": self.issue_type, "detail": self.detail}
        if self.node_id:
            d["node_id"] = self.node_id
        return d


class DialogueValidator:
    """Validates dialogue trees for structural and referential integrity."""

    def validate(
        self,
        tree: DialogueTree,
        npc_ids: set[str] | None = None,
    ) -> list[DialogueIssue]:
        """Validate a dialogue tree.

        *npc_ids*: optional set of known NPC IDs for speaker validation.
        """
        issues: list[DialogueIssue] = []

        # Check start node exists
        node_map = {n.id: n for n in tree.nodes}
        if tree.start_node_id not in node_map:
            issues.append(DialogueIssue(
                "missing_start",
                detail=f"Start node '{tree.start_node_id}' not found in tree",
            ))

        # Check each node
        seen_ids: set[str] = set()
        for node in tree.nodes:
            # Duplicate IDs
            if node.id in seen_ids:
                issues.append(DialogueIssue(
                    "duplicate_id", node.id,
                    f"Duplicate node ID: '{node.id}'",
                ))
            seen_ids.add(node.id)

            # Speaker validation
            if npc_ids is not None and node.speaker_id not in npc_ids:
                issues.append(DialogueIssue(
                    "missing_speaker", node.id,
                    f"Speaker '{node.speaker_id}' is not a known NPC",
                ))

            # Choice validation
            for choice in node.choices:
                if choice.next_id and choice.next_id not in node_map:
                    issues.append(DialogueIssue(
                        "dead_end", node.id,
                        f"Choice leads to unknown node '{choice.next_id}'",
                    ))

            # Terminal nodes should have no choices
            if node.is_terminal and node.choices:
                issues.append(DialogueIssue(
                    "orphan_node", node.id,
                    "Terminal node should not have choices",
                ))

        return issues

    def validate_from_dict(
        self,
        tree_data: dict,
        npc_ids: set[str] | None = None,
    ) -> list[DialogueIssue]:
        """Validate a dialogue tree from a raw dict."""
        nodes = [
            DialogueNode(
                id=n["id"],
                speaker_id=n["speaker_id"],
                text=n["text"],
                conditions=n.get("conditions", {}),
                choices=[DialogueChoice(
                    text=c["text"],
                    next_id=c.get("next_id", ""),
                    conditions=c.get("conditions", {}),
                ) for c in n.get("choices", [])],
                emotion=n.get("emotion", "neutral"),
                is_terminal=n.get("is_terminal", False),
            )
            for n in tree_data.get("nodes", [])
        ]
        tree = DialogueTree(
            id=tree_data.get("id", ""),
            name=tree_data.get("name", ""),
            start_node_id=tree_data.get("start_node_id", ""),
            nodes=nodes,
            version=tree_data.get("version", 1),
        )
        return self.validate(tree, npc_ids)


def load_dialogue_file(filepath: str) -> DialogueTree | None:
    """Load a dialogue JSON file into a DialogueTree. Returns None on failure."""
    import json
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warn("dialogue", f"Failed to load {filepath}: {exc}")
        return None

    nodes = [
        DialogueNode(
            id=n["id"],
            speaker_id=n["speaker_id"],
            text=n["text"],
            conditions=n.get("conditions", {}),
            choices=[DialogueChoice(
                text=c["text"],
                next_id=c.get("next_id", ""),
                conditions=c.get("conditions", {}),
            ) for c in n.get("choices", [])],
            emotion=n.get("emotion", "neutral"),
            is_terminal=n.get("is_terminal", False),
        )
        for n in data.get("nodes", [])
    ]
    return DialogueTree(
        id=data.get("id", ""),
        name=data.get("name", ""),
        start_node_id=data.get("start_node_id", ""),
        nodes=nodes,
        version=data.get("version", 1),
    )


def validate_dialogue_file(
    filepath: str,
    npc_ids: list[str] | None = None,
) -> dict:
    """Validate a dialogue file and return results dict."""
    tree = load_dialogue_file(filepath)
    if tree is None:
        return {"error": f"Could not load dialogue file: {filepath}"}

    validator = DialogueValidator()
    issues = validator.validate(tree, set(npc_ids) if npc_ids else None)

    return {
        "filepath": filepath,
        "dialogue_id": tree.id,
        "name": tree.name,
        "node_count": len(tree.nodes),
        "issue_count": len(issues),
        "issues": [i.to_dict() for i in issues],
        "valid": len(issues) == 0,
    }
