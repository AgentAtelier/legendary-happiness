@tool
extends VBoxContainer

var http_generate: HTTPRequest
var http_report: HTTPRequest
var http_repair: HTTPRequest
var http_learn: HTTPRequest

var server_url := "http://127.0.0.1:8000"

var _last_prompt: String = ""
var _pending_results: Array = []
var _pending_scene_tree: Dictionary = {}
var _repair_attempts: int = 0


# ------------------------------------------------------------
# Scene Management
# ------------------------------------------------------------

func _get_game_scene_root() -> Node:
	var root = get_tree().edited_scene_root
	
	if root == null:
		return null
	
	# Don't use the plugin panel as the root
	if root.name.begins_with("DevForge") or root.has_method("_on_run_pressed"):
		return null
	
	return root


# ------------------------------------------------------------
# Ready
# ------------------------------------------------------------

func _ready():
	
	if has_node("RunButton"):
		$RunButton.pressed.connect(_on_run_pressed)

	http_generate = HTTPRequest.new()
	http_report = HTTPRequest.new()
	http_repair = HTTPRequest.new()
	http_learn = HTTPRequest.new()

	add_child(http_generate)
	add_child(http_report)
	add_child(http_repair)
	add_child(http_learn)

	http_generate.request_completed.connect(Callable(self, "_on_generate_completed"))
	http_repair.request_completed.connect(Callable(self, "_on_repair_completed"))

	_log("DevForge panel ready")


# ------------------------------------------------------------
# Run Button
# ------------------------------------------------------------

func _on_run_pressed():

	var prompt_input = $PromptInput
	var prompt = prompt_input.text.strip_edges()

	if prompt == "":
		return

	_last_prompt = prompt

	var root = _get_game_scene_root()
	var scene_data = {}

	if root:
		scene_data = _serialize_node(root)
	else:
		_log("WARNING: No game scene open. Nodes will not be added to any scene.")
		_log("Please open or create a scene in the editor first.")

	_pending_scene_tree = scene_data

	var payload = {
	"prompt": prompt,
	"scene_tree": scene_data
	}

	_log("RUN BUTTON PRESSED")
	_log("Prompt:\n" + prompt)

	_send_json(http_generate, server_url + "/generate", payload)


# ------------------------------------------------------------
# Generate Response
# ------------------------------------------------------------

func _on_repair_completed(_result, response_code, _headers, body):

	if response_code != 200:
		_log("Repair failed: " + str(response_code))
		return

	var data = _parse_body(body)

	if typeof(data) != TYPE_DICTIONARY:
		_log("Repair returned invalid data")
		return

	var ops = data.get("operations", [])
	var files = data.get("files", [])

	files = _dedupe_files(files)

	_create_files(files)

	var results = _execute_operations(ops)

	_pending_results = results

	# refresh scene snapshot after repair
	var root = get_tree().edited_scene_root
	if root:
		_pending_scene_tree = _serialize_node(root)

	_send_report()

# ------------------------------------------------------------
# Generate Response
# ------------------------------------------------------------

func _on_generate_completed(_result, response_code, _headers, body):

	if response_code != 200:
		_log("Generate failed: " + str(response_code))
		return

	var data = _parse_body(body)

	if typeof(data) != TYPE_DICTIONARY:
		_log("Generate returned invalid data")
		return

	_handle_response(data)

# ------------------------------------------------------------
# Response Handling
# ------------------------------------------------------------

func _handle_response(data: Dictionary):

	var ops = data.get("operations", [])
	var files = data.get("files", [])

	files = _dedupe_files(files)

	_create_files(files)

	var results = _execute_operations(ops)

	_pending_results = results

	# ------------------------------------------------------------
	# CRITICAL FIX
	# re-serialize scene after operations
	# ------------------------------------------------------------

	var root = get_tree().edited_scene_root

	if root:
		_pending_scene_tree = _serialize_node(root)

	# ------------------------------------------------------------

	_send_report()


# ------------------------------------------------------------
# File Creation
# ------------------------------------------------------------

func _dedupe_files(files):

	var seen := {}
	var result := []

	for f in files:

		var path = f.get("path", "")

		if path == "":
			continue

		if seen.has(path):
			continue

		seen[path] = true
		result.append(f)

	return result


func _create_files(files):

	for f in files:

		var rel_path = f.get("path", "")
		var content = f.get("content", "")

		if rel_path == "":
			continue

		var res_path = "res://" + rel_path
		var abs_path = ProjectSettings.globalize_path(res_path)

		var dir_path = abs_path.get_base_dir()

		if not DirAccess.dir_exists_absolute(dir_path):
			var err = DirAccess.make_dir_recursive_absolute(dir_path)
			if err != OK:
				_log("[DevForge] Failed to create directory: " + dir_path)
				continue

		var file = FileAccess.open(abs_path, FileAccess.WRITE)

		if file:
			file.store_string(content)
			file.close()
			_log("[DevForge] Created file: " + res_path)
		else:
			_log("[DevForge] Cannot write: " + res_path)
			
		EditorInterface.get_resource_filesystem().scan()

# ------------------------------------------------------------
# Operation Execution
# ------------------------------------------------------------

func _execute_operations(ops):

	var root = _get_game_scene_root()
	
	if root == null:
		_log("ERROR: No game scene open. Please open or create a scene first.")
		return []

	var results = []

	for op in ops:

		var op_type = op.get("type", "")

		var success = false
		var err = ""

		match op_type:

			"add_node":
				success = _op_add_node(root, op)

			"remove_node":
				success = _op_remove_node(root, op)

			"rename_node":
				success = _op_rename_node(root, op)

			"attach_script":
				success = _op_attach_script(root, op)

			"set_property":
				success = _op_set_property(root, op)

			"connect_signal":
				success = _op_connect_signal(root, op)

			"add_child_scene":
				success = _op_add_child_scene(root, op)

			_:
				err = "Unknown op"

		if success:
			_log("[DevForge] OK: " + op_type + " " + str(op.get("name", "")))
		else:
			_log("[DevForge] FAILED: " + op_type)

		results.append({
			"operation": op,
			"success": success,
			"error": err
		})

	return results


# ------------------------------------------------------------
# Operations
# ------------------------------------------------------------

func _resolve_path(root: Node, path: String) -> Node:

	if path == "" or root == null:
		return null

	if path == "/root":
		return root

	return root.get_node_or_null(path.replace("/root/", ""))


func _op_add_node(root, op) -> bool:

	var parent = _resolve_path(root, op.get("parent", ""))

	if parent == null:
		return false

	var node_type = op.get("node_type", "Node")
	var node_name = op.get("name", node_type)

	var node = ClassDB.instantiate(node_type)

	if node == null:
		return false

	node.name = node_name
	node.owner = root
	parent.add_child(node)

	return true


func _op_remove_node(root, op) -> bool:

	var node = _resolve_path(root, op.get("node", ""))

	if node == null:
		return false

	node.queue_free()

	return true


func _op_rename_node(root, op) -> bool:

	var node = _resolve_path(root, op.get("node", ""))

	if node == null:
		return false

	var new_name = op.get("new_name", "")

	if new_name == "":
		return false

	node.name = new_name

	return true


func _op_attach_script(root, op) -> bool:

	var node = _resolve_path(root, op.get("node", ""))

	if node == null:
		return false

	var script_path = op.get("script", "")

	var script = load("res://" + script_path)

	if script == null:
		return false

	node.set_script(script)

	return true


func _op_set_property(root, op) -> bool:

	var node = _resolve_path(root, op.get("node", ""))

	if node == null:
		return false

	var prop = op.get("property", "")
	var value = op.get("value")

	node.set(prop, value)

	return true


func _op_connect_signal(root, op) -> bool:

	var source = _resolve_path(root, op.get("source", ""))
	var target = _resolve_path(root, op.get("target", ""))

	if source == null or target == null:
		return false

	var sig = op.get("signal", "")
	var method = op.get("method", "")

	source.connect(sig, Callable(target, method))

	return true


func _op_add_child_scene(root, op) -> bool:

	var parent = _resolve_path(root, op.get("parent", ""))

	if parent == null:
		return false

	var scene_path = op.get("scene", "")

	var scene = load("res://" + scene_path)

	if scene == null:
		return false

	var instance = scene.instantiate()

	parent.add_child(instance)

	return true


# ------------------------------------------------------------
# Scene Serialization
# ------------------------------------------------------------

func _serialize_node(node: Node) -> Dictionary:

	var d = {}

	d["name"] = node.name
	d["type"] = node.get_class()
	d["path"] = node.get_path()

	var children = []

	for c in node.get_children():
		children.append(_serialize_node(c))

	d["children"] = children

	return d


# ------------------------------------------------------------
# Networking
# ------------------------------------------------------------

func _send_report():

	var payload = {
		"prompt": _last_prompt,
		"results": _pending_results,
		"scene": _pending_scene_tree
	}

	_send_json(http_report, server_url + "/report", payload)


func _send_json(http: HTTPRequest, url: String, payload: Dictionary):

	var json_str = JSON.stringify(payload)
	var headers = ["Content-Type: application/json"]

	http.request(url, headers, HTTPClient.METHOD_POST, json_str)


func _parse_body(body: PackedByteArray):

	var text = body.get_string_from_utf8()
	return JSON.parse_string(text)


# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

func _log(msg: String):
	print("[DevForge] " + msg)
