"""Intermediate Representation for DevForge plans.

The IR sits between the LLM output (architecture delta) and the
final Godot operations. Steps compile() into deterministic operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# ── Base Step ──────────────────────────────────────────────


@dataclass
class PlanStep:
    """Base class for all plan steps."""

    step_type: str = ""

    def validate(self) -> List[str]:
        """Return list of validation errors (empty = valid)."""
        return []

    def compile(self) -> List[Dict[str, Any]]:
        """Convert to execution operations."""
        raise NotImplementedError(f"{self.__class__.__name__}.compile()")


# ── Scene Steps ────────────────────────────────────────────


@dataclass
class CreateEntityStep(PlanStep):
    name: str = ""
    node_type: str = "Node3D"
    parent: str = "/root/Main"

    def __post_init__(self):
        self.step_type = "create_entity"

    def validate(self) -> List[str]:
        errors = []
        if not self.name:
            errors.append("CreateEntityStep: name is required")
        if not self.parent:
            errors.append("CreateEntityStep: parent is required")
        return errors

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "add_node",
                "parent": self.parent,
                "node_type": self.node_type,
                "name": self.name,
            }
        ]


@dataclass
class CreateScriptStep(PlanStep):
    path: str = ""
    content: str = ""

    def __post_init__(self):
        self.step_type = "create_script"

    def validate(self) -> List[str]:
        errors = []
        if not self.path:
            errors.append("CreateScriptStep: path is required")
        if not self.content:
            errors.append("CreateScriptStep: content is required")
        return errors

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "create_file",
                "path": self.path,
                "content": self.content,
            }
        ]


@dataclass
class AttachScriptStep(PlanStep):
    node: str = ""
    script: str = ""

    def __post_init__(self):
        self.step_type = "attach_script"

    def validate(self) -> List[str]:
        errors = []
        if not self.node:
            errors.append("AttachScriptStep: node path is required")
        if not self.script:
            errors.append("AttachScriptStep: script path is required")
        return errors

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "attach_script",
                "node": self.node,
                "script": self.script,
            }
        ]


@dataclass
class RemoveNodeStep(PlanStep):
    node: str = ""

    def __post_init__(self):
        self.step_type = "remove_node"

    def validate(self) -> List[str]:
        errors = []
        if not self.node:
            errors.append("RemoveNodeStep: node path is required")
        return errors

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "remove_node",
                "node": self.node,
            }
        ]


@dataclass
class RenameNodeStep(PlanStep):
    node: str = ""
    new_name: str = ""

    def __post_init__(self):
        self.step_type = "rename_node"

    def validate(self) -> List[str]:
        errors = []
        if not self.node:
            errors.append("RenameNodeStep: node path is required")
        if not self.new_name:
            errors.append("RenameNodeStep: new_name is required")
        return errors

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "rename_node",
                "node": self.node,
                "new_name": self.new_name,
            }
        ]


@dataclass
class SetPropertyStep(PlanStep):
    node: str = ""
    property: str = ""
    value: Any = None

    def __post_init__(self):
        self.step_type = "set_property"

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "set_property",
                "node": self.node,
                "property": self.property,
                "value": self.value,
            }
        ]


@dataclass
class ConnectSignalStep(PlanStep):
    source: str = ""
    signal: str = ""
    target: str = ""
    method: str = ""

    def __post_init__(self):
        self.step_type = "connect_signal"

    def compile(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "connect_signal",
                "source": self.source,
                "signal": self.signal,
                "target": self.target,
                "method": self.method,
            }
        ]


# ── Plan Container ─────────────────────────────────────────


@dataclass
class DevForgePlan:
    goal: str = ""
    steps: List[PlanStep] = field(default_factory=list)

    def validate(self) -> List[str]:
        errors = []
        if not self.steps:
            errors.append("Plan has no steps")
        for step in self.steps:
            errors.extend(step.validate())
        return errors

    def compile_all(self) -> Dict[str, List]:
        """Compile all steps into files and operations."""
        files = []
        operations = []

        for step in self.steps:
            for op in step.compile():
                if op.get("type") == "create_file":
                    files.append(
                        {
                            "path": op.get("path"),
                            "content": op.get("content", ""),
                        }
                    )
                else:
                    operations.append(op)

        return {"files": files, "operations": operations}
