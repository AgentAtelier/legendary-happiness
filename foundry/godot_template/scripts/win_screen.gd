# WinScreen — shown on quest completion.
# Hidden by default; show_win() makes it visible and releases the mouse.
# P-B: handles R (restart scene) and Esc (quit) keys.
extends Control


func show_win() -> void:
	visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_R:
			get_tree().reload_current_scene()
		elif event.physical_keycode == KEY_ESCAPE:
			get_tree().quit()
