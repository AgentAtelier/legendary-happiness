"""world_events — CB-5 emergent world-events engine.

Anvil port (G3): themed event pick + precursor signals + spatial
propagation + consequences → mutate room/needs → spawn an emergent
quest (reuses CB-1 quest-gen).

Event-consequence schema (the CB-5 data contract):
```python
{
    "event_id": "event_N",
    "event_type": "blight",
    "precursors": ["low_food", "night"],       # what triggered it
    "spatial_origin": {"room": [rx, rz]},       # where it originated
    "consequences": {
        "needs": {"food": -30},                 # need mutations (delta)
        "room_mutations": [],                   # room entity changes
        "spawned_quest_id": "q_emergent_N",     # emergent quest
    },
    "tick_fired": 0,                            # which game tick fired it
}
```

The module is extractable as a standalone event-engine tool.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple


# ── Event type ───────────────────────────────────────────────────

class EventType:
    """A single event type in the catalogue."""
    name: str
    dominant_consequence: str       # "resource_loss" | "structural" | "displacement" | "deaths" | "disease"
    precursors: List[str]           # conditions that can trigger it
    need_mutations: Dict[str, float]  # delta applied to NPC needs (negative = loss, positive = gain)
    severity: float                 # 0.0–1.0 base severity multiplier
    spatial_radius: int             # rooms affected from epicentre (Manhattan distance)
    spawns_quest: bool              # whether this event generates an emergent quest
    quest_theme: str                # theme for the spawned quest (fetch/clear/repair/escort)

    def __init__(
        self,
        name: str,
        dominant_consequence: str,
        precursors: List[str],
        need_mutations: Dict[str, float],
        severity: float = 0.5,
        spatial_radius: int = 0,
        spawns_quest: bool = True,
        quest_theme: str = "fetch",
    ):
        self.name = name
        self.dominant_consequence = dominant_consequence
        self.precursors = precursors
        self.need_mutations = need_mutations
        self.severity = severity
        self.spatial_radius = spatial_radius
        self.spawns_quest = spawns_quest
        self.quest_theme = quest_theme


# ── Event catalogue (G3: 7 event types) ──────────────────────────

EVENT_CATALOGUE: Dict[str, EventType] = {
    "flood": EventType(
        name="flood",
        dominant_consequence="displacement",
        precursors=["night", "rain"],  # triggers during night/rain
        need_mutations={"shelter": -40, "safety": -30, "food": -15},
        severity=0.7,
        spatial_radius=1,
        spawns_quest=True,
        quest_theme="deliver",  # "bring supplies to the flood zone"
    ),
    "earthquake": EventType(
        name="earthquake",
        dominant_consequence="structural",
        precursors=["day", "no_warning"],  # sudden, no precursor
        need_mutations={"safety": -50, "shelter": -35, "water": -20},
        severity=0.9,
        spatial_radius=2,
        spawns_quest=True,
        quest_theme="place",  # "repair the collapsed shelf"
    ),
    "wildfire": EventType(
        name="wildfire",
        dominant_consequence="resource_loss",
        precursors=["day", "drought"],
        need_mutations={"shelter": -45, "food": -30, "safety": -40},
        severity=0.8,
        spatial_radius=1,
        spawns_quest=True,
        quest_theme="fetch",  # "fetch water from the well"
    ),
    "blizzard": EventType(
        name="blizzard",
        dominant_consequence="displacement",
        precursors=["night", "cold"],
        need_mutations={"shelter": -50, "companionship": -25, "food": -20},
        severity=0.8,
        spatial_radius=2,
        spawns_quest=True,
        quest_theme="deliver",  # "deliver blankets to the stranded"
    ),
    "drought": EventType(
        name="drought",
        dominant_consequence="resource_loss",
        precursors=["day", "long_time"],  # after many ticks
        need_mutations={"water": -50, "food": -25, "joy": -15},
        severity=0.6,
        spatial_radius=1,
        spawns_quest=True,
        quest_theme="fetch",  # "fetch water from the well"
    ),
    "landslide": EventType(
        name="landslide",
        dominant_consequence="structural",
        precursors=["rain", "earthquake"],  # follows rain or quake
        need_mutations={"shelter": -40, "safety": -45, "companionship": -20},
        severity=0.85,
        spatial_radius=1,
        spawns_quest=True,
        quest_theme="place",  # "clear the blocked entrance"
    ),
    "blight": EventType(
        name="blight",
        dominant_consequence="disease",
        precursors=["day", "long_time"],
        need_mutations={"food": -40, "joy": -30, "water": -20, "sleep": -15},
        severity=0.65,
        spatial_radius=1,
        spawns_quest=True,
        quest_theme="fetch",  # "fetch the healing herb"
    ),
}


# ── Precursor signals (the conditions that trigger events) ──────

def check_precursors(
    event_type: str,
    time_of_day: str = "day",
    tick_count: int = 0,
    needs: Dict[str, float] | None = None,
    room_recent_events: List[str] | None = None,
) -> bool:
    """Return True if the precursor conditions for *event_type* are met.

    Args:
        event_type: Key into EVENT_CATALOGUE.
        time_of_day: "day" | "night" | "dawn" | "dusk".
        tick_count: Current game tick (higher = more elapsed time).
        needs: Current NPC need values (to check for low-need triggers).
        room_recent_events: Recent event type names in this room (for chaining).

    Returns:
        True if all precursors for the event type are satisfied.
    """
    ev = EVENT_CATALOGUE.get(event_type)
    if ev is None:
        return False

    needs = needs or {}
    room_recent_events = room_recent_events or []

    for precursor in ev.precursors:
        if precursor == "day" and time_of_day not in ("day", "dawn", "dusk"):
            return False
        if precursor == "night" and time_of_day != "night":
            return False
        if precursor == "rain":
            # Rain is an external condition — for now, always possible
            # (future: tie to weather system)
            pass
        if precursor == "cold":
            # Cold is a seasonal/time condition — always possible at night
            if time_of_day != "night":
                return False
        if precursor == "drought":
            # Drought follows long dry periods — check tick count
            if tick_count < 10:
                return False
        if precursor == "long_time":
            # Triggers after many ticks have passed
            if tick_count < 20:
                return False
        if precursor == "no_warning":
            # Always possible — no precursor needed
            pass
        if precursor == "earthquake":
            # Chaining: earthquake must have recently occurred
            if "earthquake" not in room_recent_events:
                return False
        if precursor == "low_food":
            if needs.get("food", 100) > 30:
                return False
        if precursor == "low_water":
            if needs.get("water", 100) > 30:
                return False
        if precursor == "low_shelter":
            if needs.get("shelter", 100) > 30:
                return False

    return True


# ── Spatial propagation ──────────────────────────────────────────

def affected_rooms(
    epicentre: Tuple[int, int],
    radius: int,
    all_rooms: List[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    """Return rooms within *radius* Manhattan distance of *epicentre*."""
    ex, ez = epicentre
    result: List[Tuple[int, int]] = []
    for rx, rz in all_rooms:
        if abs(rx - ex) + abs(rz - ez) <= radius:
            result.append((rx, rz))
    return result


# ── Consequence generation ──────────────────────────────────────

def generate_consequences(
    event_type: str,
    epicentre: Tuple[int, int],
    all_rooms: List[Tuple[int, int]],
    event_id: str = "event_0",
    tick: int = 0,
) -> dict:
    """Generate the full consequence dict for a fired event.

    Returns the event-consequence schema dict with need mutations,
    room mutations, and a spawned emergent quest ID.
    """
    ev = EVENT_CATALOGUE.get(event_type)
    if ev is None:
        return {
            "event_id": event_id,
            "event_type": event_type,
            "precursors": [],
            "spatial_origin": {"room": list(epicentre)},
            "consequences": {
                "needs": {},
                "room_mutations": [],
                "spawned_quest_id": None,
            },
            "tick_fired": tick,
        }

    # Scale need mutations by severity
    scaled_needs: Dict[str, float] = {}
    for need, delta in ev.need_mutations.items():
        scaled_needs[need] = delta * ev.severity

    # Determine affected rooms
    rooms = affected_rooms(epicentre, ev.spatial_radius, all_rooms)

    # Room mutations: structural events can disable furniture
    room_mutations: List[dict] = []
    if ev.dominant_consequence == "structural":
        room_mutations.append({
            "action": "disable_random_furniture",
            "count": max(1, int(ev.severity * 2)),
        })
    elif ev.dominant_consequence == "resource_loss":
        room_mutations.append({
            "action": "remove_random_carryable",
            "count": max(1, int(ev.severity * 2)),
        })
    elif ev.dominant_consequence == "disease":
        room_mutations.append({
            "action": "spread_disease",
            "npc_count": max(1, int(ev.severity * 3)),
        })

    # Spawn emergent quest if the event type supports it
    spawned_quest_id = None
    if ev.spawns_quest:
        spawned_quest_id = f"q_emergent_{event_id}"

    return {
        "event_id": event_id,
        "event_type": event_type,
        "precursors": list(ev.precursors),
        "spatial_origin": {"room": list(epicentre)},
        "affected_rooms": [list(r) for r in rooms],
        "consequences": {
            "needs": scaled_needs,
            "room_mutations": room_mutations,
            "spawned_quest_id": spawned_quest_id,
        },
        "tick_fired": tick,
    }


# ── Emergent quest spawning ─────────────────────────────────────

def spawn_emergent_quest(
    event_type: str,
    epicentre: Tuple[int, int],
    existing_npc_ids: List[str],
    quest_id: str = "q_emergent_0",
    manifest_entities: List[str] | None = None,
) -> dict:
    """Generate a valid quest spec for an emergent event.

    Returns a quest-spec dict suitable for injection into the
    behaviour_gen pipeline (compatible with CB-1 quest_data v2).

    The quest type is derived from the event's quest_theme.
    *manifest_entities* are real entity IDs from the manifest —
    used as fetch/deliver/place targets so the quest is winnable.
    """
    ev = EVENT_CATALOGUE.get(event_type)
    quest_theme = ev.quest_theme if ev else "fetch"
    manifest_entities = manifest_entities or []

    # Choose a giver NPC from the existing set
    giver_id = existing_npc_ids[0] if existing_npc_ids else "npc_0"

    # Pick a real target entity from the manifest if available
    target_entity = manifest_entities[0] if manifest_entities else f"emergent_{event_type}"

    quest_spec: dict = {
        "npc_id": giver_id,
        "npc_role": "villager",
        "quest_id": quest_id,
        "objective": {
            "type": quest_theme,
            "target": target_entity,
            "giver": giver_id,
        },
        "dialogue": {
            "greet": f"A {event_type} has struck! Please help.",
            "ask": f"The {event_type} caused trouble. Can you assist?",
            "wrong": "That won't fix things.",
            "thank": "You saved us from the disaster. Thank you!",
        },
        "idle_barks": [
            f"The {event_type} has changed everything.",
            "We must rebuild.",
            "Thank you for helping us recover.",
        ],
        "depends_on": [],
    }

    # Tune the objective based on quest_theme
    if quest_theme == "deliver":
        quest_spec["objective"]["recipient"] = (
            existing_npc_ids[1] if len(existing_npc_ids) > 1 else giver_id
        )
    elif quest_theme == "place":
        # Use a real surface entity if available, otherwise fallback
        surface_target = (
            manifest_entities[2] if len(manifest_entities) > 2
            else manifest_entities[0] if manifest_entities
            else f"surface_{epicentre[0]}_{epicentre[1]}"
        )
        quest_spec["objective"]["location"] = surface_target
    elif quest_theme == "talk":
        quest_spec["objective"]["target"] = (
            existing_npc_ids[1] if len(existing_npc_ids) > 1 else giver_id
        )

    return quest_spec


# ── Event picker (deterministic, seed-driven) ────────────────────

def pick_events(
    num_events: int = 1,
    time_of_day: str = "day",
    tick_count: int = 0,
    needs: Dict[str, float] | None = None,
    room_recent_events: List[str] | None = None,
    seed: int = 42,
) -> List[str]:
    """Pick *num_events* event types whose precursors are satisfied.

    Returns a list of event type names, deterministically ordered.
    """
    import random as _random
    rng = _random.Random(seed)

    needs = needs or {}
    room_recent_events = room_recent_events or []

    # Find all events whose precursors are met
    candidates: List[EventType] = []
    for ev in EVENT_CATALOGUE.values():
        if check_precursors(
            ev.name,
            time_of_day=time_of_day,
            tick_count=tick_count,
            needs=needs,
            room_recent_events=room_recent_events,
        ):
            candidates.append(ev)

    if not candidates:
        return []

    # Pick deterministically — weighted by severity
    # Sort by severity (descending), then pick top N
    candidates.sort(key=lambda e: (-e.severity, e.name))
    chosen = candidates[:min(num_events, len(candidates))]

    return [ev.name for ev in chosen]


# ── Convenience: fire events for a room ──────────────────────────

def fire_events(
    num_events: int = 1,
    time_of_day: str = "day",
    tick_count: int = 0,
    needs: Dict[str, float] | None = None,
    room_recent_events: List[str] | None = None,
    epicentre: Tuple[int, int] = (0, 0),
    all_rooms: List[Tuple[int, int]] | None = None,
    existing_npc_ids: List[str] | None = None,
    manifest_entities: List[str] | None = None,
    seed: int = 42,
) -> List[dict]:
    """Pick, generate, and return fired event dicts.

    Returns a list of event-consequence schema dicts, one per fired
    event, ready for emission into quest_data.

    *manifest_entities* are real entity IDs from the manifest, used
    as quest targets so spawned emergent quests reference real entities.
    """
    all_rooms = all_rooms or [(0, 0)]
    existing_npc_ids = existing_npc_ids or ["npc_0"]
    manifest_entities = manifest_entities or []

    event_types = pick_events(
        num_events=num_events,
        time_of_day=time_of_day,
        tick_count=tick_count,
        needs=needs,
        room_recent_events=room_recent_events,
        seed=seed,
    )

    fired: List[dict] = []
    for i, etype in enumerate(event_types):
        event_id = f"event_{tick_count}_{i}"
        event = generate_consequences(
            etype,
            epicentre=epicentre,
            all_rooms=all_rooms,
            event_id=event_id,
            tick=tick_count,
        )
        # Attach the spawned quest spec
        if event["consequences"]["spawned_quest_id"]:
            quest_spec = spawn_emergent_quest(
                etype,
                epicentre=epicentre,
                existing_npc_ids=existing_npc_ids,
                quest_id=event["consequences"]["spawned_quest_id"],
                manifest_entities=manifest_entities,
            )
            event["spawned_quest"] = quest_spec
        fired.append(event)

    return fired
