"""Schema definitions for the Lorekeeper content database.

Each schema defines the shape of a content type (Item, NPC, Quest, etc.).
Fields have types and optional foreign-key references to other schemas.
The engine is generic — game-specific schemas are defined by the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from devforge.infrastructure.logger import logger


# ── Schema field types ──────────────────────────────────────────

VALID_FIELD_TYPES = {"str", "int", "float", "bool", "list", "dict"}


@dataclass
class SchemaField:
    """A single field in a content schema."""

    name: str           # "damage", "npc_id"
    type: str           # "int" | "str" | "float" | "bool" | "list" | "dict" | "ref:<schema>"
    required: bool = False
    default: Any = None
    description: str = ""
    foreign_ref: str | None = None  # schema name for "ref:" type fields

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.foreign_ref:
            d["foreign_ref"] = self.foreign_ref
        return d


@dataclass
class SchemaDefinition:
    """A complete content-type schema."""

    name: str           # "item", "npc", "quest"
    version: int = 1
    description: str = ""
    fields: list[SchemaField] = field(default_factory=list)
    id_field: str = "id"  # the primary-key field name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "id_field": self.id_field,
            "fields": [f.to_dict() for f in self.fields],
        }

    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    def field_map(self) -> dict[str, SchemaField]:
        return {f.name: f for f in self.fields}

    def ref_fields(self) -> list[SchemaField]:
        """Return fields that reference other schemas."""
        return [f for f in self.fields if f.foreign_ref is not None]


# ── Validation ──────────────────────────────────────────────────

def validate_data_entry(
    entry: dict,
    schema: SchemaDefinition,
) -> list[str]:
    """Validate a single data entry against a schema.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []
    field_map = schema.field_map()

    # Check required fields
    for name in schema.required_fields():
        if name not in entry or entry[name] is None:
            errors.append(
                f"Missing required field '{name}' in {schema.name} entry"
            )

    # Check field types and values
    for key, value in entry.items():
        if key not in field_map:
            continue  # unknown fields are silently accepted (forward compat)

        field = field_map[key]
        errors.extend(_validate_field_value(key, value, field))

    return errors


def validate_referential_integrity(
    entries: list[dict],
    schema: SchemaDefinition,
    data_index: dict[str, dict[str, dict]],
) -> list[str]:
    """Check that every foreign-key reference points to an existing entry.

    *data_index* maps schema name → id → entry dict.
    """
    errors: list[str] = []
    ref_fields = schema.ref_fields()

    for entry in entries:
        entry_id = entry.get(schema.id_field, "<unknown>")
        for ref_field in ref_fields:
            if ref_field.name not in entry:
                continue
            ref_value = entry[ref_field.name]
            if ref_value is None:
                continue

            target_schema = ref_field.foreign_ref
            if target_schema not in data_index:
                errors.append(
                    f"{schema.name} '{entry_id}': "
                    f"references unknown schema '{target_schema}' "
                    f"(field '{ref_field.name}')"
                )
                continue

            if ref_value not in data_index[target_schema]:
                errors.append(
                    f"{schema.name} '{entry_id}': "
                    f"{ref_field.name}='{ref_value}' does not exist in "
                    f"{target_schema}"
                )

    return errors


def _validate_field_value(
    key: str, value: Any, field: SchemaField,
) -> list[str]:
    """Validate that *value* matches *field.type*."""
    errors: list[str] = []
    ftype = field.type

    if ftype == "str":
        if not isinstance(value, str):
            errors.append(f"Field '{key}': expected str, got {type(value).__name__}")
    elif ftype == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"Field '{key}': expected int, got {type(value).__name__}")
    elif ftype == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"Field '{key}': expected float, got {type(value).__name__}")
    elif ftype == "bool":
        if not isinstance(value, bool):
            errors.append(f"Field '{key}': expected bool, got {type(value).__name__}")
    elif ftype == "list":
        if not isinstance(value, list):
            errors.append(f"Field '{key}': expected list, got {type(value).__name__}")
    elif ftype == "dict":
        if not isinstance(value, dict):
            errors.append(f"Field '{key}': expected dict, got {type(value).__name__}")
    elif ftype.startswith("ref:"):
        if not isinstance(value, str):
            errors.append(f"Field '{key}': expected str (ref), got {type(value).__name__}")
        # ref: field type — the actual target schema is in foreign_ref
    else:
        logger.warn("lore", f"Unknown field type '{ftype}' for '{key}'")

    return errors


# ── Serialization ───────────────────────────────────────────────

def schema_from_dict(data: dict) -> SchemaDefinition:
    """Parse a schema dict (from JSON) into a SchemaDefinition."""
    fields = []
    for f in data.get("fields", []):
        ftype = f["type"]
        foreign_ref = None
        if ftype.startswith("ref:"):
            foreign_ref = f.get("foreign_ref", ftype[4:])
        fields.append(SchemaField(
            name=f["name"],
            type=ftype,
            required=f.get("required", False),
            default=f.get("default"),
            description=f.get("description", ""),
            foreign_ref=foreign_ref,
        ))
    return SchemaDefinition(
        name=data["name"],
        version=data.get("version", 1),
        description=data.get("description", ""),
        fields=fields,
        id_field=data.get("id_field", "id"),
    )
