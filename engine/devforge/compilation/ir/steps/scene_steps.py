from dataclasses import dataclass
from typing import Dict, Any, List

from .base import PlanStep


# ---------------------------------------------------------
# Create Entity
# ---------------------------------------------------------


@dataclass
class CreateEntityStep(PlanStep):
    name: str
    node_type: str
    parent: str

    def __init__(self, name: str, node_type: str, parent: str):

        super().__init__(step_type="create_entity")

        self.name = name
        self.node_type = node_type
        self.parent = parent

    def compile(self) -> List[Dict[str, Any]]:

        return [
            {
                "type": "add_node",
                "parent": self.parent,
                "node_type": self.node_type,
                "name": self.name,
            }
        ]


# ---------------------------------------------------------
# Create Script
# ---------------------------------------------------------


@dataclass
class CreateScriptStep(PlanStep):
    path: str
    content: str

    def __init__(self, path: str, content: str):

        super().__init__(step_type="create_script")

        self.path = path
        self.content = content

    def compile(self) -> List[Dict[str, Any]]:

        return [
            {
                "type": "create_file",
                "path": self.path,
                "content": self.content,
            }
        ]


# ---------------------------------------------------------
# Attach Script
# ---------------------------------------------------------


@dataclass
class AttachScriptStep(PlanStep):
    node: str
    script: str

    def __init__(self, node: str, script: str):

        super().__init__(step_type="attach_script")

        self.node = node
        self.script = script

    def compile(self) -> List[Dict[str, Any]]:

        return [
            {
                "type": "attach_script",
                "node": self.node,
                "script": self.script,
            }
        ]


# ---------------------------------------------------------
# Set Property
# ---------------------------------------------------------


@dataclass
class SetPropertyStep(PlanStep):
    node: str
    property: str
    value: Any

    def __init__(self, node: str, property: str, value: Any):

        super().__init__(step_type="set_property")

        self.node = node
        self.property = property
        self.value = value

    def compile(self) -> List[Dict[str, Any]]:

        return [
            {
                "type": "set_property",
                "node": self.node,
                "property": self.property,
                "value": self.value,
            }
        ]
