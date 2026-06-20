# HUD — heads-up display with quest log, counter, subtitles, and inventory.
# B1: Quest log panel (J toggle), multi-quest counter (X/N done),
#      subtitle/dialogue scrollback, reticle color updates.
extends Control

@onready var _objective_label: Label = $ObjectiveLabel
@onready var _interact_label: Label = $InteractLabel
@onready var _inventory_label: Label = $InventoryLabel
# B1: new HUD children
@onready var _quest_log: Control = $QuestLog
@onready var _quest_log_text: Label = $QuestLog/QuestLogText
@onready var _quest_counter: Label = $QuestCounter
@onready var _subtitle_panel: RichTextLabel = $SubtitlePanel
@onready var _crosshair: ColorRect = $Crosshair
@onready var _tooltip_label: Label = $TooltipLabel

# B1: quest tracking
var _quests_total: int = 0
var _quests_done: int = 0
var _quest_log_visible: bool = false

# B1: subtitle tracking
var _subtitle_lines: Array[String] = []
const _MAX_SUBTITLE_LINES := 50


func _ready() -> void:
	# B1: Connect to all NPC quest_state_changed signals
	_connect_npc_signals()
	# B1: Initial counter update
	_refresh_quest_counter()
	# B1: Quest log starts hidden
	_quest_log.visible = false
	# B1: Tooltip starts hidden
	_tooltip_label.visible = false


func set_objective(text: String) -> void:
	_objective_label.text = text


func show_interact(text: String) -> void:
	_interact_label.text = text
	_interact_label.visible = text != ""


# ── B1: Quest log panel ──────────────────────────────────────────

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_J:
			_quest_log_visible = not _quest_log_visible
			_quest_log.visible = _quest_log_visible
			if _quest_log_visible:
				_refresh_quest_log()


func _connect_npc_signals() -> void:
	"""Connect to every NPC's quest_state_changed signal."""
	var root = get_node_or_null("/root/Root")
	if not root:
		return
	var all_nodes: Array = []
	_collect_all(root, all_nodes)
	for n in all_nodes:
		if n.has_signal("quest_state_changed"):
			if not n.quest_state_changed.is_connected(_on_quest_state_changed):
				n.quest_state_changed.connect(_on_quest_state_changed)


func _on_quest_state_changed(_npc_id: String, _state: int) -> void:
	"""Called when any NPC changes state."""
	_refresh_quest_counter()
	if _quest_log_visible:
		_refresh_quest_log()


func _refresh_quest_counter() -> void:
	"""Count DONE vs total NPCs and update the counter label."""
	var _total := 0
	var _done := 0
	var root = get_node_or_null("/root/Root")
	if root:
		var all_nodes: Array = []
		_collect_all(root, all_nodes)
		for n in all_nodes:
			if n.has_meta("_forge_tag") and n.get_meta("_forge_tag") == "talk":
				_total += 1
				if int(n._state) == 2:  # DONE
					_done += 1
	_quests_total = _total
	_quests_done = _done
	if _quest_counter:
		if _total > 0:
			_quest_counter.text = "%d / %d quests done" % [_done, _total]
			_quest_counter.visible = true
		else:
			_quest_counter.visible = false


func update_quest_counter(done: int, total: int) -> void:
	"""Called by npc.gd _try_emit_win to update counter."""
	_quests_done = done
	_quests_total = total
	if _quest_counter:
		if total > 0:
			_quest_counter.text = "%d / %d quests done" % [done, total]
			_quest_counter.visible = true
		else:
			_quest_counter.visible = false


func _refresh_quest_log() -> void:
	"""Rebuild the quest log text from all NPCs.
	B1-fix: Read targets from quest_data.json (n.get(_quest_data)
	returns null since _quest_data is a script var, not a node property)."""
	var lines: PackedStringArray = []
	lines.append("--- Quest Log ---")
	# Read quest_data.json once for target mapping
	var npc_targets: Dictionary = _read_quest_targets()
	var root = get_node_or_null("/root/Root")
	if root:
		var all_nodes: Array = []
		_collect_all(root, all_nodes)
		for n in all_nodes:
			if n.has_meta("_forge_tag") and n.get_meta("_forge_tag") == "talk":
				var role: String = str(n.get_meta("_forge_role", "NPC"))
				var npc_id: String = str(n.get_meta("_forge_npc_id", "NPC"))
				var target: String = str(npc_targets.get(npc_id, ""))
				var state_str: String = "???"
				var st := int(n._state)
				match st:
					0: state_str = "AVAILABLE"
					1: state_str = "IN PROGRESS"
					2: state_str = "DONE"
				lines.append("%s: %s [%s]" % [role, _short_target(target), state_str])
	lines.append("--- %d / %d complete ---" % [_quests_done, _quests_total])
	_quest_log_text.text = "\n".join(lines)


func _read_quest_targets() -> Dictionary:
	"""Read npc_id → target_entity mapping from quest_data.json."""
	var result: Dictionary = {}
	var scene_path: String = get_tree().current_scene.scene_file_path
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var parsed = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			var npcs = parsed.get("npcs", {})
			if npcs is Dictionary:
				for k in npcs.keys():
					result[k] = str(npcs[k].get("target_entity", ""))
	return result


func _short_target(target_id: String) -> String:
	"""Shorten a target ID for display (e.g. 'iron_key_3' → 'iron key')."""
	var s := target_id
	var lu := s.rfind("_")
	if lu > 0:
		var suffix := s.substr(lu + 1)
		if suffix.is_valid_int():
			s = s.substr(0, lu)
	return s.replace("_", " ")


# ── B1: Subtitle / dialogue scrollback ──────────────────────────

func push_subtitle(line: String) -> void:
	"""Push a dialogue line into the subtitle scrollback."""
	_subtitle_lines.append(line)
	while _subtitle_lines.size() > _MAX_SUBTITLE_LINES:
		_subtitle_lines.pop_front()
	if _subtitle_panel:
		_subtitle_panel.text = "\n".join(_subtitle_lines)
		# Fade in, hold, then fade out after 8 seconds
		_subtitle_panel.modulate.a = 1.0
		var tween = create_tween()
		tween.tween_interval(6.0)
		tween.tween_property(_subtitle_panel, "modulate:a", 0.3, 2.0)
		# Scroll to bottom
		_subtitle_panel.scroll_to_line(_subtitle_lines.size() - 1)


# ── B1: Reticle color update ─────────────────────────────────────

func set_crosshair_style(tag: String) -> void:
	"""Change crosshair color based on what's being looked at."""
	if not _crosshair:
		return
	match tag:
		"pickup":
			_crosshair.color = Color(0, 1, 0, 0.8)  # green
		"talk":
			_crosshair.color = Color(1, 0.9, 0.2, 0.8)  # yellow/amber
		_:
			_crosshair.color = Color(1, 1, 1, 0.5)  # white (default)


# ── B1: Tooltip label ────────────────────────────────────────────

func show_tooltip(text: String) -> void:
	"""Show a floating tooltip label (e.g. prop category / NPC role)."""
	if not _tooltip_label:
		return
	if text == "":
		_tooltip_label.visible = false
		return
	_tooltip_label.text = text
	_tooltip_label.visible = true


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
		var display_name: String = _display_name(item_id)
		if i == active_index:
			lines.append("> %s" % display_name)
		else:
			lines.append("  %s" % display_name)
	_inventory_label.text = "\n".join(lines)


func _display_name(item_id: String) -> String:
	"""Convert an item ID like 'golden_key_3' to a readable name."""
	var result: String = item_id
	var last_underscore: int = result.rfind("_")
	if last_underscore > 0:
		var suffix: String = result.substr(last_underscore + 1)
		if suffix.is_valid_int():
			result = result.substr(0, last_underscore)
	return result.replace("_", " ").capitalize()


func _collect_all(node, out: Array) -> void:
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)
