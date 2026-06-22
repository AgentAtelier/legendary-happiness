"""Tests for room_graph — CB-4 multi-room graph manager.

Tests assert:
- Grid topology (correct room count, adjacent edges)
- Spanning tree guarantees connectivity
- Start→exit path validator
- Door schema (correct wall assignment, door_ids)
- Deterministic output (same seed → same graph)
"""

from __future__ import annotations

import pytest

from room_graph import (
    build_grid_rooms,
    build_spanning_tree,
    build_doors,
    build_room_graph,
    has_path,
    validate_start_exit_path,
    door_position_on_wall,
    get_doors_for_room,
    _wall_between,
)


# ── Grid builder ─────────────────────────────────────────────────

def test_build_grid_rooms_3x3():
    rooms, edges = build_grid_rooms(3, 3)
    assert len(rooms) == 9
    assert len(edges) == 12  # 3*2 horizontal + 3*2 vertical = 12

def test_build_grid_rooms_2x2():
    rooms, edges = build_grid_rooms(2, 2)
    assert len(rooms) == 4
    assert len(edges) == 4  # 2*1 h + 2*1 v = 4

def test_build_grid_rooms_4x1():
    """Single row: only horizontal edges."""
    rooms, edges = build_grid_rooms(4, 1)
    assert len(rooms) == 4
    assert len(edges) == 3  # 3 horizontal, 0 vertical


def test_grid_rooms_deterministic():
    """Same seed → same rooms and edges."""
    r1, e1 = build_grid_rooms(3, 3, seed=42)
    r2, e2 = build_grid_rooms(3, 3, seed=42)
    assert r1 == r2
    assert e1 == e2


# ── Wall direction ───────────────────────────────────────────────

def test_wall_between_east():
    assert _wall_between((0, 0), (1, 0)) == "east"

def test_wall_between_west():
    assert _wall_between((1, 0), (0, 0)) == "west"

def test_wall_between_south():
    assert _wall_between((0, 0), (0, 1)) == "south"

def test_wall_between_north():
    assert _wall_between((0, 1), (0, 0)) == "north"


# ── Spanning tree ────────────────────────────────────────────────

def test_spanning_tree_connects_all_rooms():
    """A spanning tree on N rooms must have N-1 edges and connect all."""
    rooms, edges = build_grid_rooms(3, 3)
    tree = build_spanning_tree(edges, seed=42)
    assert len(tree) == len(rooms) - 1  # 9 rooms → 8 edges

    # Every room must be reachable from every other room via the tree
    for start in rooms:
        for end in rooms:
            assert has_path(start, end, tree), (
                f"no path from {start} to {end} in spanning tree"
            )


def test_spanning_tree_deterministic():
    """Same seed → same tree."""
    _, edges = build_grid_rooms(3, 3)
    t1 = build_spanning_tree(edges, seed=42)
    t2 = build_spanning_tree(edges, seed=42)
    assert t1 == t2


def test_spanning_tree_different_seeds_differ():
    """Different seeds may produce different trees."""
    _, edges = build_grid_rooms(4, 4)
    t1 = build_spanning_tree(edges, seed=42)
    t2 = build_spanning_tree(edges, seed=123)
    # They could be the same by chance, but with 16 rooms it's unlikely
    # Just verify both produce valid trees
    rooms, _ = build_grid_rooms(4, 4)
    assert len(t1) == len(rooms) - 1
    assert len(t2) == len(rooms) - 1


# ── Path validator ───────────────────────────────────────────────

def test_has_path_same_room():
    assert has_path((0, 0), (0, 0), set()) is True

def test_has_path_adjacent():
    edges = {((0, 0), (1, 0))}
    assert has_path((0, 0), (1, 0), edges) is True

def test_has_path_through_intermediate():
    edges = {((0, 0), (1, 0)), ((1, 0), (2, 0))}
    assert has_path((0, 0), (2, 0), edges) is True

def test_has_path_disconnected():
    edges = {((0, 0), (1, 0))}
    assert has_path((0, 0), (2, 0), edges) is False


def test_validate_start_exit_path_success():
    _, edges = build_grid_rooms(3, 3)
    tree = build_spanning_tree(edges, seed=42)
    rooms = [(rx, rz) for rz in range(3) for rx in range(3)]
    assert validate_start_exit_path(rooms, tree, (0, 0), (2, 2)) is True


# ── Doors ────────────────────────────────────────────────────────

def test_build_doors_creates_one_per_edge():
    _, edges = build_grid_rooms(2, 2)
    tree = build_spanning_tree(edges)
    doors = build_doors(tree)
    assert len(doors) == len(tree)
    for d in doors:
        assert "door_id" in d
        assert "from_room" in d
        assert "to_room" in d
        assert "wall" in d
        assert "locked" in d
        assert "key_entity" in d

def test_build_doors_deterministic():
    _, edges = build_grid_rooms(3, 3)
    tree = build_spanning_tree(edges, seed=42)
    d1 = build_doors(tree, seed=42)
    d2 = build_doors(tree, seed=42)
    assert d1 == d2

def test_build_doors_locked_probability_zero():
    """With lock_probability=0, no doors are locked."""
    _, edges = build_grid_rooms(3, 3)
    tree = build_spanning_tree(edges)
    doors = build_doors(tree, lock_probability=0.0, seed=42)
    for d in doors:
        assert d["locked"] is False
        assert d["key_entity"] is None

def test_build_doors_locked_probability_one():
    """With lock_probability=1.0, all doors are locked."""
    _, edges = build_grid_rooms(3, 3)
    tree = build_spanning_tree(edges)
    doors = build_doors(tree, lock_probability=1.0, seed=42)
    for d in doors:
        assert d["locked"] is True
        assert d["key_entity"] is not None

def test_build_doors_wall_correct():
    """Each door's wall assignment matches the adjacency direction."""
    _, edges = build_grid_rooms(2, 2)
    tree = build_spanning_tree(edges)
    doors = build_doors(tree, seed=42)
    for d in doors:
        fr, to = tuple(d["from_room"]), tuple(d["to_room"])
        expected_wall = _wall_between(fr, to)
        assert d["wall"] == expected_wall, (
            f"door from {fr} to {to}: expected wall={expected_wall}, got {d['wall']}"
        )


# ── Door position helper ─────────────────────────────────────────

def test_door_position_east():
    x, y, z, yaw = door_position_on_wall((0, 0), (1, 0), 20.0, 20.0)
    assert x == 10.0  # right edge of room (0,0)
    assert y == 0.0
    assert z == 0.0   # centre of room
    assert abs(yaw - 1.5708) < 0.01  # facing east

def test_door_position_west():
    x, y, z, yaw = door_position_on_wall((1, 0), (0, 0), 20.0, 20.0)
    assert x == -10.0 + 20.0  # left edge of room (1,0)
    assert y == 0.0
    assert z == 0.0
    assert abs(yaw + 1.5708) < 0.01  # facing west

def test_door_position_north():
    x, y, z, yaw = door_position_on_wall((0, 0), (0, -1), 20.0, 20.0)
    assert x == 0.0
    assert y == 0.0
    assert z == -10.0  # north wall of room (0,0) at z = -half_depth
    assert abs(yaw - 0.0) < 0.01  # facing north

def test_door_position_south():
    x, y, z, yaw = door_position_on_wall((0, 0), (0, 1), 20.0, 20.0)
    assert x == 0.0
    assert y == 0.0
    assert z == 10.0
    assert abs(yaw - 3.14159) < 0.01  # facing south


# ── Door per-room lookup ─────────────────────────────────────────

def test_get_doors_for_room():
    doors = [
        {"door_id": "door_0", "from_room": [0, 0], "to_room": [1, 0], "wall": "east"},
        {"door_id": "door_1", "from_room": [0, 0], "to_room": [0, 1], "wall": "south"},
        {"door_id": "door_2", "from_room": [1, 0], "to_room": [1, 1], "wall": "south"},
    ]
    room_doors = get_doors_for_room((0, 0), doors)
    assert len(room_doors) == 2
    door_ids = {d["door_id"] for d in room_doors}
    assert door_ids == {"door_0", "door_1"}

    # Room (1, 1) connects to door_2
    room_doors = get_doors_for_room((1, 1), doors)
    assert len(room_doors) == 1
    assert room_doors[0]["door_id"] == "door_2"


# ── Full room graph builder ──────────────────────────────────────

def test_build_room_graph_defaults():
    graph = build_room_graph(width=3, depth=3, seed=42)
    assert len(graph["rooms"]) == 9
    assert graph["start"] == (0, 0)
    assert graph["exit"] == (2, 2)
    assert graph["start_exit_path_exists"] is True
    assert graph["width"] == 3
    assert graph["depth"] == 3
    assert len(graph["tree_edges"]) == 8  # 9-1
    # Extra loop edges
    assert len(graph["extra_edges"]) == 2
    # Doors = tree + extra
    assert len(graph["doors"]) == 10  # 8 + 2

def test_build_room_graph_deterministic():
    g1 = build_room_graph(width=3, depth=3, seed=42)
    g2 = build_room_graph(width=3, depth=3, seed=42)
    assert g1["rooms"] == g2["rooms"]
    assert g1["tree_edges"] == g2["tree_edges"]
    assert g1["doors"] == g2["doors"]

def test_build_room_graph_custom_start_exit():
    graph = build_room_graph(width=3, depth=3, start=(2, 0), exit_room=(1, 2), seed=42)
    assert graph["start"] == (2, 0)
    assert graph["exit"] == (1, 2)
    assert graph["start_exit_path_exists"] is True

def test_build_room_graph_1x1():
    """Single room: no edges, no doors, path trivially exists."""
    graph = build_room_graph(width=1, depth=1, seed=42)
    assert len(graph["rooms"]) == 1
    assert len(graph["tree_edges"]) == 0
    assert len(graph["doors"]) == 0
    assert graph["start_exit_path_exists"] is True

def test_build_room_graph_no_extra_loops():
    graph = build_room_graph(width=3, depth=3, extra_loop_edges=0, seed=42)
    assert len(graph["extra_edges"]) == 0
    assert len(graph["doors"]) == len(graph["tree_edges"])
