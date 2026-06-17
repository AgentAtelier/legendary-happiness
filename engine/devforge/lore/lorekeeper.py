"""Lorekeeper engine — load schemas, validate data, check integrity.

Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from devforge.lore.schema import (
    SchemaDefinition,
    schema_from_dict,
    validate_data_entry,
    validate_referential_integrity,
)
from devforge.infrastructure.logger import logger


# Default directories (relative to project root)
DEFAULT_SCHEMA_DIR = ".devforge/lore/schemas"


def list_schemas(directory: str | None = None) -> list[dict]:
    """Scan for ``*.schema.json`` files and return schema summaries."""
    directory = directory or DEFAULT_SCHEMA_DIR
    path = Path(directory)
    if not path.is_dir():
        return []

    schemas: list[dict] = []
    for f in sorted(path.glob("*.schema.json")):
        try:
            s = _load_schema_file(str(f))
            schemas.append(
                {
                    "name": s.name,
                    "version": s.version,
                    "description": s.description,
                    "field_count": len(s.fields),
                    "required_fields": s.required_fields(),
                }
            )
        except Exception as exc:
            logger.warn("lorekeeper", f"Skipping {f.name}: {exc}")

    return sorted(schemas, key=lambda s: s["name"])


def load_schema(name: str, directory: str | None = None) -> SchemaDefinition | None:
    """Load a schema by name from disk."""
    directory = directory or DEFAULT_SCHEMA_DIR
    filepath = os.path.join(directory, f"{name}.schema.json")
    try:
        return _load_schema_file(filepath)
    except Exception as exc:
        logger.warn("lorekeeper", f"Failed to load schema '{name}': {exc}")
        return None


def load_data_file(filepath: str) -> list[dict] | None:
    """Load a JSON data file (array of entries). Returns None on failure."""
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warn("lorekeeper", f"{filepath}: expected a JSON array")
            return None
        return data
    except Exception as exc:
        logger.warn("lorekeeper", f"Failed to load {filepath}: {exc}")
        return None


def validate_data(
    schema: SchemaDefinition,
    entries: list[dict],
) -> dict:
    """Validate *entries* against *schema*.

    Returns:
        {
          "schema": "item",
          "total_entries": 50,
          "valid": 48,
          "errors": [
            "Missing required field 'damage' in item entry",
            ...
          ]
        }
    """
    errors: list[str] = []
    invalid_ids: set[str] = set()
    for entry in entries:
        entry_id = str(entry.get(schema.id_field, "<unknown>"))
        entry_errors = validate_data_entry(entry, schema)
        if entry_errors:
            invalid_ids.add(entry_id)
            for e in entry_errors:
                errors.append(f"[{entry_id}] {e}")

    return {
        "schema": schema.name,
        "total_entries": len(entries),
        "valid": len(entries) - len(invalid_ids),
        "error_count": len(errors),
        "errors": errors,
    }


def validate_integrity(
    data_files: dict[str, list[dict]],
    schemas: dict[str, SchemaDefinition],
) -> dict:
    """Check referential integrity across all data files.

    *data_files* maps schema name → list of entries.
    *schemas* maps schema name → SchemaDefinition.

    Returns:
        {
          "total_refs": 15,
          "valid_refs": 14,
          "errors": [
            "item 'sword01': npc_id='bob' does not exist in npc",
            ...
          ]
        }
    """
    # Build id → entry index for each schema
    data_index: dict[str, dict[str, dict]] = {}
    for schema_name, entries in data_files.items():
        schema = schemas.get(schema_name)
        if schema is None:
            continue
        index: dict[str, dict] = {}
        for entry in entries:
            eid = entry.get(schema.id_field)
            if eid is not None:
                index[str(eid)] = entry
        data_index[schema_name] = index

    all_errors: list[str] = []
    for schema_name, entries in data_files.items():
        schema = schemas.get(schema_name)
        if schema is None:
            continue
        errors = validate_referential_integrity(entries, schema, data_index)
        all_errors.extend(errors)

    return {
        "error_count": len(all_errors),
        "errors": all_errors,
    }


def _load_schema_file(filepath: str) -> SchemaDefinition:
    """Load and parse a .schema.json file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return schema_from_dict(data)
