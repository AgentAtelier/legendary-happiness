extends Control
## WS-4: Build Report panel — displays the Brief's Understood / Built /
## Assumed / Couldn't as a clean in-world card (the legibility flex).
##
## Reads from ``res://build_report.json`` written by the orchestrator.
## Toggle visibility with the B key; visible on first load.

const REPORT_PATH := "res://build_report.json"

@onready var _panel: Panel = $Panel
@onready var _title: Label = $Panel/TitleLabel
@onready var _understood: RichTextLabel = $Panel/UnderstoodSection/Content
@onready var _built: RichTextLabel = $Panel/BuiltSection/Content
@onready var _assumed: RichTextLabel = $Panel/AssumedSection/Content
@onready var _couldnt: RichTextLabel = $Panel/CouldntSection/Content
@onready var _close_hint: Label = $Panel/CloseHint

var _visible: bool = true


func _ready() -> void:
	_load_report()
	_update_visibility()


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_B:
			_visible = not _visible
			_update_visibility()


func _update_visibility() -> void:
	_panel.visible = _visible
	_close_hint.visible = _visible


func _load_report() -> void:
	if not FileAccess.file_exists(REPORT_PATH):
		_title.text = "Build Report (not found)"
		return
	var f := FileAccess.open(REPORT_PATH, FileAccess.READ)
	if not f:
		return
	var text := f.get_as_text()
	f.close()
	var report := JSON.parse_string(text)
	if not report:
		_title.text = "Build Report (parse error)"
		return
	
	_title.text = report.get("title", "Build Report")
	_render_section(_understood, report.get("understood", []), "Interpreter understood")
	_render_section(_built, report.get("built", []), "Assembled from library")
	_render_section(_assumed, report.get("assumed", []), "Resolver assumed defaults")
	_render_section(_couldnt, report.get("couldnt", []), "Could not resolve")


func _render_section(label: RichTextLabel, items, fallback: String) -> void:
	if items and not items.is_empty():
		var lines: Array[String] = []
		for item in items:
			if item is String:
				lines.append("  • " + item)
			elif item is Dictionary:
				lines.append("  • " + item.get("label", item.get("code", str(item))))
		label.text = "\n".join(lines)
	else:
		label.text = "  (none)"


func set_report_data(data: Dictionary) -> void:
	"""Programmatic override: set report data directly."""
	_title.text = data.get("title", "Build Report")
	_render_section(_understood, data.get("understood", []), "")
	_render_section(_built, data.get("built", []), "")
	_render_section(_assumed, data.get("assumed", []), "")
	_render_section(_couldnt, data.get("couldnt", []), "")
