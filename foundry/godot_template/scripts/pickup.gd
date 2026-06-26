# Pickup — attached to quest props.
# On interact, hides the prop and stores it in the player's inventory.
# C-2: Multi-item inventory — uses player.add_item() to append to
#       carried_items array; no longer restores the previous item.
# P-B: Carry-in-view — reparents model to CarriedItem node on pickup.
# Disables collision on pickup so the prop doesn't block the player.
extends Node3D

signal picked_up(item_id: String)


func on_interact(tag: String) -> void:
	if tag != "pickup":
		return
	var player = get_node("/root/Root/Player")

	# C-2: Multi-item inventory — no need to restore previous item.
	# player.add_item() handles showing/hiding models via _show_active_model().

	# P-C-1: clear hover highlight before reparenting model
	var interaction = get_node_or_null("/root/Root/Player/Camera3D/InteractionRaycast")
	if interaction and interaction.has_method("_clear_highlight"):
		interaction._clear_highlight()
	# Move the model to the CarriedItem node (in front of camera)
	var model = null
	var carried_parent = get_node_or_null("/root/Root/Player/Camera3D/CarriedItem")
	if carried_parent:
		model = get_node_or_null("%s_model" % name)
		if model:
			# B1: Tween bounce before reparenting
			_do_pickup_bounce(model)
			model.reparent(carried_parent, false)
			# C-2: Don't show() here — player.add_item() calls _show_active_model()

	# B2: Disable any light child (OmniLight3D) so it doesn't stay glowing at origin
	var light = get_node_or_null("%s_light" % name)
	if light:
		light.visible = false

	# Disable collision so the prop doesn't block the player
	# Use set() to bypass GDScript static analysis (script extends Node3D,
	# but is attached to StaticBody3D nodes at runtime).
	set("collision_layer", 0)
	set("collision_mask", 0)
	hide()

	# C-2/B3: Use add_item() for multi-item inventory (returns false if blocked)
	var added: bool = player.add_item(name)
	if not added:
		# B3: Rollback — inventory full or too heavy, restore the prop
		if model:
			model.reparent(self, false)
		set("collision_layer", 1)
		set("collision_mask", 1)
		show()
		# Re-enable light if was on
		light = get_node_or_null("%s_light" % name)
		if light:
			light.visible = true
		return
	picked_up.emit(name)
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_pickup()


# ── B1: Pickup juice ─────────────────────────────────────────────

func _do_pickup_bounce(model: Node3D) -> void:
	"""Play a quick scale-bounce tween on the model before reparenting."""
	var tween = create_tween()
	tween.tween_property(model, "scale", Vector3(1.2, 1.2, 1.2), 0.08)
	tween.tween_property(model, "scale", Vector3(1.0, 1.0, 1.0), 0.08)
