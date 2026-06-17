"""Unit tests for Batch Operator: parse_query, match_nodes, build_batch_ops.

Tests: structured query parsing, convenience phrasings, error handling,
matching logic (type, name, subtree), zero-match, operation shaping, ordering.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _tree(name: str = "Main", type_: str = "Node3D", *children: dict) -> dict:
    """Convenience: build a scene-tree dict."""
    return {"name": name, "type": type_, "children": list(children)}


def _leaf(name: str, type_: str = "Node3D") -> dict:
    """A node with no children."""
    return {"name": name, "type": type_}


# ── parse_query ─────────────────────────────────────────────────

def test_parse_type_only() -> None:
    """parse_query(\"type:OmniLight3D\") sets node_type."""
    from devforge.operations.batch_filter import parse_query

    f = parse_query("type:OmniLight3D")
    assert f.node_type == "OmniLight3D"
    assert f.name_contains is None
    assert f.under_path is None


def test_parse_combined() -> None:
    """Combined query sets all three fields."""
    from devforge.operations.batch_filter import parse_query

    f = parse_query("type:Timer name~heat under:/root/Main/Effects")
    assert f.node_type == "Timer"
    assert f.name_contains == "heat"
    assert f.under_path == "/root/Main/Effects"


def test_convenience_all_type_plural() -> None:
    """"all OmniLight3Ds" maps to type:OmniLight3D (plural stripped)."""
    from devforge.operations.batch_filter import parse_query

    f = parse_query("all OmniLight3Ds")
    assert f.node_type == "OmniLight3D"
    assert f.name_contains is None


def test_convenience_every_under() -> None:
    """"every Timer under /root/X" maps to type:Timer under:/root/X."""
    from devforge.operations.batch_filter import parse_query

    f = parse_query("every Timer under /root/Main/UI")
    assert f.node_type == "Timer"
    assert f.under_path == "/root/Main/UI"


def test_convenience_nodes_named() -> None:
    """"nodes named foo" maps to name~foo."""
    from devforge.operations.batch_filter import parse_query

    f = parse_query("nodes named MainCamera")
    assert f.name_contains == "MainCamera"
    assert f.node_type is None


def test_unknown_token_raises_valueerror() -> None:
    """Unknown token raises ValueError naming the valid forms."""
    from devforge.operations.batch_filter import parse_query

    try:
        parse_query("flavor:spicy")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "flavor:spicy" in str(e)
        assert "type:" in str(e)


def test_empty_query_raises_valueerror() -> None:
    """Empty query raises ValueError."""
    from devforge.operations.batch_filter import parse_query

    try:
        parse_query("   ")
        assert False, "Expected ValueError"
    except ValueError:
        pass


# ── match_nodes ─────────────────────────────────────────────────

_SCENE = _tree("Main", "Node3D",
    _tree("Enemies", "Node3D",
        _leaf("Goblin1", "CharacterBody3D"),
        _leaf("Goblin2", "CharacterBody3D"),
        _leaf("GoblinSpawner", "Node3D"),
    ),
    _tree("Lights", "Node3D",
        _leaf("Sun", "DirectionalLight3D"),
        _leaf("Torch1", "OmniLight3D"),
        _leaf("Torch2", "OmniLight3D"),
    ),
    _leaf("PlayerCamera", "Camera3D"),
)


def test_match_nodes_type() -> None:
    """match_nodes finds exactly the OmniLight3D nodes."""
    from devforge.operations.batch_filter import NodeFilter, match_nodes

    f = NodeFilter(node_type="OmniLight3D")
    matched = match_nodes(_SCENE, f)
    assert len(matched) == 2
    assert all("Torch" in p for p in matched)


def test_match_nodes_under_path() -> None:
    """under_path excludes same-type nodes outside the subtree."""
    from devforge.operations.batch_filter import NodeFilter, match_nodes

    f = NodeFilter(node_type="OmniLight3D", under_path="/root/Main/Enemies")
    matched = match_nodes(_SCENE, f)
    assert len(matched) == 0  # no OmniLight3Ds under Enemies

    f2 = NodeFilter(node_type="CharacterBody3D", under_path="/root/Main/Enemies")
    matched2 = match_nodes(_SCENE, f2)
    assert len(matched2) == 2  # two goblins


def test_match_nodes_name_case_insensitive() -> None:
    """name_contains is case-insensitive."""
    from devforge.operations.batch_filter import NodeFilter, match_nodes

    f = NodeFilter(name_contains="GOBLIN")
    matched = match_nodes(_SCENE, f)
    assert len(matched) == 3  # Goblin1, Goblin2, GoblinSpawner


def test_match_nodes_zero_match() -> None:
    """No-match query returns empty list (not an error)."""
    from devforge.operations.batch_filter import NodeFilter, match_nodes

    f = NodeFilter(node_type="NonExistentType")
    matched = match_nodes(_SCENE, f)
    assert matched == []


def test_match_nodes_ordering_stable() -> None:
    """Matched paths are sorted and stable across runs."""
    from devforge.operations.batch_filter import NodeFilter, match_nodes

    f = NodeFilter(node_type="CharacterBody3D")
    a = match_nodes(_SCENE, f)
    b = match_nodes(_SCENE, f)
    assert a == b
    assert a == sorted(a)


# ── build_batch_ops ─────────────────────────────────────────────

def test_build_batch_ops_shape() -> None:
    """Operation dicts have exactly the expected shape."""
    from devforge.operations.batch_filter import build_batch_ops

    ops = build_batch_ops(
        ["/root/Main/Lamp1", "/root/Main/Lamp2"],
        property="light_energy",
        value=0.8,
    )

    assert len(ops) == 2
    for op in ops:
        assert op["type"] == "set_property"
        assert "node" in op
        assert op["property"] == "light_energy"
        assert op["value"] == 0.8


def test_build_batch_ops_empty() -> None:
    """Empty path list returns empty ops list."""
    from devforge.operations.batch_filter import build_batch_ops

    ops = build_batch_ops([], property="x", value=1)
    assert ops == []


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_parse_type_only,
        test_parse_combined,
        test_convenience_all_type_plural,
        test_convenience_every_under,
        test_convenience_nodes_named,
        test_unknown_token_raises_valueerror,
        test_empty_query_raises_valueerror,
        test_match_nodes_type,
        test_match_nodes_under_path,
        test_match_nodes_name_case_insensitive,
        test_match_nodes_zero_match,
        test_match_nodes_ordering_stable,
        test_build_batch_ops_shape,
        test_build_batch_ops_empty,
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
