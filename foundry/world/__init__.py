"""foundry.world — world-model slice 1 (coherence foundation, Prompt 8).

A deterministic, validate-before-commit world model with an append-only
event log.  STANDALONE — not wired into the live pipeline yet.

Key concepts:
  - ``Placement``: an asset placed in the world (id, asset_hash, attrs).
  - ``World``: an ordered list of Placements.
  - ``Intent``: a WHOLE small object (add or replace one placement).
  - ``propose(world, intent)``: validate → accept or reject with Decision Points.
  - Event log: JSONL, replay via ``replay(path) -> World``.
  - Geometry NEVER stored — referenced by asset_hash only.
"""

from world.model import Intent, Placement, ProposeResult, World
from world.invariants import check_invariants
from world.log import append_event, replay, restore, snapshot

__all__ = [
    "Placement", "World", "Intent", "ProposeResult",
    "check_invariants", "append_event", "replay", "restore", "snapshot",
]
