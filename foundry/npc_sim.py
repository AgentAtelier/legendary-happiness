"""npc_sim — G2 needs + utility-action loop (Anvil port).

Design from ANVIL-PORT-ASSESSMENT.md §G2:
- 7 needs (food/water/shelter/safety/sleep/companionship/joy)
- Per-need decay (linear, configurable rate)
- ~21-action catalogue (each tagged primary_need, coping_type, time_preference,
  communal, major/minor, duration)
- NPCs pick the **utility-max** action using a simple urgency × fulfillment model.

This is a **build-time** module.  It defines the needs model and action
catalogue; the generated needs data is serialised into quest_data for
the Godot runtime (npc.gd) to tick and act on.

Run-time needs decay + action selection are mirrored in npc.gd for
deterministic Godot-side execution.
"""

from __future__ import annotations

# ── 7 Needs ──────────────────────────────────────────────────────

NEED_NAMES: tuple[str, ...] = (
    "food", "water", "shelter", "safety",
    "sleep", "companionship", "joy",
)

# Per-need defaults: (initial_value, decay_per_hour, urgency_threshold)
# Decay is linear — need drops by decay_per_hour every game-hour.
# When a need falls below its threshold, it becomes "urgent" and
# actions that address it get a utility bonus.
NEED_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "food":           (80.0, 8.0,  30.0),
    "water":          (85.0, 10.0, 25.0),
    "shelter":        (90.0, 2.0,  50.0),
    "safety":         (75.0, 3.0,  40.0),
    "sleep":          (70.0, 6.0,  35.0),
    "companionship":  (60.0, 4.0,  30.0),
    "joy":            (50.0, 1.0,  20.0),  # joy only from catalyst events (G2)
}


def default_needs() -> dict[str, float]:
    """Return a fresh needs dict with default starting values."""
    return {name: NEED_DEFAULTS[name][0] for name in NEED_NAMES}


def tick_needs(needs: dict[str, float], hours: float) -> dict[str, float]:
    """Decay all needs by *hours* game-hours.

    Returns a new dict (does not mutate input).  Clamps to ≥ 0.
    """
    result: dict[str, float] = {}
    for name in NEED_NAMES:
        _, decay_rate, _ = NEED_DEFAULTS[name]
        result[name] = max(0.0, needs.get(name, 100.0) - decay_rate * hours)
    return result


def urgency(need_name: str, value: float) -> float:
    """Return the urgency of a need (0..1).  1 = critically depleted."""
    _, _, threshold = NEED_DEFAULTS[need_name]
    if value >= threshold:
        return 0.0
    return 1.0 - (value / threshold)


# ── 21-Action Catalogue ──────────────────────────────────────────
#
# Each action has:
#   id              str            unique action key
#   label           str            human-readable name
#   primary_need    str            the need this action primarily addresses
#   fulfillment     float          0..100 how much need is restored
#   duration_h      float          hours to complete
#   coping_type     str            "active" | "passive" | "social"
#   time_preference str            "any" | "day" | "night"
#   communal        bool           True if action involves other NPCs
#   major           bool           True for long/significant actions
#   location_tag    str            where the action happens ("any" | "furniture" | "npc" | "door")
#   target_category str | None     furniture/carryable category to seek (None = any)

_ACTION_CATALOGUE: list[dict] = [
    # ── Food ──────────────────────────────────────────────────
    {"id": "eat_stored",   "label": "Eat stored food",   "primary_need": "food",  "fulfillment": 60, "duration_h": 0.3,  "coping_type": "active",  "time_preference": "any",  "communal": False, "major": False, "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "cook_meal",    "label": "Cook a meal",       "primary_need": "food",  "fulfillment": 85, "duration_h": 1.0,  "coping_type": "active",  "time_preference": "day",  "communal": False, "major": True,  "location_tag": "furniture", "target_category": "table"},  # noqa: E501  literal
    {"id": "forage_food",  "label": "Forage for food",   "primary_need": "food",  "fulfillment": 40, "duration_h": 2.0,  "coping_type": "active",  "time_preference": "day",  "communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    # ── Water ────────────────────────────────────────────────
    {"id": "drink_stored", "label": "Drink stored water", "primary_need": "water", "fulfillment": 60, "duration_h": 0.2,  "coping_type": "active",  "time_preference": "any",  "communal": False, "major": False, "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "fetch_water",  "label": "Fetch fresh water",  "primary_need": "water", "fulfillment": 75, "duration_h": 1.5,  "coping_type": "active",  "time_preference": "day",  "communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "share_water",  "label": "Share water",        "primary_need": "water", "fulfillment": 50, "duration_h": 0.3,  "coping_type": "social",  "time_preference": "any",  "communal": True,  "major": False, "location_tag": "npc",       "target_category": None},  # noqa: E501  literal
    # ── Shelter ──────────────────────────────────────────────
    {"id": "rest_at_home",   "label": "Rest at home",     "primary_need": "shelter", "fulfillment": 70, "duration_h": 2.0,  "coping_type": "passive", "time_preference": "any",  "communal": False, "major": True,  "location_tag": "furniture", "target_category": "chair"},  # noqa: E501  literal
    {"id": "repair_shelter", "label": "Repair shelter",   "primary_need": "shelter", "fulfillment": 50, "duration_h": 3.0,  "coping_type": "active",  "time_preference": "day",  "communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "huddle_warmth",  "label": "Huddle for warmth","primary_need": "shelter", "fulfillment": 30, "duration_h": 1.0,  "coping_type": "social",  "time_preference": "night","communal": True,  "major": False, "location_tag": "npc",       "target_category": None},  # noqa: E501  literal
    # ── Safety ───────────────────────────────────────────────
    {"id": "stand_guard",   "label": "Stand guard",       "primary_need": "safety", "fulfillment": 40, "duration_h": 2.0,  "coping_type": "active",  "time_preference": "any",  "communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "patrol_area",   "label": "Patrol the area",   "primary_need": "safety", "fulfillment": 50, "duration_h": 1.5,  "coping_type": "active",  "time_preference": "any",  "communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "seek_company",  "label": "Seek company",      "primary_need": "safety", "fulfillment": 35, "duration_h": 0.5,  "coping_type": "social",  "time_preference": "any",  "communal": True,  "major": False, "location_tag": "npc",       "target_category": None},  # noqa: E501  literal
    # ── Sleep ────────────────────────────────────────────────
    {"id": "nap",           "label": "Take a nap",        "primary_need": "sleep", "fulfillment": 40, "duration_h": 1.0,  "coping_type": "passive", "time_preference": "any",  "communal": False, "major": False, "location_tag": "furniture", "target_category": "chair"},  # noqa: E501  literal
    {"id": "sleep_night",   "label": "Sleep through night","primary_need": "sleep", "fulfillment": 90, "duration_h": 6.0,  "coping_type": "passive", "time_preference": "night","communal": False, "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "doze_by_fire",  "label": "Doze by the fire",  "primary_need": "sleep", "fulfillment": 50, "duration_h": 2.0,  "coping_type": "passive", "time_preference": "any",  "communal": False, "major": False, "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    # ── Companionship ────────────────────────────────────────
    {"id": "chat",          "label": "Chat with someone",  "primary_need": "companionship", "fulfillment": 45, "duration_h": 0.5,  "coping_type": "social", "time_preference": "any",  "communal": True,  "major": False, "location_tag": "npc",       "target_category": None},  # noqa: E501  literal
    {"id": "share_story",   "label": "Share a story",     "primary_need": "companionship", "fulfillment": 60, "duration_h": 1.0,  "coping_type": "social", "time_preference": "any",  "communal": True,  "major": True,  "location_tag": "npc",       "target_category": None},  # noqa: E501  literal
    {"id": "work_together", "label": "Work together",     "primary_need": "companionship", "fulfillment": 50, "duration_h": 2.0,  "coping_type": "active", "time_preference": "day",  "communal": True,  "major": True,  "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    # ── Joy (only from catalyst events in full G2; included for completeness) ─
    {"id": "idle_sit",      "label": "Sit and rest",     "primary_need": "joy", "fulfillment": 15, "duration_h": 0.5,  "coping_type": "passive", "time_preference": "any",  "communal": False, "major": False, "location_tag": "furniture", "target_category": "chair"},  # noqa: E501  literal
    {"id": "admire_view",   "label": "Admire the view",  "primary_need": "joy", "fulfillment": 20, "duration_h": 0.3,  "coping_type": "passive", "time_preference": "day",  "communal": False, "major": False, "location_tag": "any",       "target_category": None},  # noqa: E501  literal
    {"id": "sing_song",     "label": "Sing a song",      "primary_need": "joy", "fulfillment": 25, "duration_h": 0.3,  "coping_type": "social",  "time_preference": "any",  "communal": True,  "major": False, "location_tag": "any",       "target_category": None},  # noqa: E501  literal
]

ACTION_CATALOGUE: tuple[dict, ...] = tuple(_ACTION_CATALOGUE)


def select_action(
    needs: dict[str, float],
    available_actions: tuple[dict, ...] = ACTION_CATALOGUE,
    time_of_day: str = "day",
    other_npcs_nearby: bool = False,
) -> dict:
    """Select the utility-max action from *available_actions*.

    Utility = sum over all needs of (urgency(need) × fulfillment_contribution)
    where fulfillment_contribution is action.fulfillment for the primary need
    and 0 for all other needs.  (Simplified model — the real Anvil system
    weights all needs by action affinity, but this is the gold path.)

    Actions with time_preference mismatching *time_of_day* are penalised
    (utility × 0.5).  Actions requiring other NPCs (communal=True) when
    *other_npcs_nearby* is False are excluded.

    Returns the winning action dict.  If no action is viable, returns
    the first action (fallback).
    """
    best_action: dict = available_actions[0]
    best_utility: float = -1.0

    for action in available_actions:
        # Exclude communal actions when no other NPCs nearby
        if action["communal"] and not other_npcs_nearby:
            continue

        primary = action["primary_need"]
        need_value = needs.get(primary, 100.0)
        u = urgency(primary, need_value)
        raw_utility = u * action["fulfillment"]

        # Time-of-day penalty
        tp = action["time_preference"]
        if tp != "any" and tp != time_of_day:
            raw_utility *= 0.5

        if raw_utility > best_utility:
            best_utility = raw_utility
            best_action = action

    return best_action


def generate_npc_needs(npc_count: int, seed: int = 42) -> list[dict[str, float]]:
    """Generate slightly-varied starting needs for *npc_count* NPCs.

    Each NPC starts close to the defaults, with ±15% random variation
    to make them feel distinct from the start.
    """
    import random as _random
    rng = _random.Random(seed)
    results: list[dict[str, float]] = []
    for _ in range(npc_count):
        needs: dict[str, float] = {}
        for name in NEED_NAMES:
            base = NEED_DEFAULTS[name][0]
            jitter = base * rng.uniform(-0.15, 0.15)
            needs[name] = max(0.0, min(100.0, base + jitter))
        results.append(needs)
    return results
