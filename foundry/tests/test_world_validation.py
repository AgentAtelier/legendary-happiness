"""Unit 2 — the W3 spatial validation gate.

Encodes the geometry contract: spaces tile without overlapping and connect
only on shared faces; entities stay inside their space.
"""
import pytest
from world.operations import WorldOpError, apply_op, replay
from world.validation import (
    Violation,
    WorldValidationError,
    aabb,
    adjacent,
    apply_op_checked,
    overlaps,
    point_in_aabb,
    validate_op,
)

# Footprints (x[0,4] y[0,3] z[0,4] etc.)
A = {"origin": [0, 0, 0], "size": [4, 3, 4]}        # x[0,4]
B_ADJ = {"origin": [4, 0, 0], "size": [4, 3, 4]}    # x[4,8] — touches A at x=4
C_OVER = {"origin": [2, 0, 2], "size": [4, 3, 4]}   # overlaps A
D_FAR = {"origin": [10, 0, 0], "size": [4, 3, 4]}   # separated from A


def _add(footprint, sid="a"):
    return {"op": "add_space", "id": sid, "brief": {}, "footprint": footprint}


def _world_with(*spaces):
    w = type(replay([]))()  # empty World
    for sid, fp in spaces:
        w = apply_op(w, _add(fp, sid))
    return w


# ── AABB helpers ──────────────────────────────────────────────────────

def test_aabb_malformed_returns_none():
    assert aabb({"origin": [0, 0], "size": [1, 1, 1]}) is None
    assert aabb({"origin": [0, 0, 0], "size": [1, 0, 1]}) is None  # zero size
    assert aabb({}) is None


def test_overlaps_and_touching():
    a, b, c = aabb(A), aabb(B_ADJ), aabb(C_OVER)
    assert overlaps(a, c) is True
    assert overlaps(a, b) is False   # only touching at x=4, not overlapping


def test_adjacent_only_when_sharing_a_face():
    a, b, c, d = aabb(A), aabb(B_ADJ), aabb(C_OVER), aabb(D_FAR)
    assert adjacent(a, b) is True    # share the x=4 face
    assert adjacent(a, c) is False   # overlapping, not face-adjacent
    assert adjacent(a, d) is False   # separated by a gap


def test_point_in_aabb():
    a = aabb(A)
    assert point_in_aabb((2, 1, 2), a) is True
    assert point_in_aabb((5, 1, 2), a) is False  # x=5 outside [0,4]


# ── add_space overlap (the headline "courtyard intersects armory") ─────

def test_add_space_non_overlapping_ok():
    w = _world_with(("a", A))
    assert validate_op(w, _add(B_ADJ, "b")) == []   # adjacent is fine
    assert validate_op(w, _add(D_FAR, "d")) == []    # far is fine


def test_add_space_overlap_rejected():
    w = _world_with(("a", A))
    vs = validate_op(w, _add(C_OVER, "c"))
    assert len(vs) == 1 and vs[0].code == "space.overlap"
    assert vs[0].details["conflicts_with"] == "a"


def test_add_space_touching_is_allowed():
    w = _world_with(("a", A))
    assert validate_op(w, _add(B_ADJ, "b")) == []   # touching != overlap


def test_add_space_malformed_footprint_rejected():
    w = _world_with()
    vs = validate_op(w, _add({"origin": [0, 0, 0], "size": [4, 0, 4]}, "bad"))
    assert len(vs) == 1 and vs[0].code == "space.bad_footprint"


# ── add_portal adjacency + boundary ────────────────────────────────────

def _portal(frm, to, position, pid="p"):
    return {"op": "add_portal", "id": pid, "from_space": frm, "to_space": to,
            "position": position, "size": [1.5, 2.0]}


def test_portal_between_adjacent_on_boundary_ok():
    w = _world_with(("a", A), ("b", B_ADJ))
    assert validate_op(w, _portal("a", "b", [4, 1.5, 2])) == []


def test_portal_between_non_adjacent_rejected():
    w = _world_with(("a", A), ("d", D_FAR))
    vs = validate_op(w, _portal("a", "d", [4, 1.5, 2]))
    assert len(vs) == 1 and vs[0].code == "portal.not_adjacent"


def test_portal_position_off_boundary_rejected():
    w = _world_with(("a", A), ("b", B_ADJ))
    # inside A but 2 m from B's surface → not on the shared boundary
    vs = validate_op(w, _portal("a", "b", [2, 1.5, 2]))
    assert len(vs) == 1 and vs[0].code == "portal.off_boundary"


def test_portal_missing_space_is_referential_not_spatial():
    w = _world_with(("a", A))
    # validate skips (returns []) — apply_op raises the referential error
    assert validate_op(w, _portal("a", "ghost", [4, 1.5, 2])) == []


# ── entity bounds ──────────────────────────────────────────────────────

def test_add_entity_in_bounds_ok():
    w = _world_with(("a", A))
    op = {"op": "add_entity", "space": "a",
          "entity": {"id": "throne", "type": "throne", "pos": [2, 0, 2]}}
    assert validate_op(w, op) == []


def test_add_entity_out_of_bounds_rejected():
    w = _world_with(("a", A))
    op = {"op": "add_entity", "space": "a",
          "entity": {"id": "throne", "type": "throne", "pos": [5, 0, 2]}}
    vs = validate_op(w, op)
    assert len(vs) == 1 and vs[0].code == "entity.out_of_bounds"


def test_move_entity_out_of_bounds_rejected():
    w = _world_with(("a", A))
    w = apply_op(w, {"op": "add_entity", "space": "a",
                     "entity": {"id": "t", "type": "throne", "pos": [2, 0, 2]}})
    vs = validate_op(w, {"op": "move_entity", "space": "a",
                         "entity_id": "t", "new_pos": [99, 0, 0]})
    assert len(vs) == 1 and vs[0].code == "entity.out_of_bounds"


# ── apply_op_checked (the gated entry point) ──────────────────────────

def test_apply_op_checked_valid_applies():
    w = _world_with(("a", A))
    w2 = apply_op_checked(w, _add(B_ADJ, "b"))
    assert "b" in w2.nodes and "b" not in w.nodes  # pure


def test_apply_op_checked_raises_with_violations():
    w = _world_with(("a", A))
    with pytest.raises(WorldValidationError) as exc:
        apply_op_checked(w, _add(C_OVER, "c"))
    assert exc.value.violations[0].code == "space.overlap"


def test_validation_error_is_a_world_op_error():
    """So `except WorldOpError` catches the spatial layer uniformly."""
    w = _world_with(("a", A))
    with pytest.raises(WorldOpError):
        apply_op_checked(w, _add(C_OVER, "c"))


def test_apply_op_checked_still_enforces_referential():
    w = _world_with(("a", A))
    with pytest.raises(WorldOpError):  # ghost space → referential error from apply_op
        apply_op_checked(w, _portal("a", "ghost", [4, 1.5, 2]))


# ── replay is NOT gated ───────────────────────────────────────────────

def test_replay_does_not_validate():
    """A log built via raw apply_op (e.g. with overlap) still replays —
    the gate only guards NEW ops via apply_op_checked."""
    w = apply_op(replay([]), _add(A, "a"))
    w = apply_op(w, _add(C_OVER, "c"))  # overlapping, but apply_op doesn't check
    w2 = replay(w.op_log)
    assert set(w2.nodes) == {"a", "c"}


def test_violation_is_a_dataclass():
    v = Violation("x.y", "msg", {"k": 1})
    assert v.code == "x.y" and v.details["k"] == 1
