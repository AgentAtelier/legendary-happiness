"""TDD tests for ``foundry.world.persistence`` — save/load round-trip.

Spec: ``save_world`` writes ``op_log.json`` (authoritative) AND
``snapshot.json`` (materialized, for inspection). ``load_world`` reads
``op_log.json`` and replays to get the canonical ``World``.

The snapshot is a convenience for human inspection and for tests that
need to compare two worlds without running replay; it MUST agree with
replay(op_log) when they are sourced from the same World.
"""

from __future__ import annotations

import json

from world.hashing import canonical_json
from world.operations import replay
from world.persistence import load_world, save_world


# ── Round-trip equality ──────────────────────────────────────────────


def test_save_load_roundtrip_reproduces_equal_world(tmp_path):
    """A saved world, when loaded back, equals the original (dataclass
    equality on all four top-level fields)."""
    ops = [
        {"op": "add_space", "id": "hall",
          "brief": {"name": "Hall"},
          "footprint": {"origin": [0, 0, 0], "size": [10, 4, 10]}},
        {"op": "add_space", "id": "keep",
          "brief": {"name": "Keep"},
          "footprint": {"origin": [20, 0, 0], "size": [12, 6, 12]}},
        {"op": "add_portal", "id": "p1",
          "from_space": "hall", "to_space": "keep",
          "position": [10, 0, 0], "size": [1, 2]},
        {"op": "add_entity", "space": "hall",
          "entity": {"id": "throne_0", "type": "throne",
                      "pos": [0, 0, 1], "properties": {"wood": "oak"}}},
    ]
    w = replay(ops)
    save_world(w, str(tmp_path))
    loaded = load_world(str(tmp_path))
    assert loaded == w


def test_save_load_roundtrip_preserves_op_log(tmp_path):
    """Loaded world's op_log equals the original op_log (verifies that
    op_log.json is read verbatim and not re-ordered or rewritten)."""
    ops = [
        {"op": "add_space", "id": "hall",
          "brief": {"name": "Hall"},
          "footprint": {"origin": [0, 0, 0], "size": [10, 4, 10]}},
        {"op": "add_entity", "space": "hall",
          "entity": {"id": "t1", "type": "table",
                      "pos": [1, 0, 1], "properties": {}}},
    ]
    w = replay(ops)
    save_world(w, str(tmp_path))
    loaded = load_world(str(tmp_path))
    assert loaded.op_log == ops


def test_save_writes_both_op_log_and_snapshot(tmp_path):
    """save_world writes BOTH files; the snapshot is for inspection."""
    w = replay([{"op": "add_space", "id": "hall",
                  "brief": {"name": "Hall"},
                  "footprint": {"origin": [0, 0, 0],
                                 "size": [10, 4, 10]}}])
    save_world(w, str(tmp_path))
    assert (tmp_path / "op_log.json").exists()
    assert (tmp_path / "snapshot.json").exists()


def test_snapshot_matches_replay_of_op_log(tmp_path):
    """The snapshot.json is byte-stable with a replay of the op_log."""
    ops = [
        {"op": "add_space", "id": "hall",
          "brief": {"name": "Hall"},
          "footprint": {"origin": [0, 0, 0], "size": [10, 4, 10]}},
        {"op": "add_entity", "space": "hall",
          "entity": {"id": "t1", "type": "table",
                      "pos": [1, 0, 1], "properties": {}}},
    ]
    w = replay(ops)
    save_world(w, str(tmp_path))

    snap = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    replayed = replay(ops)

    # Snapshot is a JSON-friendly view of the world. We compare on the
    # canonical-JSON form so insertion-order insensitivity doesn't
    # matter.
    snap_canon = canonical_json(snap)
    re_canon = canonical_json({
        "nodes": {sid: {"id": n.id, "seed": n.seed, "brief": n.brief,
                         "footprint": n.footprint,
                         "entities": [{"id": e.id, "type": e.type,
                                        "pos": e.pos,
                                        "properties": e.properties}
                                        for e in n.entities],
                         "portals": list(n.portals),
                         "gen_version": n.gen_version}
                  for sid, n in replayed.nodes.items()},
        "portals": {pid: {"id": p.id, "from_space": p.from_space,
                           "to_space": p.to_space,
                           "position": p.position, "size": p.size}
                  for pid, p in replayed.portals.items()},
        "op_log": replayed.op_log,
        "world_bible": replayed.world_bible,
    })
    assert snap_canon == re_canon


def test_load_uses_op_log_not_snapshot(tmp_path):
    """If a hostile snapshot.json is corrupted, load_world still succeeds
    because op_log.json is authoritative and replay does the work."""
    ops = [{"op": "add_space", "id": "hall",
             "brief": {"name": "Hall"},
             "footprint": {"origin": [0, 0, 0],
                            "size": [10, 4, 10]}}]
    save_world(replay(ops), str(tmp_path))
    # Corrupt the snapshot
    (tmp_path / "snapshot.json").write_text("garbage", encoding="utf-8")
    loaded = load_world(str(tmp_path))
    assert "hall" in loaded.nodes


def test_load_missing_dir_raises(tmp_path):
    """load_world on a directory with no op_log.json raises FileNotFoundError
    (so callers know the world is uninitialised rather than silently empty)."""
    import pytest
    with pytest.raises(FileNotFoundError):
        load_world(str(tmp_path / "nonexistent"))


def test_save_creates_parent_directory(tmp_path):
    """Passing a deep path that doesn't exist → save creates the parents."""
    nested = tmp_path / "deep" / "nest" / "world"
    ops = [{"op": "add_space", "id": "hall",
             "brief": {"name": "Hall"},
             "footprint": {"origin": [0, 0, 0],
                            "size": [10, 4, 10]}}]
    save_world(replay(ops), str(nested))
    assert nested.exists()
    assert (nested / "op_log.json").exists()
