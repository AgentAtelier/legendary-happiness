"""Unit tests for Lorekeeper: schema parsing, data validation, integrity."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _write_schema(tmpdir: str, name: str, data: dict) -> str:
    """Write a .schema.json file and return its path."""
    filepath = os.path.join(tmpdir, f"{name}.schema.json")
    with open(filepath, "w") as f:
        json.dump(data, f)
    return filepath


# ── schema_from_dict ────────────────────────────────────────────


def test_schema_from_dict_minimal() -> None:
    """Minimal schema dict parses correctly."""
    from devforge.lore.schema import schema_from_dict

    s = schema_from_dict({"name": "item", "version": 1})
    assert s.name == "item"
    assert s.version == 1
    assert s.fields == []


def test_schema_with_ref_field() -> None:
    """ref: type field sets foreign_ref."""
    from devforge.lore.schema import schema_from_dict

    s = schema_from_dict(
        {
            "name": "quest",
            "fields": [
                {"name": "reward_item", "type": "ref:item", "required": True, "foreign_ref": "item"},
            ],
        }
    )
    assert len(s.fields) == 1
    assert s.fields[0].foreign_ref == "item"
    assert s.ref_fields()[0].name == "reward_item"


# ── validate_data_entry ─────────────────────────────────────────


def test_validate_missing_required() -> None:
    """Missing required field is reported."""
    from devforge.lore.schema import validate_data_entry, SchemaDefinition, SchemaField

    s = SchemaDefinition(
        "item",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
            SchemaField("name", "str", required=True),
        ],
    )
    errors = validate_data_entry({"id": "sword01"}, s)
    assert len(errors) == 1
    assert "name" in errors[0]


def test_validate_valid_entry() -> None:
    """Valid entry produces no errors."""
    from devforge.lore.schema import validate_data_entry, SchemaDefinition, SchemaField

    s = SchemaDefinition(
        "item",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
            SchemaField("damage", "int"),
        ],
    )
    errors = validate_data_entry({"id": "sword01", "damage": 10}, s)
    assert errors == []


def test_validate_wrong_type() -> None:
    """Wrong field type is reported."""
    from devforge.lore.schema import validate_data_entry, SchemaDefinition, SchemaField

    s = SchemaDefinition(
        "item",
        id_field="id",
        fields=[
            SchemaField("damage", "int"),
        ],
    )
    errors = validate_data_entry({"id": "sword01", "damage": "high"}, s)
    assert len(errors) == 1
    assert "int" in errors[0]


# ── validate_referential_integrity ──────────────────────────────


def test_integrity_valid_refs() -> None:
    """Valid foreign-key references produce no errors."""
    from devforge.lore.schema import SchemaDefinition, SchemaField
    from devforge.lore.lorekeeper import validate_integrity as vi

    item_schema = SchemaDefinition(
        "item",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
        ],
    )
    npc_schema = SchemaDefinition(
        "npc",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
            SchemaField("favorite_item", "ref:item", foreign_ref="item"),
        ],
    )

    data_files = {
        "item": [{"id": "sword01"}],
        "npc": [{"id": "bob", "favorite_item": "sword01"}],
    }
    schemas = {"item": item_schema, "npc": npc_schema}

    result = vi(data_files, schemas)
    assert result["error_count"] == 0


def test_integrity_broken_ref() -> None:
    """Broken foreign-key reference is reported."""
    from devforge.lore.schema import SchemaDefinition, SchemaField
    from devforge.lore.lorekeeper import validate_integrity

    item_schema = SchemaDefinition(
        "item",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
        ],
    )
    npc_schema = SchemaDefinition(
        "npc",
        id_field="id",
        fields=[
            SchemaField("id", "str", required=True),
            SchemaField("favorite_item", "ref:item", foreign_ref="item"),
        ],
    )

    data_files = {
        "item": [{"id": "sword01"}],
        "npc": [{"id": "bob", "favorite_item": "nonexistent"}],
    }
    schemas = {"item": item_schema, "npc": npc_schema}

    result = validate_integrity(data_files, schemas)
    assert result["error_count"] >= 1
    assert "nonexistent" in result["errors"][0]


# ── list_schemas / load_schema ──────────────────────────────────


def test_list_schemas_scans_directory() -> None:
    """list_schemas finds .schema.json files."""
    from devforge.lore.lorekeeper import list_schemas

    with tempfile.TemporaryDirectory() as tmpdir:
        _write_schema(tmpdir, "item", {"name": "item", "fields": []})
        _write_schema(tmpdir, "npc", {"name": "npc", "fields": []})

        result = list_schemas(directory=tmpdir)
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"item", "npc"}


def test_list_schemas_empty_dir() -> None:
    """Empty schema directory returns empty list."""
    from devforge.lore.lorekeeper import list_schemas

    with tempfile.TemporaryDirectory() as tmpdir:
        result = list_schemas(directory=tmpdir)
        assert result == []


def test_load_schema_returns_none_for_missing() -> None:
    """load_schema returns None for unknown name."""
    from devforge.lore.lorekeeper import load_schema

    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_schema("nonexistent", directory=tmpdir)
        assert result is None


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_schema_from_dict_minimal,
        test_schema_with_ref_field,
        test_validate_missing_required,
        test_validate_valid_entry,
        test_validate_wrong_type,
        test_integrity_valid_refs,
        test_integrity_broken_ref,
        test_list_schemas_scans_directory,
        test_list_schemas_empty_dir,
        test_load_schema_returns_none_for_missing,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
