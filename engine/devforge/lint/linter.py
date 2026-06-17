"""Content Linter engine — orchestrates lint rules over data files.

Deterministic core (tier 0): no LLM calls.
"""

from __future__ import annotations

import json

from devforge.infrastructure.logger import logger
from devforge.lint.rules import (
    LintFinding,
    check_duplicate_ids,
    check_duplicate_ids_cross_file,
    check_empty_required,
    check_mismatched_keys,
    check_naming_convention,
)
from devforge.lore.lorekeeper import load_schema
from devforge.lore.schema import SchemaDefinition


class ContentLinter:
    """Orchestrates multiple lint rules over content data files.

    Usage::

        linter = ContentLinter()
        result = linter.lint_file("data/items.json", schema_name="item")
    """

    # All rules run by default — mismatched_keys is gated on schema presence
    _DEFAULT_RULES = [
        "duplicate_ids",
        "naming_convention",
        "empty_required",
        "mismatched_keys",
    ]

    def lint_file(
        self,
        entries: list[dict],
        schema: SchemaDefinition | None = None,
        rules: list[str] | None = None,
    ) -> dict:
        """Run lint rules against *entries*, optionally schema-aware.

        Returns:
            {
              "total_entries": 50,
              "finding_count": 5,
              "errors": 3,
              "warnings": 2,
              "findings": [...],
            }
        """
        rules = rules or self._DEFAULT_RULES
        findings: list[LintFinding] = []
        id_field = schema.id_field if schema else "id"

        for rule_name in rules:
            if rule_name == "duplicate_ids":
                findings.extend(check_duplicate_ids(entries, id_field=id_field))
            elif rule_name == "naming_convention":
                findings.extend(check_naming_convention(entries, id_field=id_field))
            elif rule_name == "empty_required":
                findings.extend(check_empty_required(entries, schema=schema))
            elif rule_name == "mismatched_keys":
                if schema is not None:
                    findings.extend(check_mismatched_keys(entries, schema))
            else:
                logger.warn("linter", f"Unknown lint rule '{rule_name}' — skipping")

        # Count severities
        errors = sum(1 for f in findings if f.severity == "ERROR")
        warnings = sum(1 for f in findings if f.severity == "WARNING")
        infos = sum(1 for f in findings if f.severity == "INFO")

        return {
            "total_entries": len(entries),
            "finding_count": len(findings),
            "errors": errors,
            "warnings": warnings,
            "info": infos,
            "findings": [f.to_dict() for f in findings],
        }


def lint_file(
    filepath: str,
    schema_name: str | None = None,
    other_files: dict[str, list[dict]] | None = None,
    rules: list[str] | None = None,
) -> dict:
    """Load a JSON data file and lint it.

    Args:
        filepath: Path to the JSON array data file.
        schema_name: Optional schema to validate against (enables L04 strict mode,
                     L05 mismatched keys).
        other_files: Optional dict of schema_name → entries for cross-file
                     duplicate detection (L06).
        rules: Optional list of rule names to run (default: all).

    Returns the lint result dict, or an error dict on failure.
    """
    # Load data
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"Could not load data file '{filepath}': {exc}"}

    if not isinstance(data, list):
        return {"error": f"Data file '{filepath}' must be a JSON array of entries"}

    entries: list[dict] = data
    if not entries:
        return {
            "total_entries": 0,
            "finding_count": 0,
            "errors": 0,
            "warnings": 0,
            "info": 0,
            "findings": [],
        }

    # Load schema if provided
    schema: SchemaDefinition | None = None
    if schema_name:
        schema = load_schema(schema_name)
        if schema is None:
            return {"error": f"Unknown schema: '{schema_name}'."}

    linter = ContentLinter()
    result = linter.lint_file(entries, schema=schema, rules=rules)

    # Run cross-file duplicate check if other files provided.
    # Only checks against files of the same schema type.
    if other_files:
        id_field = schema.id_field if schema else "id"
        cross_findings = check_duplicate_ids_cross_file(
            entries,
            other_files,
            id_field=id_field,
            target_schema_name=schema_name,
        )
        if cross_findings:
            result["findings"].extend(f.to_dict() for f in cross_findings)
            result["finding_count"] += len(cross_findings)
            e = sum(1 for f in cross_findings if f.severity == "ERROR")
            w = sum(1 for f in cross_findings if f.severity == "WARNING")
            result["errors"] += e
            result["warnings"] += w

    return result
