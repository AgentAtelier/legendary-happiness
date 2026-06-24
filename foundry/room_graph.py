"""room_graph — CB-4 multi-room graph manager (C-5).

Builds a deterministic grid graph of rooms with:
- A spanning tree (guaranteed connectivity)
- Optional loop edges for exploration variety
- Door edges on shared walls between adjacent rooms
- A guaranteed start→exit path (validated)

Door schema (defined here — the CB-4 data contract):
```python
{
    "door_id": "door_N",
    "from_room": (rx, rz),
    "to_room": (rx, rz),
    "wall": "north|south|east|west",  # which wall the door sits on
    "locked": bool,                     # True if locked (key needed)
    "key_entity": str | None,          # carryable entity ID for the key
}
```

The module is extractable as a standalone dungeon-graph tool.
"""

from __future__ import annotations

# ── Grid-room type ──────────────────────────────────────────────

# A room on the grid: (rx, rz) coordinate pair.
# rx = column index, rz = row index.
GridRoom = tuple[int, int]

# A door edge between two adjacent rooms.
DoorEdge = dict  # see schema above


# ── Grid builder ────────────────────────────────────────────────

_WALL_DIRECTIONS: list[tuple[str, int, int]] = [
    ("north", 0, -1),
    ("south", 0, 1),
    ("east", 1, 0),
    ("west", -1, 0),
]


def _opposite_wall(wall: str) -> str:
    return {"north": "south", "south": "north", "east": "west", "west": "east"}[wall]


def build_grid_rooms(
    width: int,
    depth: int,
    seed: int = 42,
) -> tuple[list[GridRoom], set[tuple[GridRoom, GridRoom]]]:
    """Build a rectangular grid of rooms with all adjacent edges.

    Returns:
        rooms: list of (rx, rz) coordinates.
        adjacent_edges: set of unordered ((rx1,rz1), (rx2,rz2)) pairs.
    """
    rooms: list[GridRoom] = []
    for rz in range(depth):
        for rx in range(width):
            rooms.append((rx, rz))

    # Collect all adjacent (non-diagonal) edges
    edges: set[tuple[GridRoom, GridRoom]] = set()
    room_set = set(rooms)
    for rx, rz in rooms:
        for _wall, dx, dz in _WALL_DIRECTIONS:
            nx, nz = rx + dx, rz + dz
            if (nx, nz) in room_set:
                edge = ((rx, rz), (nx, nz))
                # Normalise: smaller coordinate first
                if (nx, nz) < (rx, rz):
                    edge = ((nx, nz), (rx, rz))
                edges.add(edge)
    return rooms, edges


def build_spanning_tree(
    edges: set[tuple[GridRoom, GridRoom]],
    seed: int = 42,
) -> set[tuple[GridRoom, GridRoom]]:
    """Build a random spanning tree from *edges* (Kruskal-style).

    Returns a set of edges forming a tree that connects all rooms.
    """
    import random as _random
    rng = _random.Random(seed)

    sorted_edges = sorted(edges, key=lambda e: rng.random())
    parent: dict[GridRoom, GridRoom] = {}

    def find(r: GridRoom) -> GridRoom:
        if r not in parent:
            parent[r] = r
        if parent[r] != r:
            parent[r] = find(parent[r])
        return parent[r]

    def union(a: GridRoom, b: GridRoom) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    tree: set[tuple[GridRoom, GridRoom]] = set()
    for edge in sorted_edges:
        a, b = edge
        if union(a, b):
            tree.add(edge)
    return tree


def build_doors(
    tree_edges: set[tuple[GridRoom, GridRoom]],
    extra_edges: set[tuple[GridRoom, GridRoom]] | None = None,
    lock_probability: float = 0.3,
    seed: int = 42,
) -> list[DoorEdge]:
    """Build door edges from tree edges (and optional extra loop edges).

    Doors are placed on the wall shared between the two rooms.
    """
    import random as _random
    rng = _random.Random(seed)

    doors: list[DoorEdge] = []
    all_edges = set(tree_edges)
    if extra_edges:
        all_edges |= extra_edges

    for i, (a, b) in enumerate(sorted(all_edges)):
        # Determine which wall the door sits on
        wall = _wall_between(a, b)

        locked = rng.random() < lock_probability
        door: DoorEdge = {
            "door_id": f"door_{i}",
            "from_room": list(a),
            "to_room": list(b),
            "wall": wall,
            "locked": locked,
            "key_entity": f"key_door_{i}" if locked else None,
        }
        doors.append(door)

    return doors


def _wall_between(a: GridRoom, b: GridRoom) -> str:
    """Determine which wall of room a faces room b.

    Precondition: a and b are adjacent (Manhattan distance == 1).
    """
    ax, az = a
    bx, bz = b
    if abs(ax - bx) + abs(az - bz) != 1:
        raise ValueError(f"rooms are not adjacent: {a} -> {b}")
    if bx > ax:
        return "east"
    if bx < ax:
        return "west"
    if bz > az:
        return "south"
    return "north"


# ── Path validator ──────────────────────────────────────────────

def has_path(
    start: GridRoom,
    end: GridRoom,
    edges: set[tuple[GridRoom, GridRoom]],
) -> bool:
    """Return True if a path exists from *start* to *end* along *edges*."""
    if start == end:
        return True

    # BFS
    adj: dict[GridRoom, list[GridRoom]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    visited: set[GridRoom] = set()
    queue: list[GridRoom] = [start]
    visited.add(start)

    while queue:
        current = queue.pop(0)
        if current == end:
            return True
        for neighbour in adj.get(current, []):
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)

    return False


def validate_start_exit_path(
    rooms: list[GridRoom],
    tree_edges: set[tuple[GridRoom, GridRoom]],
    start: GridRoom,
    exit_room: GridRoom,
) -> bool:
    """Validate that a path exists from *start* to *exit_room* via *tree_edges*.

    Returns True if a path exists, False otherwise.
    """
    return has_path(start, exit_room, tree_edges)


# ── Full room graph builder (convenience) ────────────────────────

def build_room_graph(
    width: int = 3,
    depth: int = 3,
    start: GridRoom | None = None,
    exit_room: GridRoom | None = None,
    extra_loop_edges: int = 2,
    lock_probability: float = 0.3,
    seed: int = 42,
) -> dict:
    """Build a complete room graph: rooms + spanning tree + doors + path check.

    Returns a dict:
    {
        "rooms": list of (rx, rz),
        "tree_edges": set of ((rx1,rz1), (rx2,rz2)),
        "extra_edges": set of ((rx1,rz1), (rx2,rz2)),
        "doors": list of DoorEdge dicts,
        "start": (rx, rz),
        "exit": (rx, rz),
        "start_exit_path_exists": bool,
        "width": int,
        "depth": int,
    }
    """
    import random as _random
    rng = _random.Random(seed)

    rooms, all_edges = build_grid_rooms(width, depth, seed=seed)

    # Spanning tree (guaranteed connectivity)
    tree_edges = build_spanning_tree(all_edges, seed=seed)

    # Extra loop edges (remove any from tree, pick remaining randomly)
    remaining = sorted(all_edges - tree_edges)
    rng.shuffle(remaining)
    extra_edges: set[tuple[GridRoom, GridRoom]] = set(remaining[:extra_loop_edges])

    # Default start = (0, 0), exit = opposite corner
    if start is None:
        start = (0, 0)
    if exit_room is None:
        exit_room = (width - 1, depth - 1)

    # Build doors
    doors = build_doors(
        tree_edges,
        extra_edges=extra_edges,
        lock_probability=lock_probability,
        seed=seed,
    )

    path_ok = validate_start_exit_path(rooms, tree_edges, start, exit_room)

    return {
        "rooms": rooms,
        "tree_edges": tree_edges,
        "extra_edges": extra_edges,
        "doors": doors,
        "start": start,
        "exit": exit_room,
        "start_exit_path_exists": path_ok,
        "width": width,
        "depth": depth,
    }


# ── Door position helper (where on the wall the door entity sits) ─

def door_position_on_wall(
    from_room: GridRoom,
    to_room: GridRoom,
    room_width: float = 20.0,
    room_depth: float = 20.0,
) -> tuple[float, float, float, float]:
    """Compute the (x, y, z, yaw) position of a door on the wall between two rooms.

    The door sits on the wall of *from_room* that faces *to_room*,
    centred on that wall.  y=0 (floor level).  yaw faces into the room.

    Returns (x, y, z, yaw_radians).
    """
    wall = _wall_between(from_room, to_room)
    rx, rz = from_room

    # Room centre in world space (rooms are room_width × room_depth)
    cx = rx * room_width
    cz = rz * room_depth

    hw = room_width / 2.0
    hd = room_depth / 2.0

    if wall == "east":
        return (cx + hw, 0.0, cz, 1.5708)      # door on right wall, facing east
    elif wall == "west":
        return (cx - hw, 0.0, cz, -1.5708)     # door on left wall, facing west
    elif wall == "north":
        return (cx, 0.0, cz - hd, 0.0)         # door on north wall, facing north
    else:  # south
        return (cx, 0.0, cz + hd, 3.14159)     # door on south wall, facing south


def get_doors_for_room(
    room: GridRoom,
    doors: list[DoorEdge],
) -> list[DoorEdge]:
    """Return all door edges connected to *room*."""
    result: list[DoorEdge] = []
    rx, rz = room
    for door in doors:
        fr, to = door["from_room"], door["to_room"]
        if (fr[0] == rx and fr[1] == rz) or (to[0] == rx and to[1] == rz):
            result.append(door)
    return result
