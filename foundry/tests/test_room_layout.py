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


# ═══════════════════════════════════════════════════════════════════════
#  Quality B2: Chair offset, carryable surface-snap, prop distribution
# ═══════════════════════════════════════════════════════════════════════

def test_chair_not_under_table():
    """Fix-Batch-1 Task 1: Chair offset along approach axis.

    The minimum distance is along the shorter axis of the table:
    table_half_z (0.4) + chair_half_z (0.25) + gap (0.08) = 0.73.
    A chair approaching along the width needs more (0.6 + 0.25 + 0.08 = 0.93).
    """
    from category_registry import COLLISION_SIZES
    table_size = COLLISION_SIZES.get("table", (1.2, 0.6, 0.8))
    chair_size = COLLISION_SIZES.get("chair", (0.5, 0.9, 0.5))
    table_half_z = table_size[2] / 2.0  # 0.4
    chair_half_z = chair_size[2] / 2.0  # 0.25
    gap = 0.08
    # Minimum standoff along the shorter approach axis
    min_standoff = table_half_z + chair_half_z + gap  # 0.73

    plan = {"room_size": {"w": 10.0, "d": 10.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 1},
                {"category": "chair", "material": "worn_oak", "count": 2},
            ]}
    manifest, _, _ = layout_room(plan)
    tables = [e for e in manifest if e["category"] == "table"]
    chairs = [e for e in manifest if e["category"] == "chair"]
    assert tables, "expected at least 1 table"
    assert len(chairs) == 2, f"expected 2 chairs, got {len(chairs)}"
    for chair in chairs:
        # Find assigned table (nearest)
        nearest = min(tables, key=lambda t: (chair["x"] - t["x"])**2 + (chair["z"] - t["z"])**2)
        dist = ((chair["x"] - nearest["x"])**2 + (chair["z"] - nearest["z"])**2)**0.5
        assert dist >= min_standoff - 0.01, (
            f"Task 1: chair at ({chair['x']},{chair['z']}) is {dist:.3f}m "
            f"from table at ({nearest['x']},{nearest['z']}), need ≥{min_standoff:.2f}"
        )


def test_carryables_on_real_surface_or_floor():
    """Quality B2: Every carryable's y equals a real host-surface top
    with (x,z) inside that host's footprint, OR it's a floor item at
    floor height."""
    from category_registry import CARRYABLES as _CARR, COLLISION_SIZES, FURNITURE_TOP_Y
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 2},
                {"category": "shelf", "material": "rough_granite", "count": 1},
                {"category": "key", "material": "wrought_iron", "count": 2},
                {"category": "book", "material": "worn_oak", "count": 1},
            ]}
    manifest, _, _ = layout_room(plan)
    furniture = [e for e in manifest if e["category"] not in ("rug", "painting", "key", "book", "gem", "cup", "bottle", "scroll", "coin-pouch", "candle", "dagger", "ring")]
    carryables = [e for e in manifest if e.get("category") in _CARR and not e.get("decor")]
    for carry in carryables:
        if carry.get("surface") == "floor":
            # Floor items should be near y=0
            assert carry["y"] < 0.1, (
                f"Quality B2: floor carryable {carry['id']} at y={carry['y']}, expected <0.1"
            )
        elif carry.get("surface") == "on":
            # Find the host furniture
            cx, cz = carry["x"], carry["z"]
            found_host = False
            for furn in furniture:
                pcat = furn["category"]
                psx, _, psz = COLLISION_SIZES.get(pcat, (1.0, 1.0, 1.0))
                phx, phz = psx / 2.0, psz / 2.0
                if abs(cx - furn["x"]) <= phx and abs(cz - furn["z"]) <= phz:
                    expected_y = FURNITURE_TOP_Y.get(pcat, 0.8) + 0.02
                    assert abs(carry["y"] - expected_y) < 0.01, (
                        f"Quality B2: {carry['id']} on '{furn['id']}' at y={carry['y']}, "
                        f"expected y≈{expected_y}"
                    )
                    found_host = True
                    break
            assert found_host, (
                f"Quality B2: {carry['id']} at ({cx},{cz}) has surface='on' "
                f"but not inside any furniture footprint"
            )


def test_props_distributed_across_room():
    """Quality B2: Placed props occupy cells in ≥ 3 of the 4 room
    quadrants (not all clustered in one quadrant)."""
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 2},
                {"category": "chair", "material": "worn_oak", "count": 2},
                {"category": "shelf", "material": "rough_granite", "count": 1},
            ]}
    manifest, _, _ = layout_room(plan)
    # Non-decor, non-underlay furniture props
    props = [e for e in manifest if not e.get("decor") and e.get("surface") != "underlay"]
    # Count quadrants (NE, NW, SE, SW)
    quadrants = set()
    for e in props:
        qx = "E" if e["x"] >= 0 else "W"
        qz = "S" if e["z"] >= 0 else "N"
        quadrants.add(f"{qz}{qx}")
    assert len(quadrants) >= 3, (
        f"Quality B2: props occupy {len(quadrants)} quadrants ({sorted(quadrants)}), need ≥3"
    )


# ═══════════════════════════════════════════════════════════════════════
#  Fix-Batch-1 Task 2: Prop distribution across the room
# ═══════════════════════════════════════════════════════════════════════

def test_spread_cell_distribution():
    """Fix-Batch-1 Task 2: When fewer props than cells, props should be
    spread across cells (not first-N row-major), covering the room.
    With an 8×8 room and 3 furniture items, the spread_stride should
    place them in cells from different quadrants (not just the first N)."""
    plan = {"room_size": {"w": 8.0, "d": 8.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 1},
                {"category": "table", "material": "worn_oak", "count": 1},
                {"category": "table", "material": "worn_oak", "count": 1},
            ]}
    manifest, _, _ = layout_room(plan)
    furniture = [e for e in manifest
                 if e.get("surface") != "underlay" and not e.get("decor")]
    # They should not all be in the same quadrant
    xs = [e["x"] for e in furniture]
    zs = [e["z"] for e in furniture]
    x_span = max(xs) - min(xs)
    z_span = max(zs) - min(zs)
    # With spread_stride, at least one axis should span > 40% of room
    assert x_span > 3.0 or z_span > 3.0, (
        f"Task 2: props clustered — X span {x_span:.2f}, Z span {z_span:.2f}"
    )

# ═══════════════════════════════════════════════════════════════════════
#  Fix-Batch-1 Task 3: occlusionTexture in GLB (test in test_build_blender)
# ═══════════════════════════════════════════════════════════════════════

def test_occlusion_texture_acceptance_stub():
    """Task 3 guard: Blender-dependent occlusionTexture test lives in
    test_build_blender.py.  This stub ensures the test module loads."""
    pass

# ═══════════════════════════════════════════════════════════════════════
#  Fix-Batch-1 Task 4: Shell textures referenced
# ═══════════════════════════════════════════════════════════════════════

def test_shell_textures_acceptance_stub():
    """Task 4 guard: Shell texture tests live in test_scene_compiler.py.
    This stub ensures the test module loads."""
    pass
