"""Unit tests for Error Triage: knowledge table, triage_text, edge cases.

Tests: all 20 regexes compile, table integrity, classification accuracy,
deduplication, empty input, category counts, unrecognised fallback.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Knowledge table integrity ───────────────────────────────────


def test_all_regexes_compile() -> None:
    """Every KNOWN_ERRORS entry has a compilable regex."""
    import re
    from devforge.triage.knowledge import KNOWN_ERRORS

    for entry in KNOWN_ERRORS:
        try:
            re.compile(entry.pattern, re.IGNORECASE)
        except re.error as e:
            raise AssertionError(f"{entry.id}: regex compile failed: {e}")


def test_all_entries_have_explanation_and_fix_hint() -> None:
    """Every table entry has non-empty explanation and fix_hint."""
    from devforge.triage.knowledge import KNOWN_ERRORS

    for entry in KNOWN_ERRORS:
        assert entry.explanation.strip(), f"{entry.id}: explanation is empty"
        assert entry.fix_hint.strip(), f"{entry.id}: fix_hint is empty"


def test_table_ids_are_unique() -> None:
    """No duplicate IDs in the knowledge table."""
    from devforge.triage.knowledge import KNOWN_ERRORS

    ids = [e.id for e in KNOWN_ERRORS]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {sorted(set(i for i in ids if ids.count(i) > 1))}"


def test_table_has_twenty_entries() -> None:
    """Knowledge table has at least 20 entries."""
    from devforge.triage.knowledge import KNOWN_ERRORS

    assert len(KNOWN_ERRORS) >= 20, f"Expected ≥20 entries, got {len(KNOWN_ERRORS)}"


# ── triage_text classification ──────────────────────────────────


def test_classify_missing_member() -> None:
    """Log with E01-pattern message → missing_member, known_id E01."""
    from devforge.triage.triage import triage_text

    log = "player.gd:42 - Invalid call. Nonexistent function 'move' in base 'Node3D'."
    result = triage_text(log)
    assert result["total_raw"] == 1
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["file"] == "player.gd"
    assert f["line"] == 42
    assert f["category"] == "missing_member"
    assert f["known_id"] == "E01"
    assert f["fix_hint"] is not None


def test_classify_null_access() -> None:
    """Log with null-instance message → null_access."""
    from devforge.triage.triage import triage_text

    log = "enemy.gd:15 - Attempt to call function 'take_damage' on a null instance."
    result = triage_text(log)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["category"] == "null_access"


def test_classify_unrecognized() -> None:
    """Unknown message → unrecognized, no known_id, explanation fallback."""
    from devforge.triage.triage import triage_text

    log = "weird.gd:99 - The flux capacitor is misaligned with the tachyon field."
    result = triage_text(log)
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["category"] == "unrecognized"
    assert f["known_id"] is None
    assert f["fix_hint"] is None
    assert "Unrecognized" in f["explanation"]


# ── Deduplication ───────────────────────────────────────────────


def test_dedupe_identical_errors() -> None:
    """Three identical errors → one finding with occurrence_count 3."""
    from devforge.triage.triage import triage_text

    log = (
        "player.gd:42 - Invalid call. Nonexistent function 'move' "
        "in base 'Node3D'.\n"
        "player.gd:42 - Invalid call. Nonexistent function 'move' "
        "in base 'Node3D'.\n"
        "player.gd:42 - Invalid call. Nonexistent function 'move' "
        "in base 'Node3D'."
    )
    result = triage_text(log)
    assert result["total_raw"] == 3
    assert len(result["findings"]) == 1
    assert result["findings"][0]["occurrence_count"] == 3


# ── Sorting ─────────────────────────────────────────────────────


def test_findings_sorted_by_file_then_line() -> None:
    """Two different files → findings sorted by (file, line)."""
    from devforge.triage.triage import triage_text

    log = "b.gd:20 - Division by zero.\na.gd:10 - Division by zero."
    result = triage_text(log)
    assert len(result["findings"]) == 2
    assert result["findings"][0]["file"] == "a.gd"
    assert result["findings"][1]["file"] == "b.gd"


# ── Edge cases ──────────────────────────────────────────────────


def test_empty_log_returns_zero() -> None:
    """Empty log → total_raw:0, findings:[], no crash."""
    from devforge.triage.triage import triage_text

    result = triage_text("")
    assert result["total_raw"] == 0
    assert result["findings"] == []
    assert result["by_category"] == {}


def test_by_category_sums_to_findings() -> None:
    """by_category counts sum to the number of unique findings."""
    from devforge.triage.triage import triage_text

    log = (
        "player.gd:42 - Invalid call. Nonexistent function 'move' "
        "in base 'Node3D'.\n"
        "enemy.gd:15 - Attempt to call function 'take_damage' "
        "on a null instance."
    )
    result = triage_text(log)
    by_cat_sum = sum(result["by_category"].values())
    assert by_cat_sum == len(result["findings"])


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_all_regexes_compile,
        test_all_entries_have_explanation_and_fix_hint,
        test_table_ids_are_unique,
        test_table_has_twenty_entries,
        test_classify_missing_member,
        test_classify_null_access,
        test_classify_unrecognized,
        test_dedupe_identical_errors,
        test_findings_sorted_by_file_then_line,
        test_empty_log_returns_zero,
        test_by_category_sums_to_findings,
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
