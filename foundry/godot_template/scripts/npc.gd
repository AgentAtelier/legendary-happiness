# NPC — handles talk (dialogue) and give (item check).
# State machine: IDLE -> QUEST_GIVEN -> DONE.
# Loads quest data from _quest_data.json alongside the scene.
extends Node3D

enum State { IDLE, QUEST_GIVEN, DONE }

var _state: int = State.IDLE
var _quest_data: Dictionary = {}


func _ready() -> void:
	_load_quest_data()


func _load_quest_data() -> void:
	var scene_path: String = get_tree().current_scene.scene_file_path
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var text: String = file.get_as_text()
		var parsed = JSON.parse_string(text)
		if parsed is Dictionary:
			_quest_data = parsed


func on_interact(tag: String) -> void:
	if tag != "talk":
		return
	var hud = get_node("/root/Root/HUD")
	match _state:
		State.IDLE:
			_show_line(hud, "greet")
			await _wait_for_advance()
			_show_line(hud, "ask")
			_state = State.QUEST_GIVEN
		State.QUEST_GIVEN:
			var player = get_node("/root/Root/Player")
			var carried: String = player.carried_item
			var target: String = _quest_data.get("target_entity", "")
			if carried == target:
				_show_line(hud, "thank")
				_state = State.DONE
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


func _show_line(hud: Node, key: String) -> void:
	var line: String = _quest_data.get("dialogue", {}).get(key, "...")
	if hud.has_method("set_objective"):
		hud.set_objective(line)


func _emit_win() -> void:
	var win = get_node("/root/Root/WinScreen")
	if win.has_method("show_win"):
		win.show_win()
