extends Control
## WS-4: Prompt-entry screen for the generation-reveal showcase.
## Shows a text field + Generate button, then triggers world assembly.

const PROMPT_FILE := "user://prompt.json"
const REPORT_FILE := "user://build_report.json"

@onready var _input: TextEdit = $PromptInput
@onready var _button: Button = $GenerateButton
@onready var _feedback: Label = $FeedbackLabel
@onready var _title: Label = $TitleLabel
@onready var _dots_timer: Timer = $DotsTimer

var _dots: int = 0
var _building: bool = false


func _ready() -> void:
	_button.pressed.connect(_on_generate_pressed)
	_dots_timer.timeout.connect(_animate_dots)
	_feedback.visible = false
	# Focus the input on start
	_input.grab_focus()
	# Allow Enter key to submit
	_input.text_changed.connect(_on_text_changed)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_ENTER and event.ctrl_pressed:
			_on_generate_pressed()


func _on_text_changed() -> void:
	# Auto-resize the text edit
	pass


func _on_generate_pressed() -> void:
	if _building:
		return
	var prompt_text: String = _input.text.strip_edges()
	if prompt_text.is_empty():
		_feedback.text = "Please enter a prompt."
		_feedback.visible = true
		return
	_building = true
	_start_building(prompt_text)


func _start_building(prompt: String) -> void:
	"""Begin world assembly with the given prompt."""
	_building = true
	_button.disabled = true
	_input.editable = false
	_feedback.visible = true
	_feedback.text = "Interpreting…"
	_dots_timer.start(0.5)
	
	# WS-4: Write prompt to file for the orchestrator to read.
	# The orchestrator (Python) polls this file, runs assembly,
	# and produces the generated scene + build report.
	var data := {"prompt": prompt, "timestamp": Time.get_unix_time_from_system()}
	var f := FileAccess.open(PROMPT_FILE, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data, "\t"))
		f.close()
	
	# Start polling for the build report (orchestrator writes it when done)
	_poll_build_complete.call_deferred()


func _animate_dots() -> void:
	if not _building:
		return
	_dots = (_dots + 1) % 4
	var msg: String
	match _dots:
		0: msg = "World building"
		1: msg = "World building."
		2: msg = "World building.."
		3: msg = "World building..."
	_feedback.text = msg


func _poll_build_complete() -> void:
	"""Check if the build report has been written by the orchestrator."""
	# WS-4: Use while loop with await instead of recursion to avoid stack overflow.
	var attempts: int = 0
	const MAX_ATTEMPTS: int = 120  # 60 seconds at 0.5s intervals
	while _building and attempts < MAX_ATTEMPTS:
		if FileAccess.file_exists(REPORT_FILE):
			break
		attempts += 1
		await get_tree().create_timer(0.5).timeout
	
	_building = false
	_dots_timer.stop()
	
	if attempts >= MAX_ATTEMPTS:
		_feedback.text = "Assembly timed out. Loading default…"
		await get_tree().create_timer(1.0).timeout
		get_tree().change_scene_to_file("res://generated_scene.tscn")
		return
	
	_feedback.text = "World ready! Loading…"
	
	# Load the generated scene
	# The orchestrator writes the scene path into the report.
	var f := FileAccess.open(REPORT_FILE, FileAccess.READ)
	if f:
		var report_text := f.get_as_text()
		f.close()
		var report := JSON.parse_string(report_text)
		if report and report.has("scene_path"):
			get_tree().change_scene_to_file(report["scene_path"])
			return
	
	# Fallback: load the default generated scene
	get_tree().change_scene_to_file("res://generated_scene.tscn")

