"""Unit tests for Content Linter: duplicate IDs, naming conventions, empty values, mismatched keys."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _write_data(tmpdir: str, filename: str, data: list[dict]) -> str:
    path = os.path.join(tmpdir, filename)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ── Duplicate IDs (L01) ─────────────────────────────────────────

def test_duplicate_ids_detected() -> None:
    """Two entries with the same id are flagged."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "sword01", "name": "Sword"},
        {"id": "sword01", "name": "Sword Again"},
    ])

    assert result["finding_count"] >= 1
    assert any(f["rule_id"] == "L01" for f in result["findings"])
    assert any(f["severity"] == "ERROR" for f in result["findings"])


def test_no_duplicates_clean() -> None:
    """Unique IDs produce no L01 findings."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "sword01", "name": "Sword"},
        {"id": "shield02", "name": "Shield"},
    ])

    assert not any(f["rule_id"] == "L01" for f in result["findings"])


# ── Naming convention (L02) ─────────────────────────────────────

def test_non_snake_case_flagged() -> None:
    """IDs that aren't snake_case get flagged as L02."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "Bad Name", "name": "Something"},
        {"id": "CamelCase", "name": "Something"},
    ])

    assert any(f["rule_id"] == "L02" for f in result["findings"])


def test_snake_case_passes() -> None:
    """Snake-case IDs produce no L02 findings."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "sword_of_fire", "name": "Fire Sword"},
        {"id": "health_potion_2", "name": "Health Potion"},
    ])

    assert not any(f["rule_id"] == "L02" for f in result["findings"])


# ── Empty name (L03) ────────────────────────────────────────────

def test_empty_name_flagged() -> None:
    """Empty or whitespace-only name is flagged as L03."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "item01", "name": ""},
        {"id": "item02", "name": "   "},
    ])

    assert any(f["rule_id"] == "L03" for f in result["findings"])
    assert sum(1 for f in result["findings"] if f["rule_id"] == "L03") >= 2


def test_valid_name_no_l03() -> None:
    """Non-empty name produces no L03."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "item01", "name": "Sword"},
    ])

    assert not any(f["rule_id"] == "L03" for f in result["findings"])


# ── Empty required (L03/L04) — null/empty name and required fields _

def test_null_value_flagged() -> None:
    """Null values in the name field are flagged as L03."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "item01", "name": None, "damage": 5},
    ])

    assert any(f["rule_id"] == "L03" for f in result["findings"])


def test_empty_duplicate_id_flagged() -> None:
    """Multiple entries with empty IDs are flagged as L01 duplicates."""
    from devforge.lint.linter import ContentLinter

    linter = ContentLinter()
    result = linter.lint_file([
        {"id": "", "name": "First"},
        {"id": "", "name": "Second"},
    ])

    assert any(
        f["rule_id"] == "L01" and f["entry_id"] == "<empty>"
        for f in result["findings"]
    )


# ── End-to-end via lint_file() ──────────────────────────────────

def test_lint_file_loads_json() -> None:
    """lint_file() loads a JSON file and runs lint rules."""
    from devforge.lint.linter import lint_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_data(tmpdir, "items.json", [
            {"id": "sword01", "name": "Sword"},
            {"id": "sword01", "name": "Sword Dupe"},
            {"id": "Bad Name", "name": "Something"},
        ])
        result = lint_file(path)
        assert result["total_entries"] == 3
        assert result["finding_count"] >= 2  # L01 duplicate + L02 naming


def test_lint_file_missing_file() -> None:
    """lint_file() returns error on missing file."""
    from devforge.lint.linter import lint_file

    result = lint_file("/nonexistent/path/data.json")
    assert "error" in result


def test_lint_file_bad_json() -> None:
    """lint_file() returns error on malformed JSON."""
    from devforge.lint.linter import lint_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("not json")
        result = lint_file(path)
        assert "error" in result


def test_lint_file_not_array() -> None:
    """lint_file() returns error on non-array JSON."""
    from devforge.lint.linter import lint_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "obj.json")
        with open(path, "w") as f:
            f.write('{"key": "val"}')
        result = lint_file(path)
        assert "error" in result


def test_lint_file_empty_array() -> None:
    """lint_file() handles empty array gracefully."""
    from devforge.lint.linter import lint_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_data(tmpdir, "empty.json", [])
        result = lint_file(path)
        assert result["total_entries"] == 0
        assert result["finding_count"] == 0


def test_lint_file_with_schema() -> None:
    """lint_file() with a non-existent schema returns error."""
    from devforge.lint.linter import lint_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_data(tmpdir, "items.json", [
            {"id": "sword01", "name": "Sword"},
        ])
        result = lint_file(path, schema_name="nonexistent_schema")
        assert "error" in result  # schema not found


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_duplicate_ids_detected,
        test_no_duplicates_clean,
        test_non_snake_case_flagged,
        test_snake_case_passes,
        test_empty_name_flagged,
        test_valid_name_no_l03,
        test_null_value_flagged,
        test_empty_duplicate_id_flagged,
        test_lint_file_loads_json,
        test_lint_file_missing_file,
        test_lint_file_bad_json,
        test_lint_file_not_array,
        test_lint_file_empty_array,
        test_lint_file_with_schema,
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
