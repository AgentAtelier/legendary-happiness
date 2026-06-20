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
