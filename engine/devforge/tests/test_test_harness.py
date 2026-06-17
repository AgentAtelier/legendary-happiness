"""Unit tests for Test Harness: parse GDScript signatures, generate scaffolds."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Parsing ─────────────────────────────────────────────────────

def test_parse_simple_function() -> None:
    """Parses a function with typed params and return type."""
    from devforge.harness.scaffolder import TestScaffolder

    src = "func add(a: int, b: float = 0.0) -> int:\n    return a + b"
    scaff = TestScaffolder()
    funcs = scaff.parse(src)
    assert len(funcs) == 1
    assert funcs[0].name == "add"
    assert funcs[0].return_type == "int"
    assert len(funcs[0].params) == 2
    assert funcs[0].params[0]["name"] == "a"
    assert funcs[0].params[0]["type"] == "int"
    assert funcs[0].params[1]["default"] == "0.0"


def test_parse_multiple_functions() -> None:
    """Parses multiple functions from a script."""
    from devforge.harness.scaffolder import TestScaffolder

    src = """
extends Node

func _ready():
    pass

func take_damage(amount: int) -> void:
    health -= amount

func heal(amount: int = 10) -> void:
    health += amount

func get_health() -> int:
    return health
"""
    scaff = TestScaffolder()
    funcs = scaff.parse(src)
    # All 4 functions parsed (including _ready)
    assert len(funcs) == 4
    names = [f.name for f in funcs]
    assert "_ready" in names
    assert "take_damage" in names
    assert "heal" in names
    assert "get_health" in names


def test_parse_untyped_params() -> None:
    """Handles parameters without type annotations."""
    from devforge.harness.scaffolder import TestScaffolder

    src = "func greet(name, times) -> String:\n    return name"
    scaff = TestScaffolder()
    funcs = scaff.parse(src)
    assert len(funcs) == 1
    assert funcs[0].params[0]["type"] == "Variant"
    assert funcs[0].params[1]["type"] == "Variant"


# ── Public function filtering ───────────────────────────────────

def test_public_functions_filter() -> None:
    """Filters out private and built-in methods."""
    from devforge.harness.scaffolder import TestScaffolder

    scaff = TestScaffolder()
    funcs = scaff.parse("""
func _ready(): pass
func _process(delta): pass
func _input(event): pass
func attack(): pass
func heal(amount: int): pass
""")
    public = scaff.public_functions(funcs)
    names = [f.name for f in public]
    assert "attack" in names
    assert "heal" in names
    assert "_ready" not in names
    assert "_process" not in names


# ── Scaffold generation ─────────────────────────────────────────

def test_generate_scaffold() -> None:
    """Generates a WAT test file from function signatures."""
    from devforge.harness.scaffolder import TestScaffolder

    scaff = TestScaffolder()
    result = scaff.generate(
        "func add(a: int, b: int) -> int:\n    return a + b",
        script_path="scripts/math.gd",
    )
    assert result["function_count"] == 1
    assert result["public_count"] == 1
    assert "extends WAT" in result["test_scaffold"]
    assert "func test_add()" in result["test_scaffold"]
    assert "assert(true)" in result["test_scaffold"]
    assert "TODO" in result["test_scaffold"]


def test_generate_skips_private() -> None:
    """Scaffold excludes private (_-prefixed) functions."""
    from devforge.harness.scaffolder import TestScaffolder

    scaff = TestScaffolder()
    result = scaff.generate(
        "func _ready(): pass\nfunc attack(damage: int): pass",
    )
    assert result["function_count"] == 2
    assert result["public_count"] == 1
    assert "test_attack" in result["test_scaffold"]
    assert "test__ready" not in result["test_scaffold"]


def test_scaffold_placeholder_values() -> None:
    """Placeholder values match parameter types."""
    from devforge.harness.scaffolder import TestScaffolder

    scaff = TestScaffolder()
    # int → 0, String → "test", bool → false, Vector3 → Vector3.ZERO
    result = scaff.generate(
        "func configure(count: int, name: String, enabled: bool, pos: Vector3): pass",
    )
    assert "0" in result["test_scaffold"]
    assert '"test"' in result["test_scaffold"]
    assert "false" in result["test_scaffold"]
    assert "Vector3.ZERO" in result["test_scaffold"]


# ── scaffold_file convenience ───────────────────────────────────

def test_scaffold_file() -> None:
    """scaffold_file() is a convenience wrapper."""
    from devforge.harness.scaffolder import scaffold_file

    result = scaffold_file(
        "scripts/player.gd",
        "func jump(vel: float) -> void:\n    velocity.y = vel",
    )
    assert result["script_path"] == "scripts/player.gd"
    assert result["public_count"] == 1
    assert "test_jump" in result["test_scaffold"]


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_parse_simple_function,
        test_parse_multiple_functions,
        test_parse_untyped_params,
        test_public_functions_filter,
        test_generate_scaffold,
        test_generate_skips_private,
        test_scaffold_placeholder_values,
        test_scaffold_file,
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
