"""World persistence (sub-project a, unit 1).

Two files per world directory:

  op_log.json    — authoritative; replayed on load to rebuild World.
  snapshot.json  — materialized; human inspection + diff-friendly.

The op_log is the truth.  Snapshot is a convenience for humans and for
tests that want to inspect state without running replay.

Format notes
------------

* op_log.json: ``json.dumps(op_log, indent=2, sort_keys=True)`` — alpha-
  sorted keys are visually stable in diffs.
* snapshot.json: a JSON-friendly view of the materialized state
  (``world_to_snapshot``); also ``indent=2, sort_keys=True``.

For determinism, the HASH is computed over the in-memory ``World.op_log``,
NOT over the on-disk bytes.  So a process can save → load → compute hash,
and the hash will equal the hash from the in-memory world (as long as
JSON loads are exact).

``load_world`` always replays op_log.json (never the snapshot) so a
hostile or corrupted snapshot doesn't desync the world.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from world.model import World

from world.operations import replay

# ── Snapshot view ───────────────────────────────────────────────────


def world_to_snapshot(world: World) -> dict[str, Any]:
    """JSON-friendly view of the materialized world.

    Tuples become lists (structural JSON), dataclasses become dicts.
    Used by ``save_world`` to write ``snapshot.json`` AND can be used by
    callers that want a dict view (for inspection, for plotting, etc.).
    """
    return {
        "nodes": {
            sid: {
                "id": n.id,
                "seed": n.seed,
                "brief": n.brief,
                "footprint": n.footprint,
                "entities": [
                    {
                        "id": e.id,
                        "type": e.type,
                        "pos": list(e.pos),
                        "properties": e.properties,
                    }
                    for e in n.entities
                ],
                "portals": list(n.portals),
                "gen_version": n.gen_version,
            }
            for sid, n in world.nodes.items()
        },
        "portals": {
            pid: {
                "id": p.id,
                "from_space": p.from_space,
                "to_space": p.to_space,
                "position": list(p.position),
                "size": list(p.size),
            }
            for pid, p in world.portals.items()
        },
        "op_log": world.op_log,
        "world_bible": world.world_bible,
    }


# ── Save ────────────────────────────────────────────────────────────


def save_world(world: World, dir_path: str | Path) -> None:
    """Write op_log.json (authoritative) + snapshot.json (convenience).

    Creates ``dir_path`` (and any missing parents) if necessary.
    """
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)

    # op_log.json is the truth — writes op_log only.
    (d / "op_log.json").write_text(
        json.dumps(world.op_log, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # snapshot.json is materialized for inspection.
    (d / "snapshot.json").write_text(
        json.dumps(world_to_snapshot(world), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ── Load ────────────────────────────────────────────────────────────


def load_world(dir_path: str | Path) -> World:
    """Load a World by REPLAYING op_log.json.  Raises FileNotFoundError if
    the directory or op_log.json is missing — never silently returns empty.
    """
    d = Path(dir_path)
    op_log_path = d / "op_log.json"
    if not op_log_path.exists():
        raise FileNotFoundError(f"op_log.json missing in {d}")
    raw = op_log_path.read_text(encoding="utf-8")
    ops = json.loads(raw)
    if not isinstance(ops, list):
        raise ValueError(
            f"op_log.json must be a JSON list, got {type(ops).__name__}"
        )
    return replay(ops)
