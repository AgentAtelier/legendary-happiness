# HUD — minimal heads-up display.
# Shows the current objective line, an interact prompt, and
# C-2: an inventory list on the right side.
extends Control

@onready var _objective_label: Label = $ObjectiveLabel
@onready var _interact_label: Label = $InteractLabel
@onready var _inventory_label: Label = $InventoryLabel


func set_objective(text: String) -> void:
	_objective_label.text = text


func show_interact(text: String) -> void:
	_interact_label.text = text
	_interact_label.visible = text != ""


# ── C-2: Inventory display ──────────────────────────────────────────

func update_inventory(items: Array, active_index: int) -> void:
	"""Render the inventory list with > marker on the active item."""
	if not _inventory_label:
		return
	var lines: PackedStringArray = []
	if items.is_empty():
		_inventory_label.text = ""
		return
	for i in range(items.size()):
		var item_id: String = items[i]
		# Strip trailing _N suffix for display (e.g. "key_0" → "key")
		var display_name: String = _display_name(item_id)
		if i == active_index:
			lines.append("> %s" % display_name)
		else:
			lines.append("  %s" % display_name)
	_inventory_label.text = "\n".join(lines)


func _display_name(item_id: String) -> String:
	"""Convert an item ID like 'golden_key_3' to a readable name."""
	# Remove trailing _N suffix
	var result: String = item_id
	var last_underscore: int = result.rfind("_")
	if last_underscore > 0:
		var suffix: String = result.substr(last_underscore + 1)
		if suffix.is_valid_int():
			result = result.substr(0, last_underscore)
	return result.replace("_", " ").capitalize()
