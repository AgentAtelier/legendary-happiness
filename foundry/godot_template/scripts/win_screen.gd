# WinScreen — shown on quest completion.
# Hidden by default; show_win() makes it visible and releases the mouse.
# P-B: handles R (restart scene) and Esc (quit) keys.
# B1: screen-shake + flash on win, multi-quest win message.
extends Control

# B1: shake parameters
var _shake_intensity: float = 4.0
var _shake_duration: float = 0.4
var _original_position: Vector2


func show_win() -> void:
	visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	# B1: Screen-shake + flash on win
	_do_win_shake()
	# B1: Update win message to reflect multi-quest
	_update_win_message()


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_R:
			get_tree().reload_current_scene()
		elif event.physical_keycode == KEY_ESCAPE:
			get_tree().quit()


# ── B1: Win juice ────────────────────────────────────────────────

func _do_win_shake() -> void:
	"""Shake the WinScreen with a decaying oscillation."""
	_original_position = position
	var tween = create_tween()
	var steps := 10
	var step_dur := _shake_duration / float(steps)
	for i in range(steps):
		var decay := 1.0 - float(i) / float(steps)
		var offset := Vector2(
			randf_range(-1, 1) * _shake_intensity * decay,
			randf_range(-1, 1) * _shake_intensity * decay
		)
		tween.tween_property(self, "position", _original_position + offset, step_dur * 0.5)
		tween.tween_property(self, "position", _original_position, step_dur * 0.5)
	tween.tween_callback(_after_shake)


func _after_shake() -> void:
	position = _original_position


func _update_win_message() -> void:
	"""Update win labels to show multi-quest completion count."""
	var hud = get_node_or_null("/root/Root/HUD")
	var done := 0
	var total := 0
	if hud:
		done = hud._quests_done
		total = hud._quests_total
	var win_label = get_node_or_null("WinLabel")
	if win_label and total > 0:
		win_label.text = "All %d quests complete!" % total
	elif win_label and done > 0:
		win_label.text = "You won! (%d/%d quests)" % [done, total]
