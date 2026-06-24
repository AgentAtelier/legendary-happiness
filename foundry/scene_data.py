"""foundry.scene_data — sidecar I/O for compiled scenes.

Extracted from scene_compiler.py (Phase 1.4).  Pure file/JSON in-out;
no .tscn emission.  Writes _quest_data.json + _world_log.jsonl and can
read them back.
"""

from __future__ import annotations

import json
from pathlib import Path


def _init_world_log(log_path: str, npc_placement: dict) -> None:
    """C-3: Write the NPC's initial state as the first event in
    the world log.  npc.gd replays this on scene load to restore
    quest state across reloads."""
    event = {
        "action": "replace",
        "placement": npc_placement,
    }
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    # C-4: Append (don't overwrite) so multiple NPC initial states accumulate
    with open(log_path, "a", encoding="utf-8") as _f:
        _f.write(json.dumps(event) + "\n")


def read_quest_data(tscn_path: str) -> dict | None:
    """Read the quest_data.json file alongside a compiled .tscn.

    Returns the parsed dict or None if the JSON file is missing.
    """
    tscn = Path(tscn_path)
    data_file = tscn.with_name(f"{tscn.stem}_quest_data.json")
    if not data_file.exists():
        return None
    return json.loads(data_file.read_text(encoding="utf-8"))


def write_sidecar_data(
    output_path: str,
    quest_specs: list[dict],
    manifest: list[dict],
    npc_positions: list[tuple],
    npc_body_category: str,
    npc_body_material: str,
    room_graph: dict | None = None,
    current_room: tuple | None = None,
) -> str:
    """Write _quest_data.json and initialise _world_log.jsonl.

    Extracted from compile_scene (Phase 1.4).  Pure I/O — no .tscn
    emission.  Returns *world_log_path* for use in door metadata.

    Args:
        output_path: Path to the .tscn file (sidecar paths derived from it).
        quest_specs: List of validated quest specs (one per NPC).
        manifest: List of placed entities.
        npc_positions: (x, z) tuples, one per NPC.
        npc_body_category, npc_body_material: Compiler constants for NPC GLB.
        room_graph: Optional multi-room graph.
        current_room: Which room this scene represents.

    Returns:
        *world_log_path* — the path to the _world_log.jsonl file.
    """
    from _constants import DEFAULT_RNG_SEED
    from examine_validator import _category_fallback
    from npc_sim import generate_npc_needs
    from soul import default_soul
    from world_events import fire_events

    output_dir = str(Path(output_path).parent)
    tscn_stem = Path(output_path).stem
    data_filename = f"{tscn_stem}_quest_data.json"
    data_path = str(Path(output_dir) / data_filename)
    # C-3: world log path for NPC quest-state persistence
    world_log_filename = f"{tscn_stem}_world_log.jsonl"
    world_log_path = str(Path(output_dir) / world_log_filename)

    # C-4: Build per-NPC quest data and placements for the shared JSON.
    npcs_data: dict = {}

    # CB-3: Generate per-NPC needs from npc_sim
    npc_needs_list = generate_npc_needs(len(quest_specs))

    for i, spec in enumerate(quest_specs):
        npc_id = spec.get("npc_id", f"npc_{i}")
        npc_pos_x, npc_pos_z = npc_positions[i]
        # Spine Slice 3: bake soul into quest_data
        npc_soul = spec.get("soul", default_soul())
        # CB-3: attach needs to NPC data
        npc_needs = npc_needs_list[i]
        placement: dict = {
            "id": npc_id,
            "asset_hash": f"{npc_body_category}_{npc_body_material}",
            "attrs": {
                "role": spec.get("npc_role", "villager"),
                "npc_state": "idle",
                "x": npc_pos_x,
                "y": 0.0,
                "z": npc_pos_z,
            },
        }
        npcs_data[npc_id] = {
            **spec,
            "soul": npc_soul,
            "npc_placement": placement,
            "needs": npc_needs,  # CB-3: per-NPC needs
        }
        # C-3: Initialise the world log with this NPC's starting state
        _init_world_log(world_log_path, placement)

    # EB-6: Build examine flavour text for all props
    examine_flavour: dict[str, str] = {}
    for entry in manifest:
        eid = entry.get("id", "")
        cat = entry.get("category", "?")
        examine_flavour[eid] = _category_fallback(cat)

    # CB-5: Generate emergent events for this room
    npc_ids = [spec.get("npc_id", f"npc_{i}") for i, spec in enumerate(quest_specs)]
    all_rooms = [(0, 0)]
    if room_graph:
        all_rooms = [tuple(r) for r in room_graph.get("rooms", [(0, 0)])]
    epicentre = current_room if current_room else (0, 0)
    manifest_entity_ids = [e.get("id", "") for e in manifest if not e.get("decor")]
    events_data = fire_events(
        num_events=1,
        time_of_day="day",  # default; runtime may override
        tick_count=0,
        needs=npc_needs_list[0] if npc_needs_list else None,
        epicentre=epicentre,
        all_rooms=all_rooms,
        existing_npc_ids=npc_ids,
        manifest_entities=manifest_entity_ids,
        seed=DEFAULT_RNG_SEED,
    )

    quest_data: dict = {
        "npcs": npcs_data,
        "world_log_path": world_log_path,
        "examine": examine_flavour,
        "events": events_data,  # CB-5: emergent events
        "enemies": [
            {"enemy_id": e["id"], "archetype": "golem",
             "health": 50.0, "damage": 8.0,
             "x": e.get("x", 0), "z": e.get("z", 0)}
            for e in manifest if e.get("category") == "enemy"
        ],  # CB-6: enemy specs
    }
    Path(data_path).write_text(
        json.dumps(quest_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return world_log_path
