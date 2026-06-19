# HUD — minimal heads-up display.
# Shows the current objective line and an interact prompt.
extends Control

@onready var _objective_label: Label = $ObjectiveLabel
@onready var _interact_label: Label = $InteractLabel


func set_objective(text: String) -> void:
	_objective_label.text = text


func show_interact(text: String) -> void:
	_interact_label.text = text
	_interact_label.visible = text != ""
