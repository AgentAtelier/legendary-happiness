"""Dialogue Engine tests — validation, loading, edge cases."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

VALID_TREE = {
    "id": "t1",
    "name": "Test",
    "start_node_id": "n1",
    "nodes": [
        {
            "id": "n1",
            "speaker_id": "eldrin",
            "text": "Hello",
            "choices": [{"text": "Who are you?", "next_id": "n2"}, {"text": "Goodbye", "next_id": ""}],
        },
        {"id": "n2", "speaker_id": "eldrin", "text": "I am Eldrin.", "is_terminal": True},
    ],
}


def test_validate_valid_tree() -> None:
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(VALID_TREE, f)
        path = f.name
    try:
        result = validate_dialogue_file(path, ["eldrin"])
        assert result["valid"] == True
        assert result["issue_count"] == 0
    finally:
        os.unlink(path)


def test_validate_missing_speaker() -> None:
    tree = dict(VALID_TREE)
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        path = f.name
    try:
        result = validate_dialogue_file(path, ["someone_else"])
        assert result["issue_count"] > 0
        assert any("eldrin" in i["detail"] for i in result["issues"])
    finally:
        os.unlink(path)


def test_validate_dead_end_choice() -> None:
    tree = {
        "id": "t",
        "name": "T",
        "start_node_id": "n1",
        "nodes": [{"id": "n1", "speaker_id": "npc", "text": "Hi", "choices": [{"text": "Go", "next_id": "missing"}]}],
    }
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        path = f.name
    try:
        result = validate_dialogue_file(path)
        assert result["issue_count"] >= 1
        assert any("dead_end" in i["issue_type"] for i in result["issues"])
    finally:
        os.unlink(path)


def test_validate_duplicate_ids() -> None:
    tree = {
        "id": "t",
        "name": "T",
        "start_node_id": "n1",
        "nodes": [{"id": "n1", "speaker_id": "npc", "text": "A"}, {"id": "n1", "speaker_id": "npc", "text": "B"}],
    }
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        path = f.name
    try:
        result = validate_dialogue_file(path)
        assert result["issue_count"] >= 1
        assert any("duplicate_id" in i["issue_type"] for i in result["issues"])
    finally:
        os.unlink(path)


def test_validate_missing_start() -> None:
    tree = {"id": "t", "name": "T", "start_node_id": "n99", "nodes": [{"id": "n1", "speaker_id": "npc", "text": "Hi"}]}
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        path = f.name
    try:
        result = validate_dialogue_file(path)
        assert result["issue_count"] >= 1
        assert any("missing_start" in i["issue_type"] for i in result["issues"])
    finally:
        os.unlink(path)


def test_load_missing_file() -> None:
    from devforge.dialogue.dialogue import load_dialogue_file

    result = load_dialogue_file("/nonexistent/path.json")
    assert result is None


def test_terminal_node_with_choices() -> None:
    tree = {
        "id": "t",
        "name": "T",
        "start_node_id": "n1",
        "nodes": [{"id": "n1", "speaker_id": "npc", "text": "Bye", "choices": [{"text": "ok"}], "is_terminal": True}],
    }
    from devforge.dialogue.dialogue import validate_dialogue_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(tree, f)
        path = f.name
    try:
        result = validate_dialogue_file(path)
        assert any("orphan_node" in i["issue_type"] for i in result["issues"])
    finally:
        os.unlink(path)


if __name__ == "__main__":
    tests = [
        test_validate_valid_tree,
        test_validate_missing_speaker,
        test_validate_dead_end_choice,
        test_validate_duplicate_ids,
        test_validate_missing_start,
        test_load_missing_file,
        test_terminal_node_with_choices,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
