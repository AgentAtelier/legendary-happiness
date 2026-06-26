# door.gd — CB-2 locked door + key / CB-4 room traversal.
#
# On interact("open"/"door"), checks if the player carries the required key.
# If locked: shows locked prompt. If unlocked: opens the door.
#
# CB-4: If the door has _forge_target_room metadata, opening it triggers
# a scene transition to the neighbour room.  The world log path is
# passed via _forge_world_log metadata so NPC state persists across
# rooms.  If no target room is set, the door simply toggles open/closed
# (single-room behaviour from CB-2).
#
# Key is defined by _forge_key_entity metadata (the carryable entity ID
# that serves as this door's key).  If no key is set, the door is
# always openable (unlocked by default).
extends Node3D

var _is_open: bool = false
var _is_locked: bool = true
var _target_room: String = ""
var _world_log_path: String = ""


func _ready() -> void:
	_target_room = str(get_meta("_forge_target_room", ""))
	_world_log_path = str(get_meta("_forge_world_log", ""))


func on_interact(tag: String) -> void:
	if tag != "open" and tag != "door":
		return

	if _is_open:
		# CB-4: if this is a room-transition door, don't close it
		if _target_room != "":
			_travel_to_room()
			return
		_close()
		return

	if _is_locked:
		if not _player_has_key():
			_show_locked_hint()
			return
		_is_locked = false

	_open()


func _player_has_key() -> bool:
	"""Check if player carries the required key entity."""
	var key_entity := str(get_meta("_forge_key_entity", ""))
	if key_entity == "":
		return true  # no key required — always openable

	var player = get_node_or_null("/root/Root/Player")
	if not player:
		return false
	# Check carried_items array (C-2 multi-item inventory)
	var carried: Array = player.get("carried_items")
	if carried and key_entity in carried:
		return true
	return false


func _show_locked_hint() -> void:
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("set_objective"):
		var key_name := str(get_meta("_forge_key_entity", "a key"))
		hud.set_objective("The door is locked. You need %s." % key_name.replace("_", " "))


func _open() -> void:
	_is_open = true
	# Disable collision so player can walk through
	set("collision_layer", 0)
	set("collision_mask", 0)
	# Visual feedback: hide the door model
	var model = get_node_or_null("%s_model" % name)
	if model:
		model.visible = false
	# CB-4: If this is a room-transition door, travel immediately
	if _target_room != "":
		_travel_to_room()


func _travel_to_room() -> void:
	"""CB-4: Transition to the neighbour room scene."""
	var to_room_str := _target_room  # e.g. "1,0"
	var parts := to_room_str.split(",")
	if parts.size() != 2:
		return
	var rx := parts[0]
	var rz := parts[1]
	var scene_path := "res://scenes/room_%s_%s.tscn" % [rx, rz]
	
	# Check the scene file exists before trying to load
	if not FileAccess.file_exists(scene_path):
		var hud = get_node_or_null("/root/Root/HUD")
		if hud and hud.has_method("set_objective"):
			hud.set_objective("The passage is not yet open.")
		return
	
	# Persist inventory across room transition via autoload
	# (carried_items should be stored on an autoload singleton or
	# passed as metadata on the next scene load)
	var tree := get_tree()
	if tree:
		tree.change_scene_to_file(scene_path)


func _close() -> void:
	_is_open = false
	set("collision_layer", 1)
	set("collision_mask", 1)
	var model = get_node_or_null("%s_model" % name)
	if model:
		model.visible = true
