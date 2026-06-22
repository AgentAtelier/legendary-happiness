# event_manager.gd — CB-5 emergent events runtime.
#
# Reads event data from quest_data.json at scene load.  Ticks on
# time-of-day transitions (from day_night.gd signal) or player
# actions, applying consequences:
#   - Need mutations: broadcasts need deltas to NPC nodes
#   - Room mutations: enables/disables furniture entities
#   - Spawned quests: registers emergent quests with QuestManager
#
# Communicates with NPCs and QuestManager via get_node() calls.
extends Node

var _events: Array = []          # list of event dicts from quest_data
var _tick_count: int = 0
var _fired_events: Array = []    # event_ids already applied
var _current_time_of_day: String = "day"


func _ready() -> void:
	_load_events()


func _load_events() -> void:
	"""Read event data from the quest_data.json file alongside the scene."""
	var scene_path := get_tree().current_scene.scene_file_path
	if scene_path == "":
		return
	var data_path := scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if not file:
		return
	var text := file.get_as_text()
	file.close()
	var json := JSON.new()
	var err := json.parse(text)
	if err != OK:
		return
	var data = json.get_data()
	if not data is Dictionary:
		return
	_events = data.get("events", [])
	if not _events is Array:
		_events = []


func on_time_of_day_changed(new_time: String) -> void:
	"""Called by day_night.gd on day/night/dusk/dawn transitions."""
	_current_time_of_day = new_time
	_tick_count += 1
	_check_and_fire_events()


func on_player_action(action: String) -> void:
	"""Called by interaction.gd on significant player actions."""
	# Actions that might trigger events: "pickup", "open_container", "talk"
	if action in ["pickup", "open_container"]:
		_tick_count += 1
		_check_and_fire_events()


func _check_and_fire_events() -> void:
	"""Check pending events and fire any whose precursors are met."""
	for ev in _events:
		if not ev is Dictionary:
			continue
		var eid := str(ev.get("event_id", ""))
		if eid in _fired_events:
			continue
		
		# Check if this event's conditions are met at this tick/time
		if _should_fire_now(ev):
			_fire_event(ev)
			_fired_events.append(eid)


func _should_fire_now(ev: Dictionary) -> bool:
	"""Check if an event's tick_fired matches current conditions."""
	var tick := int(ev.get("tick_fired", 0))
	# Fire when tick matches or on first eligible time-of-day
	if tick <= _tick_count:
		return true
	return false


func _fire_event(ev: Dictionary) -> void:
	"""Apply an event's consequences to the world."""
	var consequences = ev.get("consequences", {})
	if not consequences is Dictionary:
		return
	
	# Apply need mutations to all NPCs
	var needs_delta: Dictionary = consequences.get("needs", {})
	if needs_delta is Dictionary and needs_delta.size() > 0:
		_apply_need_mutations(needs_delta)
	
	# Apply room mutations
	var room_mutations: Array = consequences.get("room_mutations", [])
	if room_mutations is Array:
		_apply_room_mutations(room_mutations)
	
	# Register spawned quest
	var quest_id := str(consequences.get("spawned_quest_id", ""))
	if quest_id != "":
		var quest_spec := ev.get("spawned_quest", null)
		if quest_spec != null:
			var qm = get_node_or_null("/root/QuestManager")
			if qm and qm.has_method("register_emergent_quest"):
				qm.register_emergent_quest(quest_id, quest_spec)
	
	# Show event notification
	var event_type := str(ev.get("event_type", ""))
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("set_objective"):
		hud.set_objective("A %s has occurred!" % event_type.replace("_", " "))


func _apply_need_mutations(needs_delta: Dictionary) -> void:
	"""Broadcast need mutations to all NPC nodes in the scene."""
	var root = get_node_or_null("/root/Root")
	if not root:
		return
	
	for child in root.get_children():
		if child.has_method("apply_need_delta"):
			child.apply_need_delta(needs_delta)


func _apply_room_mutations(mutations: Array) -> void:
	"""Apply room entity changes from event consequences."""
	var root = get_node_or_null("/root/Root")
	if not root:
		return
	
	for mutation in mutations:
		if not mutation is Dictionary:
			continue
		var action := str(mutation.get("action", ""))
		var count := int(mutation.get("count", 1))
		
		match action:
			"disable_random_furniture":
				_disable_random_furniture(root, count)
			"remove_random_carryable":
				_remove_random_carryable(root, count)
			"spread_disease":
				_spread_disease(root, count)


func _disable_random_furniture(root: Node, count: int) -> void:
	"""Make random furniture invisible and non-colliding to simulate structural damage."""
	var furniture: Array = []
	for child in root.get_children():
		var tag := str(child.get_meta("_forge_tag", ""))
		if tag in ["pickup", "open"] and child.is_class("StaticBody3D"):
			furniture.append(child)
	
	var disabled := 0
	for item in furniture:
		if disabled >= count:
			break
		item.visible = false
		item.set("collision_layer", 0)
		item.set("collision_mask", 0)
		disabled += 1


func _remove_random_carryable(root: Node, count: int) -> void:
	"""Remove random carryables from the scene to simulate theft/loss."""
	var carryables: Array = []
	for child in root.get_children():
		var tag := str(child.get_meta("_forge_tag", ""))
		if tag == "pickup" and child.is_class("StaticBody3D"):
			carryables.append(child)
	
	var removed := 0
	for item in carryables:
		if removed >= count:
			break
		item.queue_free()
		removed += 1


func _spread_disease(root: Node, count: int) -> void:
	"""Apply disease need penalty to random NPCs."""
	var npcs: Array = []
	for child in root.get_children():
		var tag := str(child.get_meta("_forge_tag", ""))
		if tag == "talk":
			npcs.append(child)
	
	var affected := 0
	for npc in npcs:
		if affected >= count:
			break
		if npc.has_method("apply_need_delta"):
			npc.apply_need_delta({"sleep": -20, "food": -15, "joy": -25})
		affected += 1
