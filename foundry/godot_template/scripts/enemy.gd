# enemy.gd — CB-6 enemy entity (golem archetype).
#
# NOT an extension of npc.gd — a separate entity type with:
#   - Approach AI (walk toward player when in aggro range)
#   - Melee attack on contact (damage cooldown)
#   - Health tracking + death (queue_free on death)
#   - NavigationAgent3D for pathfinding
#
# The enemy reads its stats from metadata emitted by scene_compiler:
#   _forge_enemy_health, _forge_enemy_damage, _forge_enemy_archetype
extends CharacterBody3D

var _health: float = 50.0
var _max_health: float = 50.0
var _damage: float = 8.0
var _aggro_range: float = 8.0
var _attack_range: float = 1.5
var _attack_cooldown: float = 1.2
var _speed: float = 2.5
var _archetype: String = "golem"
var _is_dead: bool = false
var _attack_timer: float = 0.0
var _nav_agent: NavigationAgent3D = null
var _player: Node = null
var _idle_timer: float = 0.0
var _idle_target: Vector3 = Vector3.ZERO
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()


func _ready() -> void:
	_read_metadata()
	_setup_navigation()
	_player = get_node_or_null("/root/Root/Player")
	# Seed RNG from name hash for deterministic per-entity behavior
	_rng.seed = name.hash()


func _read_metadata() -> void:
	if has_meta("_forge_enemy_health"):
		_health = float(get_meta("_forge_enemy_health"))
		_max_health = _health
	if has_meta("_forge_enemy_damage"):
		_damage = float(get_meta("_forge_enemy_damage"))
	if has_meta("_forge_enemy_archetype"):
		_archetype = str(get_meta("_forge_enemy_archetype"))
	if has_meta("_forge_enemy_aggro"):
		_aggro_range = float(get_meta("_forge_enemy_aggro"))
	if has_meta("_forge_enemy_speed"):
		_speed = float(get_meta("_forge_enemy_speed"))


func _setup_navigation() -> void:
	_nav_agent = NavigationAgent3D.new()
	_nav_agent.agent_radius = 0.3
	_nav_agent.agent_height = 2.0
	_nav_agent.max_speed = _speed
	add_child(_nav_agent)


func _physics_process(delta: float) -> void:
	if _is_dead:
		return

	_attack_timer = maxf(0.0, _attack_timer - delta)

	if not _player:
		return

	var dist_to_player: float = global_position.distance_to(_player.global_position)

	if dist_to_player <= _aggro_range:
		# Aggro: pursue player
		if dist_to_player <= _attack_range:
			_attack_player()
		else:
			_navigate_to(_player.global_position, delta)
	else:
		# Idle: wander in place
		_idle_wander(delta)


func _navigate_to(target: Vector3, delta: float) -> void:
	"""Move toward target using NavigationAgent3D."""
	if not _nav_agent:
		return
	_nav_agent.target_position = target
	var next_pos := _nav_agent.get_next_path_position()
	var direction := (next_pos - global_position).normalized()
	velocity = direction * _speed
	move_and_slide()

	# Face the player
	var look_dir := (_player.global_position - global_position).normalized()
	look_dir.y = 0.0
	if look_dir.length() > 0.01:
		look_at(global_position + look_dir, Vector3.UP)


func _idle_wander(delta: float) -> void:
	"""CB-3: Simple idle wander when not aggroed (seeded RNG)."""
	_idle_timer -= delta
	if _idle_timer <= 0.0:
		# Pick a new random nearby position (seeded per-entity)
		_idle_timer = _rng.randf_range(2.0, 5.0)
		var offset := Vector3(
			_rng.randf_range(-3.0, 3.0),
			0.0,
			_rng.randf_range(-3.0, 3.0),
		)
		_idle_target = global_position + offset

	if _nav_agent:
		_nav_agent.target_position = _idle_target
		var next_pos := _nav_agent.get_next_path_position()
		var direction := (next_pos - global_position).normalized()
		velocity = direction * _speed * 0.4  # slower when idle
		move_and_slide()


func _attack_player() -> void:
	"""Melee attack the player if cooldown permits."""
	if _attack_timer > 0.0:
		return
	if not _player:
		return

	# Check if player has a health node
	var player_health = _player.get_node_or_null("Health")
	if not player_health:
		return

	player_health.take_damage(_damage, self)
	_attack_timer = _attack_cooldown


func take_damage(amount: float, source: Node = null) -> void:
	"""Receive damage from player combat."""
	if _is_dead:
		return

	_health -= amount
	_flash_hurt()

	if _health <= 0.0:
		_health = 0.0
		_die()


func _flash_hurt() -> void:
	"""Brief visual feedback on taking damage."""
	# Flash red tint
	var body = get_node_or_null("Body")
	if body:
		body.modulate = Color(1.0, 0.3, 0.3, 1.0)
		await get_tree().create_timer(0.15).timeout
		if body:
			body.modulate = Color(1.0, 1.0, 1.0, 1.0)


func _die() -> void:
	"""Handle enemy death — disable, then free after delay."""
	_is_dead = true
	visible = false
	set("collision_layer", 0)
	set("collision_mask", 0)

	# Drop loot particle effect
	_spawn_death_particles()

	# Free after short delay
	await get_tree().create_timer(2.0).timeout
	queue_free()


func _spawn_death_particles() -> void:
	"""Spawn a brief particle burst on death."""
	var particles := CPUParticles3D.new()
	particles.emitting = false
	particles.one_shot = true
	particles.amount = 20
	particles.lifetime = 0.8
	particles.explosiveness = 1.0
	particles.direction = Vector3(0, 1, 0)
	particles.spread = 45.0
	particles.gravity = Vector3(0, -3.0, 0)
	particles.initial_velocity_min = 1.5
	particles.initial_velocity_max = 4.0
	particles.scale_amount_min = 0.05
	particles.scale_amount_max = 0.15
	particles.color = Color(0.6, 0.3, 0.2, 0.7)
	particles.finish_color = Color(0.6, 0.3, 0.2, 0.0)
	particles.position = global_position
	get_parent().add_child(particles)
	particles.emitting = true
	await get_tree().create_timer(0.9).timeout
	particles.queue_free()


func is_dead() -> bool:
	return _is_dead
