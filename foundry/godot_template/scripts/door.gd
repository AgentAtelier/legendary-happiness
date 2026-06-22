# door.gd — CB-2 locked door + key.
#
# On interact("open"), checks if the player carries the required key.
# If locked: shows locked prompt. If unlocked: toggles open/closed
# (disables collision when open so the player can walk through).
#
# Key is defined by _forge_key_entity metadata (the carryable entity ID
# that serves as this door's key).  If no key is set, the door is
# always openable (unlocked by default).
extends Node3D

var _is_open: bool = false
var _is_locked: bool = true


func on_interact(tag: String) -> void:
	if tag != "open" and tag != "door":
		return

	if _is_open:
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


func _close() -> void:
	_is_open = false
	set("collision_layer", 1)
	set("collision_mask", 1)
	var model = get_node_or_null("%s_model" % name)
	if model:
		model.visible = true
