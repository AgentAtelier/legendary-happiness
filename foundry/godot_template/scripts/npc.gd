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
			await get_tree().create_timer(2.0).timeout
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
		State.DONE:
			_show_line(hud, "thank")


func _show_line(hud: Node, key: String) -> void:
	var line: String = _quest_data.get("dialogue", {}).get(key, "...")
	if hud.has_method("set_objective"):
		hud.set_objective(line)


func _emit_win() -> void:
	var win = get_node("/root/Root/WinScreen")
	if win.has_method("show_win"):
		win.show_win()
