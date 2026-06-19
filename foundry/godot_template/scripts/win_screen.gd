# WinScreen — shown on quest completion.
# Hidden by default; show_win() makes it visible and releases the mouse.
extends Control


func show_win() -> void:
	visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
