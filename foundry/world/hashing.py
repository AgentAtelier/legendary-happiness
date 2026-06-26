"""World content addressing (sub-project a, unit 1).

Two content addresses:

* ``world_state_hash`` — the WHOLE world.
    ``sha256(canonical_json(world.op_log))``
    The world is the fold of an op_log; the log IS the truth.

* ``node_content_hash`` — ONE space.
    ``sha256(canonical_json({brief, seed, gen_version, entities, portals}))``
    Used for per-node regen caching (unit 3) AND for the W1 LOCALITY
    tests: a move_entity in A must not change the content hash of B.

Both rely on ``canonical_json`` — a JSON serializer with sorted keys,
no whitespace, and Python's stock ``float.__repr__`` (round-trip stable
in Python 3.1+).  Because ``canonical_json`` is sort-key-stable, two
processes with the same op_log produce identical bytes, which is what
makes cross-process determinism hold.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from world.model import SpaceNode, World


# ── canonical_json ───────────────────────────────────────────────────


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, deterministic float repr.

    The float repr is whatever Python's stock ``json.dumps`` emits, which
    uses ``float.__repr__`` (round-trip stable in Python 3.1+).  For two
    processes running the same Python interpreter this is byte-exact;
    for cross-version determinism we lean on Python's published
    ``float.__repr__`` contract.

    Tuples become JSON arrays — element order preserved.  Sets are NOT
    supported (deliberately: there must be no place in the hashing path
    that emits unordered data).
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        check_circular=False,
        allow_nan=False,
        ensure_ascii=False,
    )


# ── World content hash ──────────────────────────────────────────────


def world_state_hash(world: World) -> str:
    """Content address of the WHOLE world.

    SHA-256 over ``canonical_json(world.op_log)``.  The world IS the
    fold of its op_log — so hashing the log hashes the world.  Any new
    operation changes the hash.
    """
    canon = canonical_json(world.op_log)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ── Node content hash ───────────────────────────────────────────────


def node_content_hash(node: SpaceNode) -> str:
    """Content address of ONE space, independent of its id.

    The id is a stable *handle*, not a content input — two spaces with
    identical (brief, seed, gen_version, entities, portals) hash equal
    (so external systems can dedupe content).  Changing any of those
    inputs changes the hash.
    """
    payload: dict[str, Any] = {
        "brief": node.brief,
        "seed": node.seed,
        "gen_version": node.gen_version,
        "entities": [
            {
                "id": e.id,
                "type": e.type,
                "pos": list(e.pos),
                "properties": e.properties,
            }
            for e in node.entities
        ],
        "portals": list(node.portals),
    }
    canon = canonical_json(payload)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
