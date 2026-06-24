"""TDD tests for foundry.world — world-model slice 1 (Prompt 8).

Tests cover:
  - Valid add → one event appended, yields new state
  - Referential-integrity violation → DecisionPoint, NO event
  - Budget violation → DecisionPoint
  - Replace existing placement works
  - Replay(log) reconstructs the same state
  - Determinism
  - Snapshot/restore round-trip
  - HARD vs SOFT invariant separation
"""

from __future__ import annotations

from world.log import append_event, replay, restore, snapshot
from world.model import Intent, Placement, World, propose

# ── Helpers ───────────────────────────────────────────────────────────


def _make_placement(id: str, material: str = "worn_oak", zone: str = "room1",
                    asset_hash: str = "abc123") -> Placement:
    return Placement(
        id=id,
        asset_hash=asset_hash,
        attrs={"material": material, "zone": zone},
    )


# ── Valid add ─────────────────────────────────────────────────────────


def test_valid_add_returns_accepted():
    """A valid add → accepted=True, new World with the placement."""
    world = World()
    intent = Intent(action="add", placement=_make_placement("table1"))

    result = propose(world, intent)
    assert result.accepted
    assert len(result.world.placements) == 1
    assert result.world.placements[0].id == "table1"


def test_valid_add_does_not_modify_original_world():
    """propose works on a staged copy — original is unchanged on accept."""
    world = World()
    original_ids = [p.id for p in world.placements]
    intent = Intent(action="add", placement=_make_placement("table1"))

    result = propose(world, intent)
    assert result.accepted
    # Original world unchanged
    assert [p.id for p in world.placements] == original_ids
    # Result world has the new placement
    assert len(result.world.placements) == 1


def test_multiple_adds_are_ordered():
    """Multiple adds preserve insertion order."""
    world = World()
    for i in range(5):
        result = propose(world, Intent(
            action="add", placement=_make_placement(f"item{i}", zone="room1")
        ))
        assert result.accepted
        world = result.world
    assert len(world.placements) == 5
    assert [p.id for p in world.placements] == [f"item{i}" for i in range(5)]


# ── Replace ───────────────────────────────────────────────────────────


def test_replace_existing_updates_placement():
    """Replace an existing placement by id."""
    world = World(placements=[_make_placement("table1", material="worn_oak")])

    replacement = _make_placement("table1", material="wrought_iron")
    intent = Intent(action="replace", placement=replacement)

    result = propose(world, intent)
    assert result.accepted
    assert len(result.world.placements) == 1
    assert result.world.placements[0].attrs["material"] == "wrought_iron"


def test_replace_nonexistent_adds_instead():
    """Replacing a placement not in the world → adds it (idempotent)."""
    world = World()
    intent = Intent(action="replace", placement=_make_placement("ghost"))

    result = propose(world, intent)
    assert result.accepted
    assert len(result.world.placements) == 1


# ── Referential-integrity violation (HARD) ────────────────────────────


def test_unknown_material_rejects():
    """A placement with a material not in the palette → reject + DecisionPoint."""
    world = World()
    placement = _make_placement("bad1", material="unobtanium")
    intent = Intent(action="add", placement=placement)

    result = propose(world, intent)
    assert not result.accepted
    # Original world unchanged
    assert result.world is world
    # DecisionPoint emitted
    assert len(result.decisions) >= 1
    dp = result.decisions[0]
    assert dp.severity == "error"
    assert "unobtanium" in dp.technical


def test_referential_integrity_rejection_no_event():
    """A rejected intent does NOT add a placement — world is unmodified."""
    world = World()
    intent = Intent(action="add", placement=_make_placement("bad1", material="glitter"))

    result = propose(world, intent)
    assert not result.accepted
    assert len(result.world.placements) == 0


# ── Budget violation (HARD) ───────────────────────────────────────────


def test_zone_budget_exceeded_rejects():
    """Exceeding max_per_zone → reject + DecisionPoint."""
    world = World()
    # Fill zone to exactly the budget
    for i in range(5):
        result = propose(
            world,
            Intent(action="add", placement=_make_placement(f"item{i}", zone="small_zone")),
            max_per_zone=5,
        )
        assert result.accepted
        world = result.world

    # Zone is now at 5 (at budget). Try to add one more.
    result = propose(
        world,
        Intent(action="add", placement=_make_placement("item5", zone="small_zone")),
        max_per_zone=5,
    )
    assert not result.accepted
    assert any(d.code == "world.zone_budget_exceeded" for d in result.decisions)


def test_zone_budget_not_exceeded_accepts():
    """Within budget → accepted."""
    world = World()
    for i in range(3):
        result = propose(
            world,
            Intent(action="add", placement=_make_placement(f"item{i}")),
            max_per_zone=5,
        )
        assert result.accepted
        world = result.world  # accumulate

    assert len(world.placements) == 3


# ── SOFT invariant (material monoculture) ─────────────────────────────


def test_material_monoculture_emits_info_decision():
    """All placements in a zone share the same material → SOFT (info)
    DecisionPoint, but proposal is still accepted."""
    world = World()
    for i in range(3):
        result = propose(
            world,
            Intent(action="add", placement=_make_placement(f"item{i}", material="worn_oak", zone="mono")),
        )
        assert result.accepted
        world = result.world

    # All 3 in "mono" share worn_oak → monoculture warning, but accepted
    assert result.accepted
    assert any(d.code == "world.material_monoculture" for d in result.decisions)
    assert all(d.severity == "info" for d in result.decisions)


# ── Event log + replay ────────────────────────────────────────────────


def test_replay_reconstructs_world(tmp_path):
    """replay(log) on an event log reconstructs the same World state."""
    log_path = tmp_path / "events.jsonl"

    # Build a world step by step, recording events
    world = World()
    for i in range(5):
        intent = Intent(action="add", placement=_make_placement(f"item{i}"))
        result = propose(world, intent)
        assert result.accepted
        world = result.world
        append_event(str(log_path), intent)

    # Replay
    replayed = replay(str(log_path))
    assert len(replayed.placements) == 5
    for a, b in zip(world.placements, replayed.placements):
        assert a.id == b.id
        assert a.asset_hash == b.asset_hash
        assert a.attrs == b.attrs


def test_replay_empty_log_returns_empty_world(tmp_path):
    """replay on a non-existent log → empty World."""
    w = replay("/tmp/no_such_log.jsonl")
    assert isinstance(w, World)
    assert w.placements == []


# ── Snapshot / restore ────────────────────────────────────────────────


def test_snapshot_restore_round_trip(tmp_path):
    """snapshot + restore preserves world state."""
    snap_path = tmp_path / "world.json"

    world = World()
    for i in range(3):
        result = propose(world, Intent(
            action="add", placement=_make_placement(f"item{i}", zone="test")
        ))
        assert result.accepted
        world = result.world

    snapshot(world, str(snap_path))
    restored = restore(str(snap_path))

    assert len(restored.placements) == 3
    for a, b in zip(world.placements, restored.placements):
        assert a.id == b.id
        assert a.asset_hash == b.asset_hash
        assert a.attrs == b.attrs


def test_restore_missing_file_returns_empty_world(tmp_path):
    """restore on a missing file → empty World."""
    w = restore(str(tmp_path / "nonexistent.json"))
    assert len(w.placements) == 0


# ── Determinism ───────────────────────────────────────────────────────


def test_propose_deterministic():
    """Same input → same output."""
    result1 = propose(World(), Intent(action="add", placement=_make_placement("t1")))
    result2 = propose(World(), Intent(action="add", placement=_make_placement("t1")))

    assert result1.accepted == result2.accepted
    assert result1.world.placements == result2.world.placements


def test_replay_deterministic(tmp_path):
    """Replaying the same log twice produces the same World."""
    log_path = tmp_path / "events.jsonl"

    for i in range(3):
        world = World()
        result = propose(world, Intent(
            action="add", placement=_make_placement(f"item{i}")
        ))
        assert result.accepted
        append_event(str(log_path), Intent(
            action="add", placement=_make_placement(f"item{i}")
        ))

    w1 = replay(str(log_path))
    w2 = replay(str(log_path))
    assert [p.id for p in w1.placements] == [p.id for p in w2.placements]


# ── Unknown action ────────────────────────────────────────────────────


def test_unknown_action_rejects():
    """An intent with an unknown action → reject."""
    world = World()
    intent = Intent(action="delete", placement=_make_placement("t1"))

    result = propose(world, intent)
    assert not result.accepted
    assert any(d.code == "world.unknown_action" for d in result.decisions)


# ── HARD vs SOFT separation ───────────────────────────────────────────


def test_hard_error_blocks_soft_ignored():
    """When a HARD invariant fires, only HARD decisions are returned
    (SOFT are invisible on rejection)."""
    world = World()
    # Add a placement with unknown material → HARD error
    placement = _make_placement("bad", material="vibranium")
    intent = Intent(action="add", placement=placement)

    result = propose(world, intent)
    assert not result.accepted
    # Only HARD decisions returned
    for d in result.decisions:
        assert d.severity == "error"
    assert any(d.code == "world.referential_integrity" for d in result.decisions)
