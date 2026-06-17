"""Scene Refactorer tests — extraction, listing, edge cases."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

SCENE = {
    "name": "Main",
    "type": "Node3D",
    "children": [
        {
            "name": "Player",
            "type": "CharacterBody3D",
            "children": [{"name": "Camera3D", "type": "Camera3D", "children": []}],
        },
        {
            "name": "Enemies",
            "type": "Node3D",
            "children": [
                {"name": "Goblin1", "type": "CharacterBody3D", "children": []},
                {"name": "Goblin2", "type": "CharacterBody3D", "children": []},
                {"name": "GoblinBoss", "type": "CharacterBody3D", "children": []},
            ],
        },
    ],
}


def test_extract_subtree_generates_ops() -> None:
    from devforge.refactorer.refactorer import extract_subtree

    result = extract_subtree(SCENE, "/Main/Enemies", "res://scenes/enemies.tscn")
    assert result["success"] == True
    assert result["new_instance_name"] == "Enemies"
    assert result["operation_count"] == 2
    ops = result["operations"]
    assert ops[0]["type"] == "remove_node"
    assert ops[1]["type"] == "add_node"


def test_extract_missing_node() -> None:
    from devforge.refactorer.refactorer import extract_subtree

    result = extract_subtree(SCENE, "/Main/Nonexistent", "res://scenes/x.tscn")
    assert result["success"] == False
    assert "not found" in result["error"]


def test_extract_invalid_path() -> None:
    from devforge.refactorer.refactorer import extract_subtree

    result = extract_subtree(SCENE, "bad_path", "res://scenes/x.tscn")
    assert result["success"] == False


def test_collision_rename_strategy() -> None:
    from devforge.refactorer.refactorer import extract_subtree

    scene_with_collision = {
        "name": "Main",
        "type": "Node3D",
        "children": [
            {
                "name": "Enemies",
                "type": "Node3D",
                "children": [{"name": "Goblin", "type": "CharacterBody3D", "children": []}],
            },
            {
                "name": "Enemies",
                "type": "Node3D",
                "children": [{"name": "Orc", "type": "CharacterBody3D", "children": []}],
            },
        ],
    }
    result = extract_subtree(scene_with_collision, "/Main/Enemies", "res://scenes/x.tscn", collision_strategy="rename")
    assert result["new_instance_name"].startswith("Enemies_")


def test_collision_error_strategy() -> None:
    from devforge.refactorer.refactorer import extract_subtree

    scene_with_collision = {
        "name": "Main",
        "type": "Node3D",
        "children": [
            {"name": "Enemies", "type": "Node3D", "children": []},
            {"name": "Enemies", "type": "Node3D", "children": []},
        ],
    }
    result = extract_subtree(scene_with_collision, "/Main/Enemies", "res://scenes/x.tscn", collision_strategy="error")
    assert result["success"] == False
    assert "collision" in result["error"].lower()


def test_list_extractable_subtrees() -> None:
    from devforge.refactorer.refactorer import list_extractable

    result = list_extractable(SCENE, min_children=2)
    assert result["candidate_count"] >= 1
    assert any(c["name"] == "Enemies" for c in result["candidates"])


def test_list_extractable_min_children_filter() -> None:
    from devforge.refactorer.refactorer import list_extractable

    result = list_extractable(SCENE, min_children=5)
    assert result["candidate_count"] == 0


if __name__ == "__main__":
    tests = [
        test_extract_subtree_generates_ops,
        test_extract_missing_node,
        test_extract_invalid_path,
        test_collision_rename_strategy,
        test_collision_error_strategy,
        test_list_extractable_subtrees,
        test_list_extractable_min_children_filter,
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
