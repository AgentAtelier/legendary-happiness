"""Unit tests for Quest Graph Validator: cycles, reachability, item/flag deadlocks."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _write_quests(tmpdir: str, quests: list[dict]) -> str:
    path = os.path.join(tmpdir, "quests.json")
    with open(path, "w") as f:
        json.dump(quests, f)
    return path


# ── Graph construction ──────────────────────────────────────────

def test_graph_start_nodes() -> None:
    """Quests with no prerequisites are start nodes."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", name="Start", prerequisites=[]),
        QuestNode(id="q2", name="Follow", prerequisites=["q1"]),
    ])
    assert g.start_nodes() == ["q1"]


def test_linear_graph_no_issues() -> None:
    """A linear quest chain has no issues."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[]),
        QuestNode(id="q2", prerequisites=["q1"]),
        QuestNode(id="q3", prerequisites=["q2"]),
    ])
    result = g.validate()
    assert result["issue_count"] == 0


# ── Unreachable detection ──────────────────────────────────────

def test_unreachable_detected() -> None:
    """A quest with a missing prerequisite is unreachable."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[]),
        QuestNode(id="q2", prerequisites=["nonexistent"]),
    ])
    result = g.validate()
    assert result["issue_count"] >= 1
    assert any(i["issue_type"] == "unreachable" for i in result["issues"])


# ── Cycle detection ────────────────────────────────────────────

def test_cycle_detected() -> None:
    """A prerequisite cycle is detected."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=["q2"]),
        QuestNode(id="q2", prerequisites=["q1"]),
    ])
    result = g.validate()
    assert any(i["issue_type"] == "cycle" for i in result["issues"])


def test_no_false_cycle() -> None:
    """A diamond dependency (shared prereq) is not a cycle."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[]),
        QuestNode(id="q2", prerequisites=["q1"]),
        QuestNode(id="q3", prerequisites=["q1"]),
        QuestNode(id="q4", prerequisites=["q2", "q3"]),
    ])
    result = g.validate()
    assert not any(i["issue_type"] == "cycle" for i in result["issues"])


# ── Item deadlock ──────────────────────────────────────────────

def test_item_deadlock_self_grant() -> None:
    """Quest requiring an item it grants itself."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[],
                  required_items=["sword"], grants_items=["sword"]),
    ])
    result = g.validate()
    assert any(i["issue_type"] == "item_deadlock" for i in result["issues"])


def test_item_can_come_from_other_quest() -> None:
    """Item requirement satisfied by another quest is fine."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[], grants_items=["sword"]),
        QuestNode(id="q2", prerequisites=["q1"], required_items=["sword"]),
    ])
    result = g.validate()
    assert not any(i["issue_type"] == "item_deadlock" for i in result["issues"])


# ── Flag deadlock ──────────────────────────────────────────────

def test_flag_deadlock_no_setter() -> None:
    """Required flag that no quest sets."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[],
                  required_flags=["castle_open"]),
    ])
    result = g.validate()
    assert any(i["issue_type"] == "flag_deadlock" for i in result["issues"])


def test_flag_valid() -> None:
    """Required flag set by another quest is fine."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=[], sets_flags=["castle_open"]),
        QuestNode(id="q2", prerequisites=["q1"], required_flags=["castle_open"]),
    ])
    result = g.validate()
    assert not any(i["issue_type"] == "flag_deadlock" for i in result["issues"])# ── Self-referencing edge case ─────────────────────────────────

def test_self_referencing_cycle() -> None:
    """A quest that lists itself as a prerequisite is a cycle."""
    from devforge.quests.graph import QuestGraph, QuestNode

    g = QuestGraph([
        QuestNode(id="q1", prerequisites=["q1"]),
    ])
    result = g.validate()
    assert any(i["issue_type"] == "cycle" for i in result["issues"])


# ── End-to-end via validator ───────────────────────────────────
def test_validate_quest_file() -> None:
    """validate_quest_file loads JSON and runs graph validation."""
    from devforge.quests.validator import validate_quest_file

    with tempfile.TemporaryDirectory() as tmpdir:
        path = _write_quests(tmpdir, [
            {"id": "q1", "name": "Start", "prerequisites": []},
            {"id": "q2", "name": "Follow", "prerequisites": ["q1"]},
        ])
        result = validate_quest_file(path)
        assert result["total_quests"] == 2
        assert result["issue_count"] == 0


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_graph_start_nodes,
        test_linear_graph_no_issues,
        test_unreachable_detected,
        test_cycle_detected,
        test_no_false_cycle,
        test_self_referencing_cycle,
        test_item_deadlock_self_grant,
        test_item_can_come_from_other_quest,
        test_flag_deadlock_no_setter,
        test_flag_valid,
        test_validate_quest_file,
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
