# container.gd — CB-2 openable container (chest, cabinet, wardrobe).
#
# On interact("open"), toggles open/close.  When opened, spawns the
# container's contents as physics props near the container so the
# player can pick them up.
#
# Contents are defined by _forge_contents metadata (comma-separated
# carryable entity IDs).  For quest-generated containers, the contents
# can be set to the quest's target entity.
extends Node3D

var _is_open: bool = false
var _contents_spawned: bool = false
var _spawned_nodes: Array = []  # CB-2 fix: track spawned nodes for cleanup


func on_interact(tag: String) -> void:
	if tag != "open":
		return
	if _is_open:
		# Close — remove spawned contents
		_remove_contents()
		_is_open = false
	else:
		# Open — spawn contents as RigidBody3D props
		_spawn_contents()
		_is_open = true


func _get_contents() -> Array:
	"""Read _forge_contents metadata (comma-separated IDs)."""
	var raw: String = str(get_meta("_forge_contents", ""))
	if raw.strip_edges() == "":
		return []
	var items: Array = []
	for token in raw.split(","):
		var tid = token.strip_edges()
		if tid != "":
			items.append(tid)
	return items


func _spawn_contents() -> void:
	if _contents_spawned:
		return
	var items := _get_contents()
	if items.is_empty():
		return

	var root = get_node_or_null("/root/Root")
	if not root:
		return

	const COLLISION: Dictionary = {
		"key": Vector3(0.12, 0.01, 0.06),
		"book": Vector3(0.25, 0.05, 0.2),
		"cup": Vector3(0.16, 0.15, 0.16),
		"gem": Vector3(0.08, 0.08, 0.08),
		"bottle": Vector3(0.14, 0.22, 0.14),
		"scroll": Vector3(0.06, 0.05, 0.25),
		"coin-pouch": Vector3(0.15, 0.1, 0.12),
		"candle": Vector3(0.1, 0.15, 0.1),
		"dagger": Vector3(0.25, 0.04, 0.06),
		"ring": Vector3(0.07, 0.03, 0.07),
	}

	var base_pos: Vector3 = global_position + Vector3(0, 0.3, 0.8)

	for i in range(items.size()):
		var item_id: String = items[i]
		var proj := RigidBody3D.new()
		proj.name = item_id
		proj.collision_layer = 1
		proj.collision_mask = 1
		proj.global_position = base_pos + Vector3(0.15 * (i % 3), 0.1 * i, -0.15 * (i / 3))

		# Add collision shape
		var cat := _infer_category(item_id)
		var size: Vector3 = COLLISION.get(cat, Vector3(0.15, 0.15, 0.15))
		var shape := CollisionShape3D.new()
		var box := BoxShape3D.new()
		box.size = size
		shape.shape = box
		proj.add_child(shape)

		# Add metadata so interaction.gd picks it up as a pickup
		proj.set_meta("_forge_tag", "pickup")
		proj.set_meta("_forge_category", cat)

		root.add_child(proj)
		_spawned_nodes.append(proj)  # CB-2: track for cleanup

		# Slight upward impulse
		proj.apply_central_impulse(Vector3(0, 1.5, 0) + Vector3(randf_range(-0.5, 0.5), 0, randf_range(-0.5, 0.5)))

	_contents_spawned = true


func _remove_contents() -> void:
	# CB-2 fix: only remove nodes this container spawned
	for c in _spawned_nodes:
		if is_instance_valid(c):
			c.queue_free()
	_spawned_nodes.clear()
	_contents_spawned = false


func _infer_category(item_id: String) -> String:
	"""Infer category from item_id (e.g. 'worn_oak_key_3' → 'key')."""
	var parts := item_id.split("_")
	if parts.size() >= 2 and parts[-1].is_valid_int():
		return "_".join(parts.slice(1, -1))
	var found: String = ""
	for known in ["key", "book", "cup", "gem", "bottle", "scroll", "candle", "dagger", "ring"]:
		if known in item_id:
			return known
	return "book"
