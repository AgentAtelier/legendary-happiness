"""Unit tests for Project Navigator: search across filesystem and symbols."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Mock callables ───────────────────────────────────────────────


def _mock_find_symbols(path: str) -> dict | None:
    """Mock find_symbols: returns symbols matching the path."""
    if "player" in path:
        return {
            "class_name": "Player",
            "extends": "CharacterBody3D",
            "functions": [
                {"name": "apply_falling_damage", "args": ["amount: float"]},
                {"name": "_process", "args": ["delta: float"]},
            ],
            "signals": [
                {"name": "died"},
                {"name": "health_changed"},
            ],
            "export_vars": ["walk_speed", "jump_velocity"],
        }
    if "enemy" in path:
        return {
            "class_name": "",
            "extends": "Node3D",
            "functions": [
                {"name": "take_damage", "args": ["amount: int"]},
            ],
            "signals": [],
            "export_vars": [],
        }
    return None


def _mock_search_filesystem(query: str, path: str = "res://", recursive: bool = True) -> dict:
    """Mock search_filesystem: returns files matching query."""
    if "falling" in query.lower():
        return {
            "files": [
                {"path": "res://scripts/player.gd", "line": 142, "snippet": "apply_falling_damage()"},
                {"path": "res://scripts/combat.gd", "line": 56, "snippet": "falling damage here"},
            ]
        }
    if "damage" in query.lower():
        return {
            "files": [
                {"path": "res://scripts/player.gd", "line": 142, "snippet": "apply_falling_damage()"},
                {"path": "res://scripts/enemy.gd", "line": 30, "snippet": "take_damage()"},
            ]
        }
    if "died" in query.lower():
        return {
            "files": [
                {"path": "res://scripts/player.gd", "line": 200, "snippet": "emit died"},
            ]
        }
    return {"files": []}


# ── Tests ────────────────────────────────────────────────────────


def test_search_finds_filesystem_hits() -> None:
    """search returns filesystem hits for a matching query."""
    from devforge.navigator.navigator import ProjectNavigator

    nav = ProjectNavigator(_mock_find_symbols, _mock_search_filesystem)
    result = nav.search("falling damage")
    assert result["hit_count"] >= 2
    assert result["by_source"].get("filesystem", 0) >= 2


def test_search_finds_symbol_hits() -> None:
    """search returns symbol hits for matching function/signal names."""
    from devforge.navigator.navigator import ProjectNavigator

    nav = ProjectNavigator(_mock_find_symbols, _mock_search_filesystem)
    result = nav.search("damage")
    # Filesystem: 2 hits, symbols: apply_falling_damage + take_damage
    assert result["hit_count"] >= 4
    assert result["by_source"].get("symbol", 0) >= 2


def test_search_symbol_by_signal() -> None:
    """search finds signals by name."""
    from devforge.navigator.navigator import ProjectNavigator

    nav = ProjectNavigator(_mock_find_symbols, _mock_search_filesystem)
    result = nav.search("died")
    # No filesystem hits, but symbol search finds "died" signal
    hits = result["hits"]
    signal_hits = [h for h in hits if h.get("symbol_type") == "signal"]
    assert len(signal_hits) >= 1


def test_search_deduplicates() -> None:
    """search deduplicates hits with same (source, path, snippet)."""
    from devforge.navigator.navigator import ProjectNavigator

    nav = ProjectNavigator(_mock_find_symbols, _mock_search_filesystem)
    result = nav.search("damage")
    # player.gd appears in both filesystem and symbol hits
    # Should have unique (source, path, snippet) combos
    keys = {(h["source"], h["path"], h.get("snippet", "")) for h in result["hits"]}
    assert len(keys) == result["hit_count"]


def test_search_empty_query() -> None:
    """Empty query returns no hits."""
    from devforge.navigator.navigator import ProjectNavigator

    nav = ProjectNavigator(_mock_find_symbols, _mock_search_filesystem)
    result = nav.search("zzz_nonexistent")
    assert result["hit_count"] == 0


# ── SearchHit to_dict ────────────────────────────────────────────


def test_search_hit_to_dict() -> None:
    """SearchHit.to_dict() includes all relevant fields."""
    from devforge.navigator.navigator import SearchHit

    hit = SearchHit(
        source="filesystem",
        path="res://x.gd",
        line=10,
        snippet="hello",
        symbol_type="function",
    )
    d = hit.to_dict()
    assert d["source"] == "filesystem"
    assert d["path"] == "res://x.gd"
    assert d["line"] == 10
    assert d["snippet"] == "hello"
    assert d["symbol_type"] == "function"


def test_search_hit_minimal_to_dict() -> None:
    """SearchHit.to_dict() omits zero values."""
    from devforge.navigator.navigator import SearchHit

    hit = SearchHit(source="filename", path="res://x.gd")
    d = hit.to_dict()
    assert "line" not in d  # 0 should be omitted
    assert "snippet" not in d


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_search_finds_filesystem_hits,
        test_search_finds_symbol_hits,
        test_search_symbol_by_signal,
        test_search_deduplicates,
        test_search_empty_query,
        test_search_hit_to_dict,
        test_search_hit_minimal_to_dict,
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
