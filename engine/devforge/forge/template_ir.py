"""Template IR — data model for system templates.

A template is a human-written, tested game system (FPS controller,
save system, inventory, etc.) that DevForge can instantiate into a
live Godot scene.  The LLM selects and parameterizes; the engine
does the deterministic work.

Template files live as JSON on disk (``devforge/forge/templates/``).
Each template has:

- **slots** — user-configurable parameters (camera height, walk speed, ...)
- **scripts** — GDScript files with ``{{slot_name}}`` placeholders
- **operations** — scene operations (add_node, set_property, attach_script)
- **collision_check** — paths to verify before instantiation
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from devforge.infrastructure.logger import logger


# ── Data model ───────────────────────────────────────────────────


@dataclass
class TemplateSlot:
    """A user-configurable parameter in a template."""

    name: str         # "camera_height"
    type: str         # "float" | "int" | "str" | "bool" | "vec3" | "node_path"
    default: Any      # default value
    description: str  # one-sentence explanation for the parameter prompt

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "description": self.description,
        }


@dataclass
class TemplateScript:
    """A GDScript file that ships with the template."""

    path: str     # "scripts/player/fps_controller.gd"
    content: str  # script body with {{slot_name}} placeholders


@dataclass
class Template:
    """A complete game-system template."""

    slug: str           # "fps_controller"
    name: str           # "FPS Controller"
    description: str    # what the system does
    version: int = 1
    slots: list[TemplateSlot] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)  # prerequisite template slugs
    scripts: list[TemplateScript] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)
    collision_check: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "slots": [s.to_dict() for s in self.slots],
            "requires": self.requires,
            "scripts": [
                {"path": s.path, "content": s.content} for s in self.scripts
            ],
            "operations": self.operations,
            "collision_check": self.collision_check,
        }


# ── Slot resolution ─────────────────────────────────────────────

_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")  # matches {{slot_name}}


def resolve_slot_values(
    slots: list[TemplateSlot],
    provided: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge provided values with slot defaults.

    Validates that every provided key is a known slot and every
    value matches the declared slot type.  Returns the resolved
    dict keyed by slot name.  Raises ``ValueError`` on mismatches.
    """
    slot_map = {s.name: s for s in slots}
    provided = provided or {}

    # Check for unknown slot names
    unknown = set(provided) - set(slot_map)
    if unknown:
        raise ValueError(
            f"Unknown slot(s): {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(sorted(slot_map))}"
        )

    resolved: dict[str, Any] = {}
    for slot in slots:
        if slot.name in provided:
            value = provided[slot.name]
            _validate_slot_value(slot, value)
            resolved[slot.name] = value
        else:
            resolved[slot.name] = slot.default

    return resolved


def substitute_slots(text: str, slot_values: dict[str, Any]) -> str:
    """Replace ``{{slot_name}}`` placeholders in *text* with values.

    Numeric values are rendered as literals; strings are embedded
    inside the text as-is (for GDScript exports, the caller should
    handle quoting).
    """
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name not in slot_values:
            logger.warn("template_ir", f"Unknown slot '{{{name}}}' — leaving as-is")
            return m.group(0)
        value = slot_values[name]
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return _SLOT_RE.sub(_replace, text)


def substitute_operations(
    ops: list[dict],
    slot_values: dict[str, Any],
) -> list[dict]:
    """Deep-copy *ops* and substitute ``{{slot}}`` in all string values."""
    substituted = copy.deepcopy(ops)

    def _walk(obj: Any) -> Any:
        if isinstance(obj, str):
            return substitute_slots(obj, slot_values)
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return obj

    return [_walk(op) for op in substituted]


# ── Validation ──────────────────────────────────────────────────

_VALID_SLOT_TYPES = {"float", "int", "str", "bool", "vec3", "node_path"}


def _validate_slot_value(slot: TemplateSlot, value: Any) -> None:
    """Raise ValueError if *value* doesn't match *slot.type*."""
    if slot.type == "float":
        if not isinstance(value, (int, float)):
            raise ValueError(f"Slot '{slot.name}' expects float, got {type(value).__name__}")
    elif slot.type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Slot '{slot.name}' expects int, got {type(value).__name__}")
    elif slot.type == "str":
        if not isinstance(value, str):
            raise ValueError(f"Slot '{slot.name}' expects str, got {type(value).__name__}")
    elif slot.type == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"Slot '{slot.name}' expects bool, got {type(value).__name__}")
    elif slot.type == "vec3":
        if not (isinstance(value, dict) and "x" in value and "y" in value and "z" in value):
            raise ValueError(f"Slot '{slot.name}' expects {{x, y, z}} dict, got {value!r}")
    elif slot.type == "node_path":
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError(f"Slot '{slot.name}' expects a scene path starting with '/', got {value!r}")
    else:
        raise ValueError(f"Unknown slot type '{slot.type}' for '{slot.name}'")


# ── Serialization ───────────────────────────────────────────────

def template_from_dict(data: dict) -> Template:
    """Parse a template dict (from JSON) into a ``Template``."""
    slots = [
        TemplateSlot(
            name=s["name"],
            type=s["type"],
            default=s["default"],
            description=s["description"],
        )
        for s in data.get("slots", [])
    ]
    scripts = [
        TemplateScript(path=s["path"], content=s["content"])
        for s in data.get("scripts", [])
    ]
    return Template(
        slug=data["slug"],
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("version", 1),
        slots=slots,
        requires=data.get("requires", []),
        scripts=scripts,
        operations=data.get("operations", []),
        collision_check=data.get("collision_check", []),
    )
