# Pickup — attached to quest props.
# On interact, hides the prop and stores it in the player's inventory.
# FIX-5: Supports switching carried items — picking up a different
# prop restores the previously-carried prop's visibility.
extends Node3D

signal picked_up(item_id: String)


func on_interact(tag: String) -> void:
	if tag != "pickup":
		return
	var player = get_node("/root/Root/Player")

	# If player is already carrying a different item, restore its visibility
	if player.carried_item != "" and player.carried_item != name:
		var old_prop = get_node_or_null("/root/Root/" + player.carried_item)
		if old_prop:
			old_prop.show()

	player.carried_item = name
	hide()
	picked_up.emit(name)
