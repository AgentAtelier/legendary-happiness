# PlayerController — first-person CharacterBody3D player.
# Works with Jolt Physics (configured in project.godot).
# WASD movement, mouse look, E for interaction, G to drop.
# Scroll wheel / 1-8 to cycle active item.
# ESC toggles mouse capture.
#
# C-2: Multi-item inventory — carried_items array + active_item_index
#       replaces the single carried_item string.
extends CharacterBody3D

# C-2: multi-item inventory
var carried_items: Array = []       # ["key_0", "book_1", ...]
var active_item_index: int = -1     # -1 when empty

var speed: float = 5.0
var mouse_sensitivity: float = 0.002
var gravity: float = 9.8
# C-1: footstep timer (throttled to avoid rapid-fire)
var _footstep_timer: float = 0.0

@onready var _camera: Camera3D = $Camera3D


func _ready() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func get_active_item() -> String:
	"""C-2: Return the currently active carried item ID, or '' if none."""
	if active_item_index >= 0 and active_item_index < carried_items.size():
		return carried_items[active_item_index]
	return ""


func add_item(item_id: String) -> void:
	"""C-2: Add an item to the inventory and make it active."""
	var idx = carried_items.find(item_id)
	if idx >= 0:
		active_item_index = idx
		_show_active_model()
		return
	carried_items.append(item_id)
	active_item_index = carried_items.size() - 1
	_show_active_model()


func remove_item(item_id: String) -> void:
	"""C-2: Remove an item from the inventory."""
	var idx = carried_items.find(item_id)
	if idx < 0:
		return
	# If this was the active item, hide its model
	if idx == active_item_index:
		_hide_all_models()
	carried_items.remove_at(idx)
	if carried_items.is_empty():
		active_item_index = -1
	elif active_item_index >= carried_items.size():
		active_item_index = carried_items.size() - 1
	if active_item_index >= 0:
		_show_active_model()
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("update_inventory"):
		hud.update_inventory(carried_items, active_item_index)


func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		else:
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * mouse_sensitivity)
		_camera.rotate_x(-event.relative.y * mouse_sensitivity)
		_camera.rotation.x = clamp(_camera.rotation.x, -PI / 2.0, PI / 2.0)
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_G:
			_drop_active_item()
		# C-2: Number keys 1-8 for direct inventory selection
		if event.physical_keycode >= KEY_1 and event.physical_keycode <= KEY_8:
			var slot = event.physical_keycode - KEY_1
			_select_slot(slot)
	# C-2: Mouse wheel to cycle active item
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			_cycle_active(1)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_cycle_active(-1)


func _physics_process(delta: float) -> void:
	var input_dir := Vector2.ZERO
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
		input_dir.y -= 1.0
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
		input_dir.y += 1.0
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
		input_dir.x -= 1.0
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
		input_dir.x += 1.0

	input_dir = input_dir.normalized()
	var direction: Vector3 = (transform.basis * Vector3(input_dir.x, 0.0, input_dir.y)).normalized()

	if direction:
		velocity.x = direction.x * speed
		velocity.z = direction.z * speed
	else:
		velocity.x = move_toward(velocity.x, 0.0, speed)
		velocity.z = move_toward(velocity.z, 0.0, speed)

	# C-1: footstep audio (throttled, only when grounded and moving)
	if direction and is_on_floor():
		_footstep_timer -= delta
		if _footstep_timer <= 0.0:
			_footstep_timer = 0.5  # ~2 steps/second at normal speed
			if has_node("/root/Audio"):
				get_node("/root/Audio").play_footstep()

	if not is_on_floor():
		velocity.y -= gravity * delta

	move_and_slide()


# ── C-2: Inventory management ────────────────────────────────────

func _select_slot(slot: int) -> void:
	"""Select inventory slot by index (0-7)."""
	if carried_items.is_empty() or slot >= carried_items.size():
		return
	if slot == active_item_index:
		return
	active_item_index = slot
	_show_active_model()
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("update_inventory"):
		hud.update_inventory(carried_items, active_item_index)


func _cycle_active(direction: int) -> void:
	"""Cycle active item: direction=+1 (next), -1 (prev)."""
	if carried_items.size() <= 1:
		return
	active_item_index = posmod(active_item_index + direction, carried_items.size())
	_show_active_model()
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("update_inventory"):
		hud.update_inventory(carried_items, active_item_index)


func _show_active_model() -> void:
	"""Show only the active item's model in the CarriedItem node."""
	_hide_all_models()
	var active_id = get_active_item()
	if active_id == "":
		return
	var model = get_node_or_null(
		"Camera3D/CarriedItem/%s_model" % active_id
	)
	if model:
		model.show()


func _hide_all_models() -> void:
	"""Hide all models in the CarriedItem node."""
	var carried = $Camera3D/CarriedItem
	for child in carried.get_children():
		child.hide()


# ── Drop ─────────────────────────────────────────────────────────

func _drop_active_item() -> void:
	"""C-2: Drop the active carried item on the floor."""
	var active_id = get_active_item()
	if active_id == "":
		return
	var prop = get_node_or_null("/root/Root/" + active_id)
	if not prop:
		remove_item(active_id)
		return
	# Restore the model to the prop
	var carried = $Camera3D/CarriedItem
	var model = carried.get_node_or_null("%s_model" % active_id)
	if model:
		model.reparent(prop, false)
	# Make the prop visible again, place it in front of player
	prop.show()
	var drop_pos: Vector3 = global_position + (-global_transform.basis.z * 1.5)
	drop_pos.y = prop.position.y
	prop.global_position = drop_pos
	# Re-enable collision
	prop.set("collision_layer", 1)
	prop.set("collision_mask", 1)
	remove_item(active_id)
