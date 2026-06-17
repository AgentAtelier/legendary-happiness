@tool
extends EditorPlugin

var panel_instance

func _enter_tree():
	print("DevForge AI plugin loaded")

	var panel_scene = preload("res://addons/devforge_ai/devforge_panel.tscn")
	panel_instance = panel_scene.instantiate()

	add_control_to_dock(DOCK_SLOT_RIGHT_UL, panel_instance)


func _exit_tree():
	print("DevForge AI plugin unloaded")

	if panel_instance:
		remove_control_from_docks(panel_instance)
