# InteractionRaycast — raycast from camera, detects interactable objects.
# Reads _forge_tag metadata on collider nodes.
# Uses _unhandled_input for one-shot E key detection.
extends Node3D

signal interact_prompt(visible: bool, prompt_text: String)
signal object_interacted(target_node: Node3D, tag: String)

var interact_range: float = 3.0

@onready var _camera: Camera3D = get_parent() as Camera3D


func _process(_delta: float) -> void:
	var space_state: PhysicsDirectSpaceState3D = get_world_3d().direct_space_state
	var origin: Vector3 = _camera.global_position
	var end: Vector3 = origin + -_camera.global_transform.basis.z * interact_range

	var query := PhysicsRayQueryParameters3D.create(origin, end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var result: Dictionary = space_state.intersect_ray(query)

	if not result.is_empty():
		var collider: Node3D = result.collider
		var parent: Node = collider.get_parent() if collider else null
		while parent:
			if parent.has_meta("_forge_tag"):
				var tag: String = parent.get_meta("_forge_tag")
				if tag == "pickup" or tag == "talk":
					interact_prompt.emit(true, "Press E to " + tag)
					return
			parent = parent.get_parent() if parent else null

	interact_prompt.emit(false, "")


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
				var collider: Node3D = result.collider
				var parent: Node = collider.get_parent() if collider else null
				while parent:
					if parent.has_meta("_forge_tag"):
						var tag: String = parent.get_meta("_forge_tag")
						if tag == "pickup" or tag == "talk":
							if parent.has_method("on_interact"):
								parent.on_interact(tag)
							return
					parent = parent.get_parent() if parent else null
