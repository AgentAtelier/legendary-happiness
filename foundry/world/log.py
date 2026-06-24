"""Append-only event log for the world model.

Each accepted change is one JSONL event.  ``replay(log_path)`` folds
over all events to reconstruct the current ``World`` state.
``snapshot`` persists the full state (convenience for restore).
"""

from __future__ import annotations

import json
from pathlib import Path

from world.model import Intent, Placement, World, propose

# ── Public API ────────────────────────────────────────────────────────


def append_event(log_path: str, intent: Intent):
    """Append one accepted intent as a JSONL event."""
    event = {
        "action": intent.action,
        "placement": {
            "id": intent.placement.id,
            "asset_hash": intent.placement.asset_hash,
            "attrs": intent.placement.attrs,
        },
    }
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def replay(log_path: str) -> World:
    """Reconstruct the World by folding over all events in *log_path*.

    Returns an empty World if the log doesn't exist."""
    world = World()
    if not Path(log_path).exists():
        return world

    for raw in Path(log_path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        event = json.loads(line)
        placement = Placement(
            id=event["placement"]["id"],
            asset_hash=event["placement"]["asset_hash"],
            attrs=event["placement"].get("attrs", {}),
        )
        intent = Intent(action=event["action"], placement=placement)

        result = propose(world, intent)
        if result.accepted:
            world = result.world
        # Ignore rejected events during replay — they shouldn't be in
        # the log, but be defensive.

    return world


def snapshot(world: World, path: str):
    """Write the full world state as a JSON snapshot (for restore)."""
    data = {
        "placements": [
            {
                "id": p.id,
                "asset_hash": p.asset_hash,
                "attrs": p.attrs,
            }
            for p in world.placements
        ]
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def restore(path: str) -> World:
    """Restore a World from a snapshot file.

    Returns an empty World if the file doesn't exist."""
    if not Path(path).exists():
        return World()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    world = World()
    for p in data.get("placements", []):
        world.placements.append(
            Placement(
                id=p["id"],
                asset_hash=p["asset_hash"],
                attrs=p.get("attrs", {}),
            )
        )
    return world
