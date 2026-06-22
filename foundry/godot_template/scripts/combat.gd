# combat.gd — CB-6 melee combat system.
#
# Attached to the Player CharacterBody3D (alongside health.gd).
# Handles left-click swing, hit detection via Area3D, damage
# application to enemies, and skill XP gain on hit/kill.
#
# Communicates with health.gd on the player for damage output,
# and with enemy.gd on hit targets for damage input.
extends Node

var _can_swing: bool = true
var _swing_cooldown: float = 0.5       # base cooldown between swings
var _swing_range: float = 2.0          # reach of the melee attack
var _swing_angle: float = 60.0         # hit cone half-angle in degrees
var _base_damage: float = 10.0         # base damage per swing

# Skill bonuses (set from skills system)
var _combat_level: int = 0
var _damage_mult: float = 1.0


func _ready() -> void:
	_recalc_from_skills()


func _recalc_from_skills() -> void:
	"""Update combat stats from skill level."""
	_damage_mult = 1.0 + _combat_level * 0.01
	if _combat_level >= 25:  # power_attack
		_swing_cooldown = 0.5 * 0.8  # 20% faster
	if _combat_level >= 10:  # quick_slash
		_swing_cooldown *= 0.85  # additional 15% faster


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_LEFT:
			_swing()


func _swing() -> void:
	"""Execute a melee swing in front of the camera."""
	if not _can_swing:
		return
	var health_node = get_parent().get_node_or_null("Health")
	if health_node and health_node.is_dead:
		return

	_can_swing = false

	# Detect hit targets in front of the camera
	var camera: Camera3D = get_parent().get_node_or_null("Camera3D")
	if not camera:
		await _reset_swing()
		return

	# Use a short-range Area3D or raycast for hit detection
	var space_state = get_parent().get_world_3d().direct_space_state
	var origin: Vector3 = camera.global_position
	var forward: Vector3 = -camera.global_transform.basis.z * _swing_range
	var query := PhysicsRayQueryParameters3D.create(origin, origin + forward)
	query.collision_mask = 1  # layer 1 = default
	query.exclude = [get_parent().get_rid()]  # don't hit self
	var result := space_state.intersect_ray(query)

	if result and result.has("collider"):
		var target = result["collider"]
		if target.has_method("take_damage"):
			var damage := _base_damage * _damage_mult
			target.take_damage(damage, get_parent())
			_on_hit_target(target, damage)

	await _reset_swing()


func _on_hit_target(target: Node, damage: float) -> void:
	"""Award combat XP and show hit feedback."""
	# Skill XP gain — guard against missing Skills node
	var skills_node = get_parent().get_node_or_null("Skills")
	if skills_node != null and skills_node.has_method("award_combat_xp"):
		var is_kill := false
		if target.has_method("is_dead"):
			is_kill = target.is_dead()
		skills_node.award_combat_xp(is_kill)

	# Hit marker on HUD — guard against missing method
	var hud = get_node_or_null("/root/Root/HUD")
	if hud != null and hud.has_method("show_hit_marker"):
		hud.show_hit_marker(damage)


func _reset_swing() -> void:
	await get_tree().create_timer(_swing_cooldown).timeout
	_can_swing = true


func set_combat_level(level: int) -> void:
	"""Called by skills.gd when combat level changes."""
	_combat_level = level
	_recalc_from_skills()
