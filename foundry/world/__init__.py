"""foundry.world — World model + operation log (sub-project a, unit 1).

The world is the FOLD of an append-only operation log. Operations are
authoritative; prompts (added later in unit b) are provenance only.

Public API:

  model       — Entity, Portal, SpaceNode, World, seed_from_id
  operations  — apply_op, replay, WorldOpError
  hashing     — canonical_json, world_state_hash, node_content_hash
  persistence — save_world, load_world, world_to_snapshot

See the prompt-of-record: docs/current/WORLD-ENGINE.md §4 + §6.
"""

from world.hashing import canonical_json, node_content_hash, world_state_hash
from world.model import (
    Entity,
    Portal,
    SpaceNode,
    World,
    seed_from_id,
)
from world.operations import WorldOpError, apply_op, replay
from world.persistence import load_world, save_world, world_to_snapshot

__all__ = [
    # model
    "Entity",
    "Portal",
    "SpaceNode",
    "World",
    "seed_from_id",
    # operations
    "WorldOpError",
    "apply_op",
    "replay",
    # hashing
    "canonical_json",
    "node_content_hash",
    "world_state_hash",
    # persistence
    "load_world",
    "save_world",
    "world_to_snapshot",
]
