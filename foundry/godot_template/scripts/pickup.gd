# Pickup — attached to quest props.
# On interact, hides the prop and stores it in the player's inventory.
# FIX-5: Supports switching carried items — picking up a different
# prop restores the previously-carried prop's visibility.
# P-B: Carry-in-view — reparents model to CarriedItem node on pickup.
# Disables collision on pickup so the prop doesn't block the player.
extends Node3D

signal picked_up(item_id: String)


func on_interact(tag: String) -> void:
	if tag != "pickup":
		return
	var player = get_node("/root/Root/Player")

	# If player is already carrying a different item, restore its model
	if player.carried_item != "" and player.carried_item != name:
		_restore_to_world(player.carried_item)

	# P-C-1: clear hover highlight before reparenting model
	var interaction = get_node_or_null("/root/Root/Player/Camera3D/InteractionRaycast")
	if interaction and interaction.has_method("_clear_highlight"):
		interaction._clear_highlight()
	# Move the model to the CarriedItem node (in front of camera)
	var carried_parent = get_node_or_null("/root/Root/Player/Camera3D/CarriedItem")
	if carried_parent:
		var model = get_node_or_null("%s_model" % name)
		if model:
			model.reparent(carried_parent, false)
			model.show()

	# Disable collision so the prop doesn't block the player
	# Use set() to bypass GDScript static analysis (script extends Node3D,
	# but is attached to StaticBody3D nodes at runtime).
	set("collision_layer", 0)
	set("collision_mask", 0)
	hide()

	player.carried_item = name
	picked_up.emit(name)
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_pickup()


func _restore_to_world(prop_name: String) -> void:
	"""Restore a previously-carried prop's model to its original parent."""
	var prop = get_node_or_null("/root/Root/" + prop_name)
	if not prop:
		return
	var model = get_node_or_null(
		"/root/Root/Player/Camera3D/CarriedItem/%s_model" % prop_name
	)
	if model and is_instance_valid(model):
		model.reparent(prop, false)
	# Re-enable collision
	prop.set("collision_layer", 1)
	prop.set("collision_mask", 1)
	prop.show()
