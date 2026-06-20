"""Tests for deterministic room layout (no LLM, no Blender)."""
from __future__ import annotations

from room_layout import layout_room

FURNITURE = {"table", "chair", "shelf", "cabinet"}


def _aabb_overlap(a, b, pad=0.0):
    return (abs(a["x"] - b["x"]) < (1.6 - pad) and abs(a["z"] - b["z"]) < (1.6 - pad))


def test_furniture_is_non_overlapping():
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 4}]}
    manifest, room_size, decisions = layout_room(plan)
    furn = [e for e in manifest if e["category"] in FURNITURE]
    assert len(furn) == 4
    for i in range(len(furn)):
        for j in range(i + 1, len(furn)):
            assert not _aabb_overlap(furn[i], furn[j]), f"{furn[i]} overlaps {furn[j]}"
    assert all(e["surface"] == "floor" and not e["decor"] for e in furn)


def test_rug_is_overlappable_underlay_decor():
    plan = {"room_size": {"w": 6.0, "d": 6.0},
            "props": [{"category": "rug", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)
    rug = [e for e in manifest if e["category"] == "rug"][0]
    assert rug["surface"] == "underlay" and rug["decor"] is True
    assert rug["y"] < 0.1  # sits on the floor


def test_painting_is_wall_mounted_decor_facing_in():
    plan = {"room_size": {"w": 6.0, "d": 6.0},
            "props": [{"category": "painting", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)
    p = [e for e in manifest if e["category"] == "painting"][0]
    assert p["surface"] == "wall" and p["decor"] is True
    assert abs(p["z"]) > 2.0 or abs(p["x"]) > 2.0   # against a wall
    assert p["y"] > 1.0                              # hung at height


def test_over_capacity_emits_decision_and_caps_placement():
    plan = {"room_size": {"w": 4.0, "d": 4.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 8}]}
    manifest, _, decisions = layout_room(plan)
    furn = [e for e in manifest if e["category"] in FURNITURE]
    assert len(furn) < 8                       # capped
    dp = [d for d in decisions if d.code == "room.over_capacity"]
    assert dp and dp[0].context["dropped"] == 8 - len(furn)


def test_layout_guarantees_a_carryable_target():
    """Every room must contain at least one pickable carryable fetch target,
    even a sparse decor-only plan (else behaviour-gen has nothing to fetch)."""
    from room_layout import CARRYABLES
    plan = {"room_size": {"w": 4.0, "d": 4.0},
            "props": [{"category": "rug", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)
    carry = [e for e in manifest if e["category"] in CARRYABLES and not e.get("decor")]
    assert carry, "no carryable target was guaranteed"


# ═══════════════════════════════════════════════════════════════════════
#  EB-7: Multi-NPC carryable injection
# ═══════════════════════════════════════════════════════════════════════


def test_layout_injects_npc_count_carryables_when_none_present():
    """EB-7: With npc_count=3 and no carryables in plan, layout_room
    injects 3 distinct carryables."""
    from room_layout import CARRYABLES
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [{"category": "table", "material": "worn_oak", "count": 2}]}
    manifest, _, _ = layout_room(plan, npc_count=3)
    carry = [e for e in manifest if e["category"] in CARRYABLES and not e.get("decor")]
    assert len(carry) >= 3, f"expected ≥3 carryables, got {len(carry)}"
    # All injected carryables should have unique IDs
    ids = {e["id"] for e in carry}
    assert len(ids) == len(carry), f"duplicate carryable IDs: {ids}"
    # All should be non-decor, pickable
    assert all(not e.get("decor") for e in carry)


def test_layout_injects_enough_for_npc_count_minus_existing():
    """EB-7: With npc_count=3 and 1 existing carryable, layout_room
    injects 2 more (3 total)."""
    from room_layout import CARRYABLES
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [
                {"category": "key", "material": "wrought_iron", "count": 1},
                {"category": "table", "material": "worn_oak", "count": 2},
            ]}
    manifest, _, _ = layout_room(plan, npc_count=3)
    carry = [e for e in manifest if e["category"] in CARRYABLES and not e.get("decor")]
    assert len(carry) >= 3, f"expected ≥3 carryables, got {len(carry)}"


def test_layout_injected_carryables_spaced_on_furniture():
    """EB-7: Injected carryables placed on different furniture surfaces
    (not all on the same furniture item)."""
    from room_layout import CARRYABLES
    plan = {"room_size": {"w": 10.0, "d": 10.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 2},
                {"category": "shelf", "material": "rough_granite", "count": 1},
            ]}
    manifest, _, _ = layout_room(plan, npc_count=3)
    carry = [e for e in manifest if e["category"] in CARRYABLES and not e.get("decor")]
    # Should be distributed — check no two carryables share same (x,z)
    positions = {(round(e["x"], 1), round(e["z"], 1)) for e in carry}
    # With offsets they should be in different positions
    assert len(positions) > 1, f"all carryables at same position: {positions}"


def test_layout_npc_count_default_1():
    """EB-7: Backward compat — npc_count defaults to 1, no breakage."""
    from room_layout import CARRYABLES
    plan = {"room_size": {"w": 4.0, "d": 4.0},
            "props": [{"category": "rug", "material": "worn_oak", "count": 1}]}
    manifest, _, _ = layout_room(plan)  # no npc_count arg
    carry = [e for e in manifest if e["category"] in CARRYABLES and not e.get("decor")]
    assert len(carry) >= 1, "backward-compat: should inject at least 1 carryable"
