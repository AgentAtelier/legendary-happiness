# InteractionRaycast — raycast from camera, detects interactable objects.
# Reads _forge_tag metadata on collider nodes.
# Uses _unhandled_input for one-shot E key detection.
# P-B: named prompts (e.g. "Press E to pick up the table")
# P-C-1: highlights the hovered interactable with emissive material overlay
extends Node3D

signal interact_prompt(visible: bool, prompt_text: String)
signal object_interacted(target_node: Node3D, tag: String)

var interact_range: float = 3.0

@onready var _camera: Camera3D = get_parent() as Camera3D

# P-C-1: hover highlight state
var _hovered_node: Node = null
var _highlight_material: StandardMaterial3D = null


func _ready() -> void:
	# Create a reusable highlight material (emissive yellow overlay)
	_highlight_material = StandardMaterial3D.new()
	_highlight_material.emission_enabled = true
	_highlight_material.emission = Color(1.0, 0.9, 0.2, 1.0)
	_highlight_material.emission_energy_multiplier = 0.5
	_highlight_material.transparency = BaseMaterial3D.Transparency.TRANSPARENCY_ALPHA
	_highlight_material.albedo_color = Color(1, 1, 0, 0.0)


func _process(_delta: float) -> void:
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range

	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)

	if not result.is_empty():
		# intersect_ray returns the CollisionObject3D (e.g. StaticBody3D),
		# not the CollisionShape3D child.  Start from the collider itself.
		var current: Node = result.collider as Node
		while current:
			if current.has_meta("_forge_tag"):
				var tag: String = current.get_meta("_forge_tag")
				if tag == "pickup" or tag == "talk":
					var prompt_text: String = _build_prompt(current, tag)
					interact_prompt.emit(true, prompt_text)
					# P-C-1: highlight the hovered node
					_highlight(current)
					return
			current = current.get_parent()

	interact_prompt.emit(false, "")
	# P-C-1: clear highlight when not looking at anything interactable
	_clear_highlight()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.physical_keycode == KEY_E:
		if event.pressed and not event.echo:
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
						if tag == "pickup" or tag == "talk":
							if current.has_method("on_interact"):
								current.on_interact(tag)
							return
					current = current.get_parent()


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
