# NPC — handles talk (dialogue) and give (item check).
# State machine: IDLE -> QUEST_GIVEN -> DONE.
# Loads quest data from _quest_data.json alongside the scene.
# C-3: Quest-state persistence via the world-model transactional log.
#       On _ready(), replays the log to find current npc_state.
#       On state change, appends a "replace" event to the log.
extends Node3D

enum State { IDLE, QUEST_GIVEN, DONE }

var _state: int = State.IDLE
var _quest_data: Dictionary = {}
# C-3: world log persistence
var _npc_id: String = ""
var _world_log_path: String = ""
var _base_placement: Dictionary = {}


func _ready() -> void:
	_load_quest_data()
	# C-3: Restore NPC state from the world log (survives reload)
	_restore_state_from_log()


func _load_quest_data() -> void:
	var scene_path: String = get_tree().current_scene.scene_file_path
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var text: String = file.get_as_text()
		var parsed = JSON.parse_string(text)
		if parsed is Dictionary:
			# C-4: Read npc_id from this node's metadata (set by scene_compiler)
			_npc_id = str(get_meta("_forge_npc_id", "NPC"))
			_world_log_path = str(parsed.get("world_log_path", ""))
			# C-4: Look up this NPC's data in the shared npcs dict
			var npcs_data = parsed.get("npcs", {})
			var my_data = npcs_data.get(_npc_id, {})
			if my_data and not my_data.is_empty():
				_quest_data = my_data
				_base_placement = my_data.get("npc_placement", {})
			else:
				# Fallback: single-NPC format (C-3 backward compat)
				_quest_data = parsed
				_base_placement = parsed.get("npc_placement", {})


func on_interact(tag: String) -> void:
	if tag != "talk":
		return
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_talk()
	var hud = get_node("/root/Root/HUD")
	match _state:
		State.IDLE:
			_show_line(hud, "greet")
			await _wait_for_advance()
			_show_line(hud, "ask")
			_state = State.QUEST_GIVEN
			# C-3: Persist state change to world log
			_append_state_to_log("quest_given")
		State.QUEST_GIVEN:
			var player = get_node("/root/Root/Player")
			# C-2: Use get_active_item() for multi-item inventory
			var carried: String = ""
			if player.has_method("get_active_item"):
				carried = player.get_active_item()
			var target: String = _quest_data.get("target_entity", "")
			if carried == target:
				_show_line(hud, "thank")
				_state = State.DONE
				# C-3: Persist state change to world log
				_append_state_to_log("done")
				_emit_win()
			else:
				_show_line(hud, "wrong")
				await _wait_for_advance()
				_show_line(hud, "ask")
		State.DONE:
			_show_line(hud, "thank")


func _wait_for_advance() -> void:
	"""Wait for Space/Enter key press, showing 'Space to continue' hint.

	U-6: In headless mode (Godot smoke tests), skip the wait entirely
	so the V-1 probe can drive the dialogue without keyboard input."""
	if OS.has_feature("headless"):
		return
	var hud = get_node("/root/Root/HUD")
	if hud.has_method("show_interact"):
		hud.show_interact("Space to continue")
	# Wait for Space or Enter key
	while true:
		await get_tree().process_frame
		if Input.is_key_pressed(KEY_SPACE) or Input.is_key_pressed(KEY_ENTER):
			break
	if hud.has_method("show_interact"):
		hud.show_interact("")
	# Debounce: wait until keys are released
	while Input.is_key_pressed(KEY_SPACE) or Input.is_key_pressed(KEY_ENTER):
		await get_tree().process_frame


# ── C-3: World-log persistence ──────────────────────────────────────

func _restore_state_from_log() -> void:
	"""C-3: Replay the world log backwards to find this NPC's last
	state, then set _state accordingly.  Survives scene reload.

	Note: Reads the entire log into memory and scans backwards — O(n)
	in log size.  Fine for C-3 with a single NPC and short logs.
	For C-4, consider seeking to end and scanning backwards in chunks."""
	if _world_log_path == "":
		return
	var file = FileAccess.open(_world_log_path, FileAccess.READ)
	if not file:
		return
	var text: String = file.get_as_text()
	var lines: PackedStringArray = text.split("\n")
	# Walk backwards — first matching event wins (most recent state)
	for i in range(lines.size() - 1, -1, -1):
		var line: String = lines[i].strip_edges()
		if line == "":
			continue
		var event = JSON.parse_string(line)
		if event is Dictionary:
			var placement = event.get("placement", {})
			if placement.get("id") == _npc_id:
				var attrs = placement.get("attrs", {})
				var saved_state: String = str(attrs.get("npc_state", "idle"))
				_state = _state_from_string(saved_state)
				return


func _append_state_to_log(state_name: String) -> void:
	"""C-3: Append a 'replace' event to the world log with the new
	npc_state.  Uses the full base_placement from quest_data so we
	don't lose asset_hash or other attrs."""
	if _world_log_path == "" or _base_placement.is_empty():
		return
	var placement: Dictionary = _base_placement.duplicate(true)
	var attrs: Dictionary = placement.get("attrs", {}).duplicate(true)
	attrs["npc_state"] = state_name
	placement["attrs"] = attrs
	var event: Dictionary = {
		"action": "replace",
		"placement": placement,
	}
	# Use READ_WRITE (non-truncating) so we don't destroy previous
	# log entries.  Fall back to WRITE (which creates+truncates) only
	# when the log doesn't exist yet.
	var file = FileAccess.open(_world_log_path, FileAccess.READ_WRITE)
	if not file:
		file = FileAccess.open(_world_log_path, FileAccess.WRITE)
	if file:
		file.seek_end()
		file.store_line(JSON.stringify(event))


func _state_from_string(state_name: String) -> int:
	match state_name:
		"quest_given":
			return State.QUEST_GIVEN
		"done":
			return State.DONE
		_:
			return State.IDLE


# ── Dialogue display + win ───────────────────────────────────────────

func _show_line(hud: Node, key: String) -> void:
	var line: String = _quest_data.get("dialogue", {}).get(key, "...")
	# C-4: Prepend NPC role to the objective line for player context
	var npc_role: String = _quest_data.get("npc_role", "")
	if npc_role != "" and key in ["greet", "ask", "wrong", "thank"]:
		line = npc_role.capitalize() + ": " + line
	if hud.has_method("set_objective"):
		hud.set_objective(line)


func _emit_win() -> void:
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_win()
	var win = get_node("/root/Root/WinScreen")
	if win.has_method("show_win"):
		win.show_win()
