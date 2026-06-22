# InteractionRaycast — raycast from camera, detects interactable objects.
# Reads _forge_tag metadata on collider nodes.
# Uses _unhandled_input for one-shot E key detection.
# P-B: named prompts (e.g. "Press E to pick up the table")
# P-C-1: highlights the hovered interactable with emissive material overlay
extends Node3D

signal interact_prompt(visible: bool, prompt_text: String, tag: String)
signal object_interacted(target_node: Node3D, tag: String)

var interact_range: float = 3.0

@onready var _camera: Camera3D = get_parent() as Camera3D

# P-C-1: hover highlight state
var _hovered_node: Node = null
var _highlight_material: StandardMaterial3D = null
# B1: cached quest_data for target glow (avoid disk I/O every frame)
var _cached_quest_data: Dictionary = {}


func _ready() -> void:
	# Create a reusable highlight material (emissive yellow overlay)
	_highlight_material = StandardMaterial3D.new()
	_highlight_material.emission_enabled = true
	_highlight_material.emission = Color(1.0, 0.9, 0.2, 1.0)
	_highlight_material.emission_energy_multiplier = 0.5
	_highlight_material.transparency = BaseMaterial3D.Transparency.TRANSPARENCY_ALPHA
	_highlight_material.albedo_color = Color(1, 1, 0, 0.0)
	# B1: Cache quest_data once (avoid disk I/O every frame)
	_cache_quest_data()


func _process(_delta: float) -> void:
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range

	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)

	if not result.is_empty():
		var current: Node = result.collider as Node
		while current:
			if current.has_meta("_forge_tag"):
				var tag: String = current.get_meta("_forge_tag")
				if tag == "pickup" or tag == "talk" or tag == "open" or tag == "door":
					var prompt_text: String = _build_prompt(current, tag)
					interact_prompt.emit(true, prompt_text, tag)
					# P-C-1: highlight the hovered node
					_highlight(current)
					# B1: Reticle color update
					_update_reticle(tag)
					# B1: Tooltip label
					_show_tooltip(current, tag)
					# B1: Persistent target glow for active quest targets
					_update_target_glow()
					return
			current = current.get_parent()

	# CB-2: Check for place surface when carrying an item (before falling through)
	if _check_place_surface():
		return
	interact_prompt.emit(false, "", "")
	# P-C-1: clear highlight when not looking at anything interactable
	_clear_highlight()
	# B1: Reset reticle to default
	_update_reticle("")
	# B1: Hide tooltip
	_show_tooltip(null, "")
	# B1: Still update target glow even when not hovering
	_update_target_glow()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.physical_keycode == KEY_E:
		if event.pressed and not event.echo:
			# CB-2: Check for place-surface first (player carrying item + looking at surface)
			var player = get_node_or_null("/root/Root/Player")
			if player and str(player.get_active_item()) != "":
				_place_item_on_surface()
			# Check what we're looking at and fire interaction
			var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
			var origin: Vector3 = _camera.global_position
			var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range
			var query := PhysicsRayQueryParameters3D.create(origin, end)
			query.collide_with_areas = true
			query.collide_with_bodies = true
			var result: Dictionary = space_state.intersect_ray(query)
			if not result.is_empty():
				# intersect_ray returns the CollisionObject3D, start from it
				var current: Node = result.collider as Node
				while current:
					if current.has_meta("_forge_tag"):
						var tag: String = current.get_meta("_forge_tag")
						if tag == "pickup" or tag == "talk" or tag == "open" or tag == "door":
							if current.has_method("on_interact"):
								current.on_interact(tag)
							return
					current = current.get_parent()
	if event is InputEventKey and event.physical_keycode == KEY_X:
		if event.pressed and not event.echo:
			# EB-6: Examine — show flavour text for the looked-at prop/NPC
			_examine()


# ── EB-6: Examine action ───────────────────────────────────────

func _examine() -> void:
	"""Look at whatever prop/NPC the player is hovering and show its
	flavour text on the HUD subtitle panel."""
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range
	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)
	if result.is_empty():
		return
	var current: Node = result.collider as Node
	while current:
		if current.has_meta("_forge_tag"):
			# Build the flavour line from cached quest_data
			var line: String = _get_examine_line(current.name)
			if line != "":
				var hud = get_node_or_null("/root/Root/HUD")
				if hud and hud.has_method("push_subtitle"):
					hud.push_subtitle(line)
			return
		current = current.get_parent()


func _get_examine_line(prop_id: String) -> String:
	"""Read the examine flavour text for *prop_id* from cached quest_data."""
	var examine_map = _cached_quest_data.get("examine", {})
	if examine_map is Dictionary:
		var line: String = str(examine_map.get(prop_id, ""))
		if line != "":
			return "[Examine] " + line
	return ""


func _build_prompt(node: Node, tag: String) -> String:
	"""Build a named interact prompt using node metadata."""
	if tag == "pickup":
		var category: String = ""
		if node.has_meta("_forge_category"):
			category = node.get_meta("_forge_category")
		if category != "":
			return "Press E to pick up the %s" % category
		return "Press E to pick up"
	if tag == "talk":
		var role: String = ""
		if node.has_meta("_forge_role"):
			role = node.get_meta("_forge_role")
		if role != "":
			return "Press E to talk to the %s" % role
		return "Press E to talk"
	if tag == "open":
		return "Press E to open"
	if tag == "door":
		return "Press E to open the door"
	return "Press E"


# ── P-C-1: Hover highlight ────────────────────────────────────────

func _highlight(node: Node) -> void:
	"""Apply emissive material overlay to the hovered node's model."""
	if node == _hovered_node:
		return
	_clear_highlight()
	_hovered_node = node
	var model = node.get_node_or_null("%s_model" % node.name)
	if model is MeshInstance3D:
		model.material_overlay = _highlight_material


func _clear_highlight() -> void:
	"""Remove highlight from the previously-hovered node."""
	if _hovered_node:
		var model = _hovered_node.get_node_or_null("%s_model" % _hovered_node.name)
		if model is MeshInstance3D:
			model.material_overlay = null
		_hovered_node = null


# ── B1: Reticle + tooltip + target glow ──────────────────────────

func _update_reticle(tag: String) -> void:
	"""Set crosshair color based on hovered tag."""
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("set_crosshair_style"):
		hud.set_crosshair_style(tag)


func _show_tooltip(node: Node, tag: String) -> void:
	"""Show a floating tooltip for the hovered interactable."""
	var hud = get_node_or_null("/root/Root/HUD")
	if not hud or not hud.has_method("show_tooltip"):
		return
	if node == null or tag == "":
		hud.show_tooltip("")
		return
	var text: String = ""
	if tag == "pickup":
		var cat: String = ""
		if node.has_meta("_forge_category"):
			cat = node.get_meta("_forge_category")
		text = cat.capitalize().replace("_", " ")
	elif tag == "talk":
		var role: String = ""
		if node.has_meta("_forge_role"):
			role = node.get_meta("_forge_role")
		text = role.capitalize()
	if text != "":
		hud.show_tooltip(text)


func _update_target_glow() -> void:
	"""Apply persistent emissive highlight to all active quest targets.

	When an NPC is in QUEST_GIVEN state (state=1), their target_entity
	prop should glow so the player can find it.
	B1-fix: Uses cached quest_data (read once in _cache_quest_data)."""
	var root = get_node_or_null("/root/Root")
	if not root:
		return
	var npcs = _cached_quest_data.get("npcs", {})
	if not npcs is Dictionary:
		return

	# Build set of target entity IDs that have active quests
	var active_targets: Array[String] = []
	var all_nodes: Array = []
	_collect_all_nodes(root, all_nodes)
	for n in all_nodes:
		if n.has_meta("_forge_tag") and n.get_meta("_forge_tag") == "talk":
			var npc_id = str(n.get_meta("_forge_npc_id", ""))
			if npc_id != "" and int(n._state) == 1:  # QUEST_GIVEN
				var npc_data = npcs.get(npc_id, {})
				var tid = str(npc_data.get("target_entity", ""))
				if tid != "" and not active_targets.has(tid):
					active_targets.append(tid)

	# Apply glow to active targets, remove from inactive
	for n in all_nodes:
		if n.has_meta("_forge_tag") and n.get_meta("_forge_tag") == "pickup":
			var model = n.get_node_or_null("%s_model" % n.name)
			if model is MeshInstance3D:
				if n.name in active_targets:
					# Only apply if not already highlighted as hovered
					if n != _hovered_node and model.material_overlay == null:
						model.material_overlay = _highlight_material
				else:
					# Only remove if it's our persistent glow (not hover)
					if n != _hovered_node and model.material_overlay == _highlight_material:
						model.material_overlay = null


func _cache_quest_data() -> void:
	"""B1: Read quest_data.json once and cache it."""
	var scene_path: String = get_tree().current_scene.scene_file_path
	if scene_path == "":
		return
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var parsed = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			_cached_quest_data = parsed


# ── CB-2: Place-on-surface detection ─────────────────────────────

func _check_place_surface() -> bool:
	"""Check if the player is looking at a place surface while carrying.

	Returns true if a place prompt was emitted (preempting other prompts).
	On E press during a place hover, places the held item on the surface."""
	var player = get_node_or_null("/root/Root/Player")
	if not player:
		return false
	var held: String = str(player.get_active_item())
	if held == "":
		return false

	# Raycast to see if we're looking at a surface-tagged furniture
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range
	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)
	if result.is_empty():
		return false

	var current: Node = result.collider as Node
	while current:
		if current.has_meta("_forge_surface_tag") and current.get_meta("_forge_surface_tag") == "place":
			var cat: String = str(current.get_meta("_forge_category", "furniture"))
			var prompt: String = "Press E to place on the %s" % cat.replace("_", " ")
			interact_prompt.emit(true, prompt, "place")
			_highlight(current)
			return true
		current = current.get_parent()

	return false


func _place_item_on_surface() -> void:
	"""Place the player's held item on the looked-at surface.

	Called from _unhandled_input when a place-surface is hovered."""
	var player = get_node_or_null("/root/Root/Player")
	if not player:
		return
	var held: String = str(player.get_active_item())
	if held == "":
		return

	# Find the target surface
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range
	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)
	if result.is_empty():
		return

	var current: Node = result.collider as Node
	while current:
		if current.has_meta("_forge_surface_tag") and current.get_meta("_forge_surface_tag") == "place":
			# Get surface Y from metadata
			var surface_y: float = float(current.get_meta("_forge_surface_y", 0.8))
			var surface_pos := current.global_position

			# Drop the item on the surface
			var prop = get_node_or_null("/root/Root/" + held)
			if not prop:
				return

			# Restore model to prop
			var carried = player.get_node_or_null("Camera3D/CarriedItem")
			var model = carried.get_node_or_null("%s_model" % held) if carried else null
			if model:
				model.reparent(prop, false)

			prop.show()
			prop.global_position = Vector3(surface_pos.x, surface_y, surface_pos.z)
			prop.set("collision_layer", 1)
			prop.set("collision_mask", 1)

			# CB-1: Try to complete a place quest
			var qm = get_node_or_null("/root/QuestManager")
			if qm and qm.has_method("try_complete_place"):
				if qm.try_complete_place(held, current.name):
					var hud = get_node_or_null("/root/Root/HUD")
					if hud and hud.has_method("set_objective"):
						hud.set_objective("Placed %s on %s!" % [held.replace("_", " "), current.name.replace("_", " ")])

			# Remove from player inventory
			if player.has_method("remove_item"):
				player.remove_item(held)

			return
		current = current.get_parent()


func _collect_all_nodes(node, out: Array) -> void:
	out.append(node)
	for child in node.get_children():
		_collect_all_nodes(child, out)
