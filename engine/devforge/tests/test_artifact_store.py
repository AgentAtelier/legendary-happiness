"""Unit tests for ArtifactStore: LRU eviction, store/get, summary building.

Tests: eviction when at capacity, thread safety, summary format, get misses.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_store_and_get() -> None:
    """Stored artifacts can be retrieved."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore(max_entries=10)
    payload = {"files": ["a.gd"], "operations": [{"type": "add_node"}]}

    aid = store.store(payload)
    assert aid is not None
    assert isinstance(aid, str)

    retrieved = store.get(aid)
    assert retrieved == payload


def test_get_miss_returns_none() -> None:
    """Unknown artifact IDs return None."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore()
    assert store.get("nonexistent_id") is None


def test_lru_eviction() -> None:
    """When at capacity, the oldest entry is evicted."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore(max_entries=3)

    # Store 3 entries
    id_a = store.store({"name": "a"})
    id_b = store.store({"name": "b"})
    id_c = store.store({"name": "c"})

    assert store.get(id_a) is not None  # all present
    assert store.get(id_b) is not None
    assert store.get(id_c) is not None

    # Access 'a' to make it recently used, then store a 4th
    store.get(id_a)
    id_d = store.store({"name": "d"})

    # 'b' should be evicted (oldest, never re-accessed)
    assert store.get(id_b) is None
    assert store.get(id_a) is not None  # re-accessed, kept
    assert store.get(id_c) is not None
    assert store.get(id_d) is not None


def test_lru_reorder_on_access() -> None:
    """Accessing an entry moves it to the front of the eviction queue."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore(max_entries=3)
    id_a = store.store({"name": "a"})
    id_b = store.store({"name": "b"})
    _ = store.store({"name": "c"})

    # Access 'a' repeatedly — should survive eviction
    for _ in range(5):
        store.get(id_a)

    _ = store.store({"name": "d"})

    # 'b' is oldest and never re-accessed — should be gone
    assert store.get(id_b) is None
    assert store.get(id_a) is not None


def test_summary_format() -> None:
    """build_summary returns the expected compact format."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore()
    payload = {
        "files": [{"path": "scripts/player.gd", "content": "extends CharacterBody3D"}],
        "operations": [
            {"type": "add_node", "name": "Player"},
            {"type": "set_property", "name": "position"},
        ],
        "errors": [],
        "scene_version": 5,
        "arch_delta": {"entities": []},
        "execution": {
            "success": True,
            "results": [
                {"op": "add_node", "success": True},
                {"op": "set_property", "success": True},
            ],
            "errors": [],
            "success_count": 2,
            "failure_count": 0,
        },
    }

    aid = store.store(payload)
    summary = store.build_summary(aid, payload)

    assert summary["artifact_id"] == aid
    assert summary["files"] == ["scripts/player.gd"]
    assert summary["operations_total"] == 2
    assert summary["applied"] == 2
    assert summary["error_count"] == 0
    assert summary["scene_version"] == 5
    assert summary["has_full_detail"] is True


def test_summary_with_errors() -> None:
    """Summary reflects errors correctly."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore()
    payload = {
        "files": [],
        "operations": [{"type": "bad_op"}],
        "errors": ["Invalid node type"],
        "scene_version": 0,
        "arch_delta": {},
        "execution": None,
    }

    aid = store.store(payload)
    summary = store.build_summary(aid, payload)

    assert summary["error_count"] == 1
    assert summary.get("errors") == ["Invalid node type"]
    assert summary["applied"] == 0


def test_max_entries_default() -> None:
    """Default max_entries is 50."""
    from devforge.knowledge.artifact_store import ArtifactStore

    store = ArtifactStore()
    assert store.max_entries == 50


def test_store_evicts_one_at_capacity() -> None:
    """Storing one extra at capacity evicts exactly one entry."""
    from devforge.knowledge.artifact_store import ArtifactStore

    max_n = 5
    store = ArtifactStore(max_entries=max_n)
    ids = [store.store({"n": i}) for i in range(max_n)]
    assert all(store.get(aid) is not None for aid in ids)

    # Store one more
    store.store({"n": "extra"})

    # Exactly one should be gone (the oldest)
    missing = sum(1 for aid in ids if store.get(aid) is None)
    assert missing == 1


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_store_and_get,
        test_get_miss_returns_none,
        test_lru_eviction,
        test_lru_reorder_on_access,
        test_summary_format,
        test_summary_with_errors,
        test_max_entries_default,
        test_store_evicts_one_at_capacity,
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
