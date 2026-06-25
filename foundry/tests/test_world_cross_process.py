"""TDD tests for cross-process determinism — Spec line:

  world_state_hash identical across two separate subprocesses with
  PYTHONHASHSEED=0 vs 42 (mirror the existing cross-process determinism
  tests in the repo).

Why this matters: The world is the fold of an op_log; world_state_hash
is sha256(canonical_json(op_log)). For the hash to be cross-process
stable, ``canonical_json`` MUST be sort-key-stable AND the op_log
construction MUST NOT depend on per-process hash-randomized state.

If a future code-path adds a ``set`` to the hashing path (or iterates a
dict without sort_keys=True), this test catches it instantly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from world.hashing import world_state_hash
from world.operations import replay


# ── Subprocess script builder ────────────────────────────────────────

# Build a small op_log + replay + hash, then print the hash. Runs in a
# subprocess with a chosen PYTHONHASHSEED. Two runs with different seeds
# MUST produce the same hash (cross-process determinism invariant).

_OPS = [
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
                  "pos": [0, 0, 1],
                  "properties": {"wood": "oak", "carved": True}}},
    {"op": "move_entity", "space": "hall",
      "entity_id": "throne_0", "new_pos": [2, 0, 2]},
    {"op": "set_property", "target_kind": "entity",
      "space": "hall", "entity_id": "throne_0",
      "path": ["wear"], "value": 0.8},
]


def _sub_script_replay_hash(ops):
    """Return a python -c script that loads ops from a repr-literal and
    prints ``world_state_hash(replay(ops))``.  Mirrors test_lighting_bake's
    cross-process pattern so the technique stays consistent.
    """
    import pprint
    ops_repr = pprint.pformat(ops, sort_dicts=True, width=120)
    body = (
        "import sys; sys.path.insert(0, 'foundry'); "
        "from world.operations import replay; "
        "from world.hashing import world_state_hash; "
        f"ops = {ops_repr}; "
        "print(world_state_hash(replay(ops)))"
    )
    return body


# ── Cross-process determinism ───────────────────────────────────────


@pytest.mark.parametrize("seed_a,seed_b", [("0", "42")])
def test_world_state_hash_cross_process(tmp_path, seed_a, seed_b):
    """world_state_hash must match across subprocesses that have
    different PYTHONHASHSEED — the gold-standard determinism check."""
    proj_root = str(Path(__file__).resolve().parent.parent.parent)
    code = _sub_script_replay_hash(_OPS)

    env_a = {**os.environ, "PYTHONHASHSEED": seed_a}
    env_b = {**os.environ, "PYTHONHASHSEED": seed_b}

    r_a = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=15,
        cwd=proj_root, env=env_a,
    )
    r_b = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=15,
        cwd=proj_root, env=env_b,
    )
    assert r_a.returncode == 0, f"subprocess A failed: {r_a.stderr}"
    assert r_b.returncode == 0, f"subprocess B failed: {r_b.stderr}"
    hash_a = r_a.stdout.strip()
    hash_b = r_b.stdout.strip()
    assert hash_a == hash_b, (
        f"world_state_hash is NOT PYTHONHASHSEED-independent: "
        f"seed={seed_a} → {hash_a[:16]}... vs seed={seed_b} → {hash_b[:16]}..."
    )


def test_same_process_two_calls_match():
    """Sanity: within one Python process the hash is stable between two
    calls.  Pairs with the cross-process test to distinguish 'hash
    function buggy' (this test would catch it) from 'process state
    leaks into the hash' (only the cross-process test catches that)."""
    expected = world_state_hash(replay(_OPS))
    for _ in range(3):
        assert world_state_hash(replay(_OPS)) == expected
