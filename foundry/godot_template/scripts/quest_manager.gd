# quest_manager.gd — CB-1 quest completion tracker + chain gating (autoload).
#
# Registered as an autoload in project.godot so every script can call
# QuestManager.is_quest_locked() / QuestManager.complete_quest() / etc.
#
# On _ready(), reads the scene's _quest_data.json and builds an internal
# registry of quests keyed by quest_id.  Tracks runtime completion state
# and enforces chain gating (a quest with unmet depends_on is locked).
#
# Objective types and their completion conditions:
#   fetch   — player carries target entity to the giver NPC
#   deliver — player carries target entity to the recipient NPC
#   place   — player carries target entity to a location surface
#   talk    — player speaks with the target NPC
extends Node

# ── Internal state ──────────────────────────────────────────────

# quest_id → quest dict (from quest_data v2)
var _quests: Dictionary = {}

# quest_id → bool (completion state)
var _completed: Dictionary = {}

# npc_id → quest_id mapping
var _npc_to_quest: Dictionary = {}

# player's current carried item (updated by pickup.gd / player.gd)
var _carried_item: String = ""

# player's current position (updated by player.gd, for place-on-surface)
var _player_pos: Vector3 = Vector3.ZERO


# ── Public API ──────────────────────────────────────────────────

func is_quest_locked(quest_id: String) -> bool:
	"""Return true if *quest_id* has unmet depends_on prerequisites."""
	if not _quests.has(quest_id):
		return false
	var quest = _quests[quest_id]
	var prereqs: Array = quest.get("depends_on", [])
	for p in prereqs:
		if not _completed.get(str(p), false):
			return true
	return false


func is_quest_complete(quest_id: String) -> bool:
	return _completed.get(quest_id, false)


func complete_quest(quest_id: String) -> void:
	_completed[quest_id] = true


func get_quest_for_npc(npc_id: String) -> Dictionary:
	"""Return the quest dict for *npc_id*, or empty dict."""
	return _quests.get(_npc_to_quest.get(npc_id, ""), {})


func get_objective_type(quest_id: String) -> String:
	"""Return the objective type for *quest_id* (fetch/deliver/place/talk)."""
	var quest = _quests.get(quest_id, {})
	var obj = quest.get("objective", {})
	return str(obj.get("type", "fetch"))


func get_objective_target(quest_id: String) -> String:
	"""Return the target entity for *quest_id*."""
	var quest = _quests.get(quest_id, {})
	var obj = quest.get("objective", {})
	return str(obj.get("target", ""))


func get_objective_recipient(quest_id: String) -> String:
	"""Return the deliver recipient NPC id for *quest_id*, or ''."""
	var quest = _quests.get(quest_id, {})
	var obj = quest.get("objective", {})
	return str(obj.get("recipient", ""))


func get_objective_location(quest_id: String) -> String:
	"""Return the place location entity id for *quest_id*, or ''."""
	var quest = _quests.get(quest_id, {})
	var obj = quest.get("objective", {})
	return str(obj.get("location", ""))


# ── Runtime hooks called by other scripts ───────────────────────

func try_complete_deliver(npc_id: String, carried: String) -> bool:
	"""CB-1: Check if the player's carried item satisfies a deliver quest
	whose recipient is *npc_id*."""
	for quest_id in _quests.keys():
		if is_quest_complete(quest_id) or is_quest_locked(quest_id):
			continue
		var obj = _quests[quest_id].get("objective", {})
		if obj.get("type") != "deliver":
			continue
		if str(obj.get("recipient", "")) != npc_id:
			continue
		if carried == str(obj.get("target", "")):
			complete_quest(quest_id)
			return true
	return false


func try_complete_talk(npc_id: String) -> bool:
	"""CB-1: Check if speaking to *npc_id* completes a talk quest."""
	for quest_id in _quests.keys():
		if is_quest_complete(quest_id) or is_quest_locked(quest_id):
			continue
		var obj = _quests[quest_id].get("objective", {})
		if obj.get("type") != "talk":
			continue
		if str(obj.get("target", "")) == npc_id:
			complete_quest(quest_id)
			return true
	return false


func try_complete_place(carried: String, surface_id: String) -> bool:
	"""CB-1: Check if placing *carried* on *surface_id* completes a place quest."""
	for quest_id in _quests.keys():
		if is_quest_complete(quest_id) or is_quest_locked(quest_id):
			continue
		var obj = _quests[quest_id].get("objective", {})
		if obj.get("type") != "place":
			continue
		if carried == str(obj.get("target", "")) and surface_id == str(obj.get("location", "")):
			complete_quest(quest_id)
			return true
	return false


func all_quests_complete() -> bool:
	for quest_id in _quests.keys():
		if not _completed.get(quest_id, false):
			return false
	return _quests.size() > 0


# ── Initialisation ──────────────────────────────────────────────

func _ready() -> void:
	_load_quests()


func _load_quests() -> void:
	# -s script mode (screenshot/probe) — no scene is loaded, so
	# current_scene is null.  Bail out cleanly instead of crashing.
	var cs := get_tree().current_scene
	if cs == null:
		return
	var scene_path: String = cs.scene_file_path
	if scene_path == "":
		return
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if not file:
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return
	var npcs = parsed.get("npcs", {})
	if not npcs is Dictionary:
		return

	for npc_id in npcs.keys():
		var npc_data = npcs[npc_id]
		if not npc_data is Dictionary:
			continue
		var quest_id: String = str(npc_data.get("quest_id", "q_" + npc_id))
		_npc_to_quest[npc_id] = quest_id
		# Build a quest dict with the fields quest_manager needs
		var obj = npc_data.get("objective", {})
		if not obj is Dictionary:
			obj = {}
		var depends: Array = obj.get("depends_on", [])
		if not depends is Array:
			depends = []
		_quests[quest_id] = {
			"npc_id": npc_id,
			"objective": obj,
			"depends_on": depends,
		}
		_completed[quest_id] = false
