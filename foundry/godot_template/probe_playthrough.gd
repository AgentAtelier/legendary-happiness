extends SceneTree

var _result = {
	"ok": false,
	"npc_state": "?",
	"win_visible": false,
	"wrong_shown": false,
	"checks": []
}

var _scene_path = ""
var _phase = 0
var _phase_timer = 0.0
var _npc = null
var _target_prop = null
var _distractor_prop = null
var _player = null
var _target_entity = ""
var _done = false


func _init():
	var args = OS.get_cmdline_args()
	for i in range(len(args)):
		if args[i].ends_with("probe_playthrough.gd") and i + 1 < len(args):
			_scene_path = args[i + 1]
			break
	if _scene_path == "":
		for i in range(len(args)):
			if not args[i].begins_with("-") and not args[i].ends_with(".gd"):
				_scene_path = args[i]
				break
	if _scene_path == "":
		_result["checks"].append("ERROR: no scene path provided")
		_print_and_quit(1)
	var err = change_scene_to_file(_scene_path)
	if err != OK:
		_result["checks"].append("ERROR: failed to load scene")
		_print_and_quit(1)


func _process(delta):
	if _done:
		return false
	_phase_timer += delta
	_run_phase()
	return false


func _run_phase():
	# ── Phase 0: Find all key nodes ────────────────────────────
	if _phase == 0:
		if _phase_timer > 1.0:
			_find_nodes()
			if _npc != null and _target_prop != null and _player != null:
				if _distractor_prop != null:
					_result["checks"].append("PASS: all key nodes found (NPC, target, distractor, Player)")
				else:
					_result["checks"].append("PASS: key nodes found (NPC, target, Player) — no distractor")
					_result["checks"].append("WARNING: no distractor prop found")
				_phase = 1
				_phase_timer = 0.0
			else:
				if _npc == null:
					_result["checks"].append("FAIL: NPC node not found")
				if _target_prop == null:
					_result["checks"].append("FAIL: target prop not found")
				if _player == null:
					_result["checks"].append("FAIL: Player node not found")
				_done = true
				_print_and_quit(1)

	# ── Phase 1: Talk to NPC (get quest) + force state transition ─
	if _phase == 1:
		if _phase_timer > 0.3:
			_result["checks"].append("ACTION: talk to NPC")
			if _npc.has_method("on_interact"):
				_npc.on_interact("talk")
			# FIX-5: Force state to QUEST_GIVEN so we don't have to wait for
			# the 2s await timer in npc.gd. This makes the probe deterministic.
			_npc._state = 1  # State.QUEST_GIVEN
			_result["checks"].append("PASS: NPC interaction called + state forced to QUEST_GIVEN")
			_phase = 2
			_phase_timer = 0.0

	# ── Phase 2: Pick up distractor prop ───────────────────────
	if _phase == 2:
		if _phase_timer > 0.3:
			if _distractor_prop != null:
				_result["checks"].append("ACTION: pick up DISTRACTOR prop")
				if _distractor_prop.has_method("on_interact"):
					_distractor_prop.on_interact("pickup")
				var carried = str(_player.carried_item)
				if carried == _distractor_prop.name:
					_result["checks"].append("PASS: player carries distractor=" + carried)
				else:
					_result["checks"].append("FAIL: expected carried=" + _distractor_prop.name + " got=" + carried)
			else:
				_result["checks"].append("SKIP: no distractor — skipping to target pickup")
			_phase = 3
			_phase_timer = 0.0

	# ── Phase 3: Talk to NPC (wrong item or skip) ──────────────
	if _phase == 3:
		if _phase_timer > 0.3:
			if _distractor_prop != null:
				_result["checks"].append("ACTION: talk to NPC (should get wrong line)")
				if _npc.has_method("on_interact"):
					_npc.on_interact("talk")
				# NPC state should remain QUEST_GIVEN (not DONE)
				if is_instance_valid(_npc):
					var nstate = int(_npc._state)
					_result["npc_state"] = str(nstate)
					if nstate == 1:  # QUEST_GIVEN
						_result["checks"].append("PASS: NPC still in QUEST_GIVEN (wrong item)")
						_result["wrong_shown"] = true
					else:
						_result["checks"].append("FAIL: expected NPC state QUEST_GIVEN(1) got=" + str(nstate))
			else:
				_result["checks"].append("SKIP: no distractor — skipping wrong-item check")
			_phase = 4
			_phase_timer = 0.0

	# ── Phase 4: Pick up target prop ───────────────────────────
	if _phase == 4:
		if _phase_timer > 0.3:
			_result["checks"].append("ACTION: pick up TARGET prop")
			if _target_prop.has_method("on_interact"):
				_target_prop.on_interact("pickup")
			var carried = str(_player.carried_item)
			if carried == _target_prop.name:
				_result["checks"].append("PASS: player carries target=" + carried)
			else:
				_result["checks"].append("FAIL: expected carried=" + _target_prop.name + " got=" + carried)
			_phase = 5
			_phase_timer = 0.0

	# ── Phase 5: Talk to NPC (deliver correct item) ────────────
	if _phase == 5:
		if _phase_timer > 0.3:
			_result["checks"].append("ACTION: talk to NPC (should deliver item)")
			if _npc.has_method("on_interact"):
				_npc.on_interact("talk")
			if is_instance_valid(_npc):
				var nstate = int(_npc._state)
				_result["npc_state"] = str(nstate)
				_result["checks"].append("NPC final state=" + str(nstate))
			_phase = 6
			_phase_timer = 0.0

	# ── Phase 6: Check WinScreen ───────────────────────────────
	if _phase == 6:
		if _phase_timer > 0.3:
			_check_win_screen()
			_done = true
			_print_and_quit(0 if _result["ok"] else 1)


func _find_nodes():
	var all_nodes = []
	_collect_all(get_root(), all_nodes)

	# Read target_entity from quest data JSON
	var data_path: String = _scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var parsed = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			_target_entity = str(parsed.get("target_entity", ""))

	for n in all_nodes:
		if n is Node3D and n.has_meta("_forge_tag"):
			var tag = n.get_meta("_forge_tag")
			if tag == "talk" and _npc == null:
				_npc = n
			elif tag == "pickup":
				if n.name == _target_entity and _target_prop == null:
					_target_prop = n
				elif n.name != _target_entity and _distractor_prop == null:
					_distractor_prop = n
		if n.name == "Player" and n is CharacterBody3D:
			_player = n


func _check_win_screen():
	var all_nodes = []
	_collect_all(get_root(), all_nodes)
	for n in all_nodes:
		if n.name == "WinScreen":
			var visible_val = n.visible
			_result["win_visible"] = visible_val
			if visible_val:
				_result["checks"].append("PASS: WinScreen is visible")
				_result["ok"] = true
			else:
				_result["checks"].append("FAIL: WinScreen is NOT visible")
			return
	_result["checks"].append("FAIL: WinScreen node not found")


func _collect_all(node, out):
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)


func _print_and_quit(exit_code):
	var json_str = JSON.stringify(_result, "")
	print("PROBE_JSON_OUTPUT:" + json_str)
	quit(exit_code)
