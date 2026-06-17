"""Unit tests for Progress Journal: append, get_entries, summary, retention."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_append_and_get() -> None:
    """Appended entries can be retrieved."""
    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:
        j.append("audit_scene", "Audit: clean", {"scene_version": 3})
        j.append("batch_apply", "Batch: 5 nodes", {"applied": 5})

        entries = j.get_entries(n=10)
        assert len(entries) == 2
        assert entries[0]["tool"] == "batch_apply"  # newest first
        assert entries[1]["tool"] == "audit_scene"
        assert entries[1]["data"]["scene_version"] == 3
    finally:
        j.clear()


def test_get_entries_filtered_by_tool() -> None:
    """get_entries filters by tool name."""
    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:
        j.append("audit_scene", "A1", {})
        j.append("batch_apply", "B1", {})
        j.append("audit_scene", "A2", {})

        audit_entries = j.get_entries(n=10, tool="audit_scene")
        assert len(audit_entries) == 2
        assert all(e["tool"] == "audit_scene" for e in audit_entries)

        batch_entries = j.get_entries(n=10, tool="batch_apply")
        assert len(batch_entries) == 1
    finally:
        j.clear()


def test_get_entries_limited() -> None:
    """get_entries respects the n limit."""
    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:
        for i in range(10):
            j.append("audit_scene", f"A{i}", {})

        entries = j.get_entries(n=3)
        assert len(entries) == 3
    finally:
        j.clear()


def test_summary_counts() -> None:
    """summary() returns correct by_tool counts."""
    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:
        j.append("audit_scene", "A1", {})
        j.append("audit_scene", "A2", {})
        j.append("batch_apply", "B1", {})

        s = j.summary()
        assert s["total_entries"] == 3
        assert s["by_tool"]["audit_scene"] == 2
        assert s["by_tool"]["batch_apply"] == 1
        assert len(s["recent_tools"]) == 2
    finally:
        j.clear()


def test_summary_empty() -> None:
    """summary() on empty journal returns zeros and None."""
    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:
        s = j.summary()
        assert s["total_entries"] == 0
        assert s["first_ts"] is None
        assert s["by_tool"] == {}
    finally:
        j.clear()


def test_retention_trims_oldest() -> None:
    """When at max_entries, oldest entries are trimmed."""
    from devforge.journal.journal import Journal

    j = Journal(
        path=os.path.join(tempfile.mkdtemp(), "test.jsonl"),
        max_entries=5,
    )
    try:
        for i in range(8):
            j.append("audit_scene", f"A{i}", {"i": i})

        entries = j.get_entries(n=20)
        assert len(entries) == 5  # capped at max_entries
        # First 3 should be trimmed
        preserved = [e["data"]["i"] for e in entries]
        assert preserved == [7, 6, 5, 4, 3]  # newest first
        assert 0 not in preserved
        assert 1 not in preserved
        assert 2 not in preserved
    finally:
        j.clear()


def test_persist_and_reload() -> None:
    """Entries persist across Journal instances (JSONL file)."""
    from devforge.journal.journal import Journal

    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "persist.jsonl")

    j1 = Journal(path=path)
    j1.append("audit_scene", "Persisted", {"v": 1})

    j2 = Journal(path=path)
    entries = j2.get_entries(n=10)
    assert len(entries) == 1
    assert entries[0]["event"] == "Persisted"
    assert entries[0]["data"]["v"] == 1

    j2.clear()


def test_thread_safety() -> None:
    """Concurrent appends don't corrupt the journal."""
    import threading

    from devforge.journal.journal import Journal

    j = Journal(path=os.path.join(tempfile.mkdtemp(), "test.jsonl"))
    try:

        def append_many(prefix: str):
            for i in range(20):
                j.append("test", f"{prefix}{i}", {})

        t1 = threading.Thread(target=append_many, args=("a",))
        t2 = threading.Thread(target=append_many, args=("b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert j.summary()["total_entries"] == 40
    finally:
        j.clear()


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_append_and_get,
        test_get_entries_filtered_by_tool,
        test_get_entries_limited,
        test_summary_counts,
        test_summary_empty,
        test_retention_trims_oldest,
        test_persist_and_reload,
        test_thread_safety,
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
