"""Lint rules — individual checks for content quality.

Each rule takes entries and optional schema, returns a list of LintFinding objects.
Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from devforge.lore.schema import SchemaDefinition


@dataclass
class LintFinding:
    """A single content quality issue found by the linter."""

    rule_id: str  # "L01", "L02", etc.
    severity: str  # "ERROR" | "WARNING" | "INFO"
    entry_index: int
    entry_id: str
    field: str | None
    message: str
    suggestion: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "entry_index": self.entry_index,
            "entry_id": self.entry_id,
            "field": self.field,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# ── Rule implementations ────────────────────────────────────────


def check_duplicate_ids(
    entries: list[dict],
    id_field: str = "id",
) -> list[LintFinding]:
    """Detect duplicate IDs within a single file."""
    findings: list[LintFinding] = []
    seen: dict[str, int] = {}  # id → first occurrence index
    empty_count = 0
    first_empty_idx = -1

    for i, entry in enumerate(entries):
        eid = str(entry.get(id_field, ""))
        if not eid:
            empty_count += 1
            if empty_count == 1:
                first_empty_idx = i
            elif empty_count >= 2:
                findings.append(
                    LintFinding(
                        rule_id="L01",
                        severity="ERROR",
                        entry_index=i,
                        entry_id="<empty>",
                        field=id_field,
                        message=(f"Duplicate (empty) {id_field} — first empty entry at index {first_empty_idx}"),
                        suggestion="Give every entry a unique, non-empty id.",
                    )
                )
            continue

        if eid in seen:
            findings.append(
                LintFinding(
                    rule_id="L01",
                    severity="ERROR",
                    entry_index=i,
                    entry_id=eid,
                    field=id_field,
                    message=(f"Duplicate {id_field} '{eid}' — first seen at entry {seen[eid]}"),
                    suggestion=f"Ensure every {id_field} value is unique within the file.",
                )
            )
        else:
            seen[eid] = i

    return findings


def check_naming_convention(
    entries: list[dict],
    id_field: str = "id",
    pattern: str = r"^[a-z][a-z0-9_]*$",
    pattern_label: str = "snake_case",
    name_field: str = "name",
) -> list[LintFinding]:
    """Check that IDs follow a naming convention (default: snake_case).

    Also checks that the ``name`` field (if present) is not empty.
    """
    findings: list[LintFinding] = []
    compiled = re.compile(pattern)

    for i, entry in enumerate(entries):
        eid = str(entry.get(id_field, ""))

        # ── ID convention check ──
        if eid and not compiled.match(eid):
            findings.append(
                LintFinding(
                    rule_id="L02",
                    severity="WARNING",
                    entry_index=i,
                    entry_id=eid,
                    field=id_field,
                    message=f"ID '{eid}' does not match {pattern_label} convention ({pattern}).",
                    suggestion=f"Rename the {id_field} to follow {pattern_label}.",
                )
            )

        # ── Name field check ──
        if name_field:
            name = entry.get(name_field)
            if name is None:
                findings.append(
                    LintFinding(
                        rule_id="L03",
                        severity="ERROR",
                        entry_index=i,
                        entry_id=eid,
                        field=name_field,
                        message=f"'{name_field}' is null/None.",
                        suggestion=f"Provide a {name_field} for this entry.",
                    )
                )
            elif isinstance(name, str) and not name.strip():
                findings.append(
                    LintFinding(
                        rule_id="L03",
                        severity="ERROR",
                        entry_index=i,
                        entry_id=eid,
                        field=name_field,
                        message=f"'{name_field}' is empty or whitespace-only.",
                        suggestion=f"Provide a non-empty {name_field}.",
                    )
                )

    return findings


def check_empty_required(
    entries: list[dict],
    schema: SchemaDefinition | None = None,
    name_field: str = "name",
) -> list[LintFinding]:
    """Flag empty strings, whitespace-only strings, and None values.

    If *schema* is provided, only checks required fields defined in the
    schema (ERROR severity).  Otherwise, checks all string fields with
    WARNING severity (no schema to distinguish required from optional).
    Skips *name_field* (handled by L03 naming_convention).
    """
    findings: list[LintFinding] = []
    has_schema = schema is not None
    required: set[str] | None = set(schema.required_fields()) if has_schema else None
    id_field = schema.id_field if has_schema else "id"
    severity = "ERROR" if has_schema else "WARNING"

    for i, entry in enumerate(entries):
        eid = str(entry.get(id_field, ""))

        for key, value in entry.items():
            # Schema-aware: only check required fields
            if required is not None and key not in required:
                continue
            # Skip the name field — L03 handles it
            if key == name_field:
                continue

            if value is None:
                findings.append(
                    LintFinding(
                        rule_id="L04",
                        severity=severity,
                        entry_index=i,
                        entry_id=eid,
                        field=key,
                        message=f"Field '{key}' is null/None.",
                        suggestion=f"Provide a non-empty value for '{key}'.",
                    )
                )
            elif isinstance(value, str) and not value.strip():
                findings.append(
                    LintFinding(
                        rule_id="L04",
                        severity=severity,
                        entry_index=i,
                        entry_id=eid,
                        field=key,
                        message=f"Field '{key}' is empty or whitespace-only.",
                        suggestion=f"Provide a non-empty value for '{key}' or mark it optional.",
                    )
                )

    return findings


def check_mismatched_keys(
    entries: list[dict],
    schema: SchemaDefinition,
) -> list[LintFinding]:
    """Flag entry keys that are not defined in the schema.

    Skips the schema's id_field (always present, defined at the top level).
    Unknown keys are accepted for forward compatibility when no schema is
    provided — this check is only active when a schema is given.
    """
    findings: list[LintFinding] = []
    known_keys = schema.field_map()
    id_field = schema.id_field

    for i, entry in enumerate(entries):
        eid = str(entry.get(id_field, ""))

        for key in entry:
            if key == id_field:
                continue
            if key not in known_keys:
                findings.append(
                    LintFinding(
                        rule_id="L05",
                        severity="WARNING",
                        entry_index=i,
                        entry_id=eid,
                        field=key,
                        message=(
                            f"Key '{key}' is not defined in schema '{schema.name}' — possibly a typo or orphaned field."
                        ),
                        suggestion=(f"Correct the field name or add '{key}' to the schema definition."),
                    )
                )

    return findings


def check_duplicate_ids_cross_file(
    entries: list[dict],
    other_entries: dict[str, list[dict]],  # schema_name → entries
    id_field: str = "id",
    target_schema_name: str | None = None,
) -> list[LintFinding]:
    """Detect IDs that appear in multiple data files.

    If *target_schema_name* is provided, only checks for duplicates
    against files of the same schema type.  Otherwise checks against
    all provided files (any schema).
    """
    findings: list[LintFinding] = []

    # Build index of IDs from other files, scoped to matching schema if given
    id_to_source: dict[str, str] = {}  # id → "schema_name"
    for schema_name, other_list in other_entries.items():
        if target_schema_name and schema_name != target_schema_name:
            continue
        for entry in other_list:
            oid = str(entry.get(id_field, ""))
            if oid:
                id_to_source[oid] = schema_name

    for i, entry in enumerate(entries):
        eid = str(entry.get(id_field, ""))
        if eid and eid in id_to_source:
            findings.append(
                LintFinding(
                    rule_id="L06",
                    severity="ERROR",
                    entry_index=i,
                    entry_id=eid,
                    field=id_field,
                    message=(f"ID '{eid}' already exists in {id_to_source[eid]} — duplicate across data files."),
                    suggestion=f"Use a unique {id_field} value across all files of this schema.",
                )
            )

    return findings
