"""Unit tests for the rename/remove pipeline path.

Covers CHANGES.md known issue #3: DeterministicPlanner emits
``_rename``/``_remove`` delta markers, ArchitectureCompiler compiles
them to rename_node/remove_node ops, the validator accepts them, and
GodotAIMCPExecutor translates them to godot-ai's delete_node /
rename_node plugin commands.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


SCENE = {
    "name": "Main",
    "type": "Node3D",
    "children": [
        {"name": "Player", "type": "CharacterBody3D", "children": []},
        {"name": "Enemy", "type": "CharacterBody3D", "children": []},
    ],
}


def test_planner_rename_preserves_case() -> None:
    """'rename Player to Hero' keeps Godot-sensitive name casing."""
    from devforge.compilation.pipeline.architecture_planner import DeterministicPlanner

    delta = DeterministicPlanner().match("rename Player to Hero")
    assert delta is not None
    assert delta["_rename"] == {"from": "Player", "to": "Hero"}


def test_planner_remove_marker() -> None:
    """'delete node Enemy' produces a _remove marker."""
    from devforge.compilation.pipeline.architecture_planner import DeterministicPlanner

    delta = DeterministicPlanner().match("delete node Enemy")
    assert delta is not None
    assert delta["_remove"] == "Enemy"


def test_compiler_rename_resolves_case_insensitively() -> None:
    """A lowercased target still resolves to the real scene node path."""
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
    from devforge.knowledge.scene.scene_graph import SceneGraph

    delta = {
        "systems": [],
        "entities": [],
        "connections": [],
        "_rename": {"from": "player", "to": "Hero"},
    }
    plan = ArchitectureCompiler().compile(delta, scene=SceneGraph(SCENE))
    ops = plan.compile_all()["operations"]

    assert ops == [
        {
            "type": "rename_node",
            "node": "/root/Main/Player",
            "new_name": "Hero",
        }
    ]


def test_compiler_remove_emits_op() -> None:
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
    from devforge.knowledge.scene.scene_graph import SceneGraph

    delta = {
        "systems": [],
        "entities": [],
        "connections": [],
        "_remove": "Enemy",
    }
    plan = ArchitectureCompiler().compile(delta, scene=SceneGraph(SCENE))
    ops = plan.compile_all()["operations"]

    assert ops == [{"type": "remove_node", "node": "/root/Main/Enemy"}]


def test_validator_accepts_resolved_ops() -> None:
    from devforge.compilation.pipeline.validator import OperationValidator

    ops = [
        {"type": "rename_node", "node": "/root/Main/Player", "new_name": "Hero"},
        {"type": "remove_node", "node": "/root/Main/Enemy"},
    ]
    valid, errors = OperationValidator().validate(ops, SCENE, files=[])
    assert errors == [], errors
    assert len(valid) == 2


def test_validator_rejects_unknown_target() -> None:
    """An unresolved target falls through to a clear validator error."""
    from devforge.compilation.pipeline.architecture_compiler import ArchitectureCompiler
    from devforge.compilation.pipeline.validator import OperationValidator
    from devforge.knowledge.scene.scene_graph import SceneGraph

    delta = {
        "systems": [],
        "entities": [],
        "connections": [],
        "_remove": "Ghost",
    }
    plan = ArchitectureCompiler().compile(delta, scene=SceneGraph(SCENE))
    ops = plan.compile_all()["operations"]
    valid, errors = OperationValidator().validate(ops, SCENE, files=[])

    assert valid == []
    assert len(errors) == 1 and "not found" in errors[0]


def test_executor_translates_to_godot_ai_commands() -> None:
    """Ops map to godot-ai's plugin command names and param keys."""
    from devforge.execution.godot_ai_mcp import GodotAIMCPExecutor

    commands = GodotAIMCPExecutor._translate_ops_to_commands(
        [
            {"type": "remove_node", "node": "/root/Main/Enemy"},
            {"type": "rename_node", "node": "/root/Main/Player", "new_name": "Hero"},
        ]
    )

    assert commands == [
        {"command": "delete_node", "params": {"path": "/root/Main/Enemy"}},
        {
            "command": "rename_node",
            "params": {
                "path": "/root/Main/Player",
                "new_name": "Hero",
            },
        },
    ]


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_planner_rename_preserves_case,
        test_planner_remove_marker,
        test_compiler_rename_resolves_case_insensitively,
        test_compiler_remove_emits_op,
        test_validator_accepts_resolved_ops,
        test_validator_rejects_unknown_target,
        test_executor_translates_to_godot_ai_commands,
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
