"""foundry.placement — placement math for the scene compiler.

Extracted from scene_compiler.py (Phase 1.4).  Pure functions (no .tscn
strings): AABB separation, NPC open-floor placement, player spawn guard,
rest offset, prop half-extents.
"""

from __future__ import annotations

from typing import List, Tuple

from _constants import DEFAULT_RNG_SEED
from category_registry import COLLISION_SIZES

# ── Constants ─────────────────────────────────────────────────────

# Props within this radius of (0,0,0) on the XZ plane are pushed away
# from the player spawn (FIX-1e).
_PLAYER_CLEAR_RADIUS = 1.0

# Quality B1: min distance from NPC to prop/player/other NPC
_NPC_CLEARANCE = 0.6


# ── Public functions ──────────────────────────────────────────────

def _guard_player_spawn(x: float, z: float) -> tuple[float, float]:
    """If (x,z) is too close to the player spawn at (0,0), push it away.

    Returns (adjusted_x, adjusted_z).  Safe to call with default values.
    """
    dist = (x * x + z * z) ** 0.5
    if dist < _PLAYER_CLEAR_RADIUS:
        if dist < 0.001:
            return (_PLAYER_CLEAR_RADIUS, 0.0)
        scale = _PLAYER_CLEAR_RADIUS / dist
        return (x * scale, z * scale)
    return (x, z)


def _prop_half_extents(category: str) -> tuple[float, float, float]:
    """Return half-extents (hx, hy, hz) for a prop's AABB from its category."""
    sx, sy, sz = COLLISION_SIZES.get(category, COLLISION_SIZES["?"])
    return (sx / 2.0, sy / 2.0, sz / 2.0)


def rest_offset(aabb_min_y: float) -> float:
    """Y to add to a prop transform so its AABB base rests on the floor (y=0).
    Props whose origin is at their centre float without this offset."""
    return -float(aabb_min_y)


def _get_prop_footprints(
    manifest: list[dict], clearance: float = 0.0,
) -> list[tuple[float, float, float, float]]:
    """Collect (x, z, half_x + clearance, half_z + clearance) for each
    separable prop in the manifest.  Skips underlays and decor entries."""
    footprints: list[tuple[float, float, float, float]] = []
    for entry in manifest:
        if entry.get("surface") == "underlay" or entry.get("decor"):
            continue
        hx, _, hz = _prop_half_extents(entry.get("category", "?"))
        footprints.append((
            entry.get("x", 0.0), entry.get("z", 0.0),
            hx + clearance, hz + clearance,
        ))
    return footprints


def _find_open_npc_positions(
    quest_specs: list[dict],
    manifest: list[dict],
    room_w: float,
    room_d: float,
    seed: int = DEFAULT_RNG_SEED,
) -> list[tuple[float, float]]:
    """Quality B1: Find open-floor (x,z) positions for NPCs with clearance
    from prop footprints and player spawn (0,0).  Distributes NPCs across
    the room instead of clustering them on the back wall."""
    import random as _random
    _rng = _random.Random(seed)

    npc_hx, _, npc_hz = _prop_half_extents("humanoid")
    clearance = _NPC_CLEARANCE

    prop_footprints = _get_prop_footprints(manifest, clearance=clearance)

    def _overlaps(px: float, pz: float, ox: float, oz: float, ohx: float, ohz: float) -> bool:
        return abs(px - ox) < (npc_hx + ohx) and abs(pz - oz) < (npc_hz + ohz)

    def _valid_npc_spot(x: float, z: float, placed: list[tuple[float, float]]) -> bool:
        # Clear of player spawn
        if abs(x) < (_PLAYER_CLEAR_RADIUS + npc_hx) and abs(z) < (_PLAYER_CLEAR_RADIUS + npc_hz):
            return False
        # Clear of prop footprints
        for (px, pz, phx, phz) in prop_footprints:
            if _overlaps(x, z, px, pz, phx, phz):
                return False
        # Clear of other NPCs
        for (ox, oz) in placed:
            if _overlaps(x, z, ox, oz, npc_hx + clearance, npc_hz + clearance):
                return False
        return True

    n_npcs = len(quest_specs)
    positions: list[tuple[float, float]] = []

    # Try a set of candidate positions spread across the room
    half_w = room_w / 2.0 - 0.5
    half_d = room_d / 2.0 - 0.5
    # Generate candidates: spread across the room in a rough grid
    candidates: list[tuple[float, float]] = []
    for row in range(-2, 3):
        for col in range(-2, 3):
            x = col * half_w * 0.45
            z = row * half_d * 0.4
            candidates.append((x, z))
    _rng.shuffle(candidates)

    for _ in range(n_npcs):
        found = False
        for cx, cz in candidates:
            if (cx, cz) not in positions and _valid_npc_spot(cx, cz, positions):
                positions.append((cx, cz))
                found = True
                break
        if not found:
            # Fallback: place at back of room spread along X
            x = (_rng.random() * half_w * 1.5 - half_w * 0.75)
            z = -half_d + 0.8
            # Ensure not on top of another NPC
            attempts = 0
            while not _valid_npc_spot(x, z, positions) and attempts < 50:
                x = (_rng.random() * half_w * 1.5 - half_w * 0.75)
                z = -half_d + 0.8
                attempts += 1
            positions.append((x, z))

    return positions


def _resolve_prop_overlaps(
    manifest: List[dict],
    npc_x: float = 0.0,
    npc_z: float = -2.0,
    max_iterations: int = 20,
) -> List[dict]:
    """Deterministic AABB separation pass (Item 3).

    Pushes overlapping props apart so they don't intersect each other
    or the NPC.  Processes in sorted entity-id order for determinism.
    Uses axis-aligned bounding boxes from ``COLLISION_SIZES`` on the
    XZ plane (ignoring Y).

    Returns a **new** list of manifest entries with updated x,z
    positions.
    """
    # Work on a full copy — all entries returned, but only
    # separable entries (non-underlay, non-decor) participate in
    # collision checking.
    result: list[dict] = [dict(e) for e in manifest]

    # Indices of entries that participate in separation
    separable = [
        i for i, e in enumerate(result)
        if e.get("surface") != "underlay" and not e.get("decor")
    ]

    if len(separable) == 0:
        return result  # no separable props to check

    # NPC half-extents (humanoid)
    npc_hx, _, npc_hz = _prop_half_extents("humanoid")

    # Build list of (index, hx, hz) for quick lookup
    prop_data: list[Tuple[int, float, float]] = []
    for i, entry in enumerate(result):
        cat = entry.get("category", "?")
        hx, _, hz = _prop_half_extents(cat)
        prop_data.append((i, hx, hz))

    for _iteration in range(max_iterations):
        moved = False

        # Process only separable indices in sorted entity-id order
        separable_sorted = sorted(separable, key=lambda i: result[i].get("id", ""))

        for idx in separable_sorted:
            entry = result[idx]
            _, hx, hz = prop_data[idx]  # (i, half_x, half_z)
            px = entry.get("x", 0.0)
            pz = entry.get("z", 0.0)

            # Check against NPC.  NPC doesn't move, so push full overlap.
            # Use <= to handle same-position case deterministically.
            ox = (hx + npc_hx) - abs(px - npc_x)
            oz = (hz + npc_hz) - abs(pz - npc_z)
            if ox > 0 and oz > 0:
                moved = True
                if ox < oz:
                    push = ox + 0.01
                    if px <= npc_x:
                        entry["x"] = px - push
                    else:
                        entry["x"] = px + push
                else:
                    push = oz + 0.01
                    if pz <= npc_z:
                        entry["z"] = pz - push
                    else:
                        entry["z"] = pz + push
                px = entry.get("x", px)
                pz = entry.get("z", pz)

            # Check against previously placed separable props
            for other_idx in separable_sorted:
                if other_idx >= idx:
                    break
                other = result[other_idx]
                _, other_hx, other_hz = prop_data[other_idx]
                ox = (hx + other_hx) - abs(px - other.get("x", 0.0))
                oz = (hz + other_hz) - abs(pz - other.get("z", 0.0))
                if ox > 0 and oz > 0:
                    moved = True
                    if ox < oz:
                        push = ox / 2.0 + 0.01
                        if px < other.get("x", 0.0):
                            entry["x"] = px - push
                        else:
                            entry["x"] = px + push
                    else:
                        push = oz / 2.0 + 0.01
                        if pz < other.get("z", 0.0):
                            entry["z"] = pz - push
                        else:
                            entry["z"] = pz + push
                    px = entry.get("x", px)
                    pz = entry.get("z", pz)

        if not moved:
            break

    return result
