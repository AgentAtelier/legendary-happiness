# health.gd — CB-6 player health component.
#
# Tracks HP, receives damage, handles death + respawn.
# Attached to the Player CharacterBody3D.
# Communicates with HUD for health bar display.
extends Node

var max_health: float = 100.0
var current_health: float = 100.0
var is_dead: bool = false
var invincible_after_hit: float = 0.5  # iframes in seconds
var _invincible_timer: float = 0.0
var _respawn_position: Vector3 = Vector3.ZERO


func _ready() -> void:
	_respawn_position = get_parent().global_position


func _process(delta: float) -> void:
	if _invincible_timer > 0.0:
		_invincible_timer -= delta


func take_damage(amount: float, source: Node = null) -> void:
	"""Apply damage. Respects invincibility frames."""
	if is_dead:
		return
	if _invincible_timer > 0.0:
		return

	current_health -= amount
	_invincible_timer = invincible_after_hit

	_update_hud()

	if current_health <= 0.0:
		current_health = 0.0
		_die()
	else:
		_flash_damage()


func heal(amount: float) -> void:
	"""Heal the player, capped at max_health."""
	if is_dead:
		return
	current_health = minf(current_health + amount, max_health)
	_update_hud()


func _die() -> void:
	"""Handle player death — hide body, show death screen, trigger respawn."""
	is_dead = true
	var player = get_parent()
	player.hide()
	player.set("collision_layer", 0)
	player.set("collision_mask", 0)

	# Show death overlay via HUD
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("set_objective"):
		hud.set_objective("You have fallen. Press R to respawn.")


func _respawn() -> void:
	"""Respawn the player at the respawn point with full health."""
	is_dead = false
	current_health = max_health
	_invincible_timer = 1.0  # brief invincibility on respawn

	var player = get_parent()
	player.global_position = _respawn_position
	player.show()
	player.set("collision_layer", 1)
	player.set("collision_mask", 1)
	_update_hud()

	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("set_objective"):
		hud.set_objective("")


func _flash_damage() -> void:
	"""Brief visual feedback on taking damage."""
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("flash_damage"):
		hud.flash_damage()


func _update_hud() -> void:
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("update_health"):
		hud.update_health(current_health, max_health)


func _input(event: InputEvent) -> void:
	"""R key respawns when dead."""
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_R and is_dead:
			_respawn()
