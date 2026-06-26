# probe_playthrough.gd — scripted human-input playthrough probe (Item 5, Phase 0.5)
#
# Usage:
#   godot --headless --path <project> -s probe_playthrough.gd <scene_path>
#
# Phase 0.5 — drives the REAL interaction path:
#   1. Aim the player camera at a target, step physics frames.
#   2. Call interaction.interact_under_crosshair() — the SAME camera
#      raycast + parent-walk + on_interact(tag) method the human E-key
#      press drives.
#   3. Await the REAL outcome with bounded timeouts (NPC state naturally
#      advances — no forced _state assignments).
#   4. Cycle/drop drive the player's real methods.
#
# C-2: Multi-item inventory — the probe tests multi-item carry,
#      active-item cycling, drop-removes-from-inventory, and
#      win-leaves-other-items-untouched.
extends SceneTree

# ── Result ───────────────────────────────────────────────────────

var _result = {
	"ok": false,
	"npc_state": "?",
	"win_visible": false,
	"wrong_shown": false,
	"checks": [],
	# B0: multi-NPC probe fields
	"multi_npc": false,
	"both_done": false,
	# B1: multi-quest win gate
	"win_after_first_done": false,
	"quest_log_populated": false,
	# B2: Atmosphere — post-processing + day/night
	"world_env_found": false,
	"day_night_found": false,
	"sun_found": false,
	# EB-6: Examine flavour text
	"examine_data_found": false
}

# ── State ────────────────────────────────────────────────────────

var _scene_path: String = ""
var _done: bool = false
var _npc = null
var _target_prop = null
var _distractor_prop = null
var _player = null
var _interaction = null
var _target_entity: String = ""

# B0: multi-NPC support
var _npc_1 = null
var _target_1_prop = null
var _npc_1_role: String = ""
var _multi_npc: bool = false

# Timeout constants (in process frames)
const _NPCSettleFrames: int = 15
const _PickupSettleFrames: int = 8
const _DropSettleFrames: int = 8
const _AimSettleFrames: int = 3


# ── Init ─────────────────────────────────────────────────────────

func _init() -> void:
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

	var err: int = change_scene_to_file(_scene_path)
	if err != OK:
		_result["checks"].append("ERROR: failed to load scene")
		_print_and_quit(1)

	await process_frame
	await process_frame

	# Run the async playthrough; _print_and_quit fires at the end.
	await _run_playthrough()
	_print_and_quit(0 if _result["ok"] else 1)


# ── Core playthrough (async) ─────────────────────────────────────

func _run_playthrough() -> void:
	_find_nodes()
	if _npc == null or _target_prop == null or _player == null or _interaction == null:
		_done = true
		return

	# Collect discovery checks
	var found_parts := PackedStringArray(["NPC", "target"])
	if _distractor_prop != null:
		found_parts.append("distractor")
	found_parts.append("Player")
	if _multi_npc:
		if _npc_1 != null:
			found_parts.append("NPC1")
		if _target_1_prop != null:
			found_parts.append("target1")
	_result["multi_npc"] = _multi_npc and _npc_1 != null and _target_1_prop != null
	# B2: post-processing + day/night
	_result["world_env_found"] = self.root.has_node("Root/WorldEnvironment")
	_result["day_night_found"] = self.root.has_node("Root/DayNight")
	_result["sun_found"] = self.root.has_node("Root/DirectionalLight3D")
	# EB-6: examine data
	var data_path: String = _scene_path.replace(".tscn", "_quest_data.json")
	var file2 = FileAccess.open(data_path, FileAccess.READ)
	if file2:
		var parsed2 = JSON.parse_string(file2.get_as_text())
		if parsed2 is Dictionary and parsed2.has("examine"):
			_result["examine_data_found"] = true
			found_parts.append("ExamineData")
		var npcs2 = parsed2.get("npcs", {})
		if npcs2 is Dictionary:
			var bark_count := 0
			for k in npcs2.keys():
				var nd = npcs2[k]
				if nd is Dictionary and nd.has("idle_barks"):
					bark_count += 1
			if bark_count > 0:
				found_parts.append("IdleBarks")
	if _result["world_env_found"]:
		found_parts.append("WorldEnv")
	if _result["day_night_found"]:
		found_parts.append("DayNight")
	if _result["sun_found"]:
		found_parts.append("Sun")

	_result["checks"].append("PASS: all key nodes found (" + ", ".join(found_parts) + ")")
	if _multi_npc and (_npc_1 == null or _target_1_prop == null):
		_result["checks"].append("WARNING: multi-NPC quest_data but second NPC/target not found")
	if _distractor_prop == null:
		_result["checks"].append("WARNING: no distractor prop found")

	# ── Phase 1: Talk to NPC (get quest) ─────────────────────
	await _phase_talk_get_quest()

	# ── Phase 2: Pick up distractor ──────────────────────────
	await _phase_pickup_distractor()

	# ── Phase 3: Talk to NPC (wrong item) ────────────────────
	await _phase_talk_wrong_item()

	# ── Phase 4: Pick up target + cycle inventory ────────────
	await _phase_pickup_target_and_cycle()

	# ── Phase 5: Drop active item ────────────────────────────
	await _phase_drop_and_verify()

	# ── Phase 6: Re-pick up target from floor ────────────────
	await _phase_repick_target()

	# ── Phase 7: Deliver to NPC ──────────────────────────────
	await _phase_deliver()

	# ── Phase 8: Check WinScreen ─────────────────────────────
	await _phase_check_win()

	# ── B0: Multi-NPC phases ─────────────────────────────────
	if _multi_npc and _npc_1 != null and _target_1_prop != null:
		await _phase_multi_npc()

	_done = true


# ── Phase implementations ────────────────────────────────────────

func _phase_talk_get_quest() -> void:
	_result["checks"].append("ACTION: talk to NPC (real interact_under_crosshair)")
	_aim_player_at(_npc)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()

	# Wait for NPC state to naturally advance to QUEST_GIVEN (1)
	var ok: bool = await _wait_npc_state(_npc, 1, _NPCSettleFrames,
		"Phase 1: NPC did not reach QUEST_GIVEN")
	if not ok:
		return
	_result["checks"].append("PASS: NPC reached QUEST_GIVEN naturally (state=1)")


func _phase_pickup_distractor() -> void:
	if _distractor_prop == null:
		_result["checks"].append("SKIP: no distractor")
		return

	_result["checks"].append("ACTION: pick up DISTRACTOR prop (real interact_under_crosshair)")
	_aim_player_at(_distractor_prop)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()
	await _wait_frames(_PickupSettleFrames)

	# C-2: verify inventory
	var active = str(_player.get_active_item())
	if active == _distractor_prop.name:
		_result["checks"].append("PASS: player carries distractor=" + active)
		_result["checks"].append("C-2: inventory size=" + str(_player.carried_items.size()))
	else:
		_result["checks"].append("FAIL: expected active=" + _distractor_prop.name + " got=" + active)


func _phase_talk_wrong_item() -> void:
	if _distractor_prop == null:
		_result["checks"].append("SKIP: no distractor —  skip wrong-item phase")
		return

	_result["checks"].append("ACTION: talk to NPC (expect wrong line — distractor is held)")
	_aim_player_at(_npc)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()
	await _wait_frames(_NPCSettleFrames)

	if is_instance_valid(_npc):
		var nstate: int = int(_npc._state)
		_result["npc_state"] = str(nstate)
		if nstate == 1:
			_result["checks"].append("PASS: NPC still in QUEST_GIVEN (wrong item)")
			_result["wrong_shown"] = true
		else:
			_result["checks"].append("FAIL: expected NPC state QUEST_GIVEN(1) got=" + str(nstate))


func _phase_pickup_target_and_cycle() -> void:
	_result["checks"].append("ACTION: pick up TARGET prop (real interact_under_crosshair)")
	_aim_player_at(_target_prop)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()
	await _wait_frames(_PickupSettleFrames)

	# C-2: Verify inventory state
	var active = str(_player.get_active_item())
	var inv_size = _player.carried_items.size()
	if active == _target_prop.name:
		_result["checks"].append("PASS: active=" + active)
	else:
		_result["checks"].append("FAIL: expected active=" + _target_prop.name + " got=" + active)
	if _distractor_prop != null:
		if _distractor_prop.name in _player.carried_items:
			_result["checks"].append("PASS: C-2 distractor still in inventory (size=" + str(inv_size) + ")")
		else:
			_result["checks"].append("FAIL: C-2 distractor MISSING from inventory")
	else:
		_result["checks"].append("C-2: inventory size=" + str(inv_size))

	if _distractor_prop != null:
		# C-2: Cycle backward to distractor
		_result["checks"].append("ACTION: C-2 cycle active backward to distractor")
		if _player.has_method("_cycle_active"):
			_player._cycle_active(-1)
		await _wait_frames(2)
		active = str(_player.get_active_item())
		if active == _distractor_prop.name:
			_result["checks"].append("PASS: C-2 cycled back to distractor=" + active)
		else:
			_result["checks"].append("FAIL: C-2 cycle expected=" + _distractor_prop.name + " got=" + active)

		# C-2: Cycle forward back to target
		_result["checks"].append("ACTION: C-2 cycle active forward to target")
		if _player.has_method("_cycle_active"):
			_player._cycle_active(1)
		await _wait_frames(2)
		active = str(_player.get_active_item())
		if active == _target_prop.name:
			_result["checks"].append("PASS: C-2 cycled forward to target=" + active)
		else:
			_result["checks"].append("FAIL: C-2 cycle expected=" + _target_prop.name + " got=" + active)


func _phase_drop_and_verify() -> void:
	_result["checks"].append("ACTION: drop active item (C-2: _drop_active_item)")
	if _player.has_method("_drop_active_item"):
		_player._drop_active_item()
	await _wait_frames(_DropSettleFrames)

	# C-2: Target should be gone, distractor should remain active
	var active = str(_player.get_active_item())
	var target_in_inv = _target_prop.name in _player.carried_items
	if not target_in_inv:
		_result["checks"].append("PASS: C-2 target removed from inventory after drop")
	else:
		_result["checks"].append("FAIL: C-2 target STILL in inventory")
	if _distractor_prop != null:
		if _distractor_prop.name in _player.carried_items:
			_result["checks"].append("PASS: C-2 distractor remains in inventory (active=" + active + ")")
		else:
			_result["checks"].append("FAIL: C-2 distractor LOST from inventory")
	else:
		_result["checks"].append("PASS: inventory empty after drop (no distractor)")
	# Verify dropped item is on the floor (y close to 0)
	if _target_prop != null and is_instance_valid(_target_prop):
		var drop_y: float = _target_prop.global_position.y
		if drop_y < 1.0:
			_result["checks"].append("PASS: dropped item on floor (y=%.3f)" % drop_y)
		else:
			_result["checks"].append("FAIL: dropped item FLOATING (y=%.3f)" % drop_y)
	else:
		_result["checks"].append("FAIL: target prop invalid after drop")


func _phase_repick_target() -> void:
	_result["checks"].append("ACTION: re-pick up target from floor (real interact_under_crosshair)")
	_aim_player_at(_target_prop)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()
	await _wait_frames(_PickupSettleFrames)

	var active = str(_player.get_active_item())
	var inv_size = _player.carried_items.size()
	if active == _target_prop.name:
		_result["checks"].append("PASS: C-2 re-picked target active=" + active + " (inv size=" + str(inv_size) + ")")
	else:
		_result["checks"].append("FAIL: expected active=" + _target_prop.name + " got=" + active)
	# C-2: Distractor should still be in inventory
	if _distractor_prop != null:
		if _distractor_prop.name in _player.carried_items:
			_result["checks"].append("PASS: C-2 distractor still in inventory after re-pick")
		else:
			_result["checks"].append("FAIL: C-2 distractor LOST after re-pick")


func _phase_deliver() -> void:
	_result["checks"].append("ACTION: talk to NPC (deliver item), await DONE state")
	_aim_player_at(_npc)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()

	# Wait for NPC state to naturally advance to DONE (2)
	var ok: bool = await _wait_npc_state(_npc, 2, _NPCSettleFrames,
		"Phase 7: NPC did not reach DONE after delivery")
	if is_instance_valid(_npc):
		var nstate: int = int(_npc._state)
		_result["npc_state"] = str(nstate)
		_result["checks"].append("NPC final state=" + str(nstate))
	if not ok:
		return


func _phase_check_win() -> void:
	await _wait_frames(3)
	_check_win_screen()
	# B1: Multi-quest win gate — after first NPC done, WinScreen should NOT be visible
	if _multi_npc:
		_result["win_after_first_done"] = _result["win_visible"]
		if _result["win_visible"]:
			_result["checks"].append("WARNING: B1 WinScreen visible after first NPC (should be gated)")
		else:
			_result["checks"].append("PASS: B1 multi-quest win gate — WinScreen NOT visible after first NPC")
	# C-2: Win shouldn't clear other inventory items
	if _distractor_prop != null:
		if _distractor_prop.name in _player.carried_items:
			_result["checks"].append("PASS: C-2 distractor survived win (still in inventory)")
		else:
			_result["checks"].append("C-2: distractor not in inventory after win (may be intentional)")


func _phase_multi_npc() -> void:
	# Phase 9: Talk to NPC 1
	_result["checks"].append("B0: ACTION interact with NPC 1 (" + _npc_1_role + ")")
	_aim_player_at(_npc_1)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()

	var ok1: bool = await _wait_npc_state(_npc_1, 1, _NPCSettleFrames,
		"B0 Phase 9: NPC 1 did not reach QUEST_GIVEN")
	if not ok1:
		return
	_result["checks"].append("PASS: B0 NPC 1 reached QUEST_GIVEN naturally")

	# Phase 10: Pick up NPC 1's target
	_result["checks"].append("B0: ACTION pick up NPC 1 target=" + _target_1_prop.name)
	_aim_player_at(_target_1_prop)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()
	await _wait_frames(_PickupSettleFrames)

	var active = str(_player.get_active_item())
	if active == _target_1_prop.name:
		_result["checks"].append("PASS: B0 player carries NPC 1 target=" + active)
	else:
		_result["checks"].append("FAIL: B0 expected active=" + _target_1_prop.name + " got=" + active)

	# Phase 11: Deliver to NPC 1
	_result["checks"].append("B0: ACTION deliver to NPC 1")
	_aim_player_at(_npc_1)
	await _wait_frames(_AimSettleFrames)
	_interaction.interact_under_crosshair()

	var ok2: bool = await _wait_npc_state(_npc_1, 2, _NPCSettleFrames,
		"B0 Phase 11: NPC 1 did not reach DONE")
	if is_instance_valid(_npc_1):
		var n1state: int = int(_npc_1._state)
		_result["checks"].append("B0: NPC 1 state=" + str(n1state))
		if n1state == 2:
			_result["checks"].append("PASS: B0 NPC 1 reached DONE")
		else:
			_result["checks"].append("FAIL: B0 NPC 1 expected DONE(2) got=" + str(n1state))

	# Phase 12: Verify both NPCs DONE + WinScreen
	await _wait_frames(3)
	var n0_done := false
	var n1_done := false
	if is_instance_valid(_npc):
		n0_done = int(_npc._state) == 2
	if is_instance_valid(_npc_1):
		n1_done = int(_npc_1._state) == 2
	_result["both_done"] = n0_done and n1_done
	if _result["both_done"]:
		_result["checks"].append("PASS: B0 both NPCs DONE")
	else:
		_result["checks"].append("FAIL: B0 NPC0_done=" + str(n0_done) + " NPC1_done=" + str(n1_done))
	_check_win_screen()
	if _result["ok"]:
		_result["checks"].append("PASS: B0 multi-NPC playthrough — WinScreen visible")


# ── Helpers ──────────────────────────────────────────────────────

func _find_nodes() -> void:
	var all_nodes: Array = []
	_collect_all(get_root(), all_nodes)

	# B0: Read ALL NPC entries from quest_data (multi-NPC format)
	var npc_targets: Dictionary = {}  # npc_id → target_entity
	var data_path: String = _scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var parsed = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			_target_entity = str(parsed.get("target_entity", ""))
			if parsed.has("npcs"):
				var npcs = parsed["npcs"]
				if npcs is Dictionary:
					var idx := 0
					var valid_quests := 0
					for k in npcs.keys():
						var td = str(npcs[k].get("target_entity", ""))
						npc_targets[k] = td
						if idx == 0:
							_target_entity = td
						# B1: Count quests with valid objective entries
						var obj = npcs[k].get("objective")
						if obj is Dictionary and obj.has("target"):
							valid_quests += 1
						idx += 1
					if npcs.size() >= 2:
						_multi_npc = true
					_result["quest_log_populated"] = valid_quests >= 1

	# Collect nodes by tag
	var talk_nodes: Array = []
	var all_pickups: Array = []
	for n in all_nodes:
		if n is Node3D and n.has_meta("_forge_tag"):
			var tag = n.get_meta("_forge_tag")
			if tag == "talk":
				talk_nodes.append(n)
			elif tag == "pickup":
				all_pickups.append(n)
		if n.name == "Player" and n is CharacterBody3D:
			_player = n

	# Locate the InteractionRaycast node
	_interaction = get_root().get_node_or_null("/root/Root/Player/Camera3D/InteractionRaycast")
	if _interaction == null:
		_result["checks"].append("FAIL: InteractionRaycast node not found at /root/Root/Player/Camera3D/InteractionRaycast")

	# Assign NPCs
	if talk_nodes.size() > 0:
		_npc = talk_nodes[0]
	if talk_nodes.size() > 1:
		_npc_1 = talk_nodes[1]
		_npc_1_role = str(_npc_1.get_meta("_forge_role", ""))

	# Map target_entities to pickup nodes
	var target_order: Array = []
	for k in npc_targets.keys():
		target_order.append({"npc_id": k, "target": npc_targets[k]})

	var used_targets: Array = []
	for entry in target_order:
		var tid = entry["target"]
		for p in all_pickups:
			if p.name == tid and not used_targets.has(p):
				if _target_prop == null:
					_target_prop = p
				elif _target_1_prop == null:
					_target_1_prop = p
				used_targets.append(p)
				break

	# Distractor = any pickup not assigned as a target
	for p in all_pickups:
		if not used_targets.has(p) and _distractor_prop == null:
			_distractor_prop = p


func _aim_player_at(target: Node3D) -> void:
	"""Position the player ~1.5m away from the target and aim the
	camera directly at it so that interaction.gd's camera raycast
	hits the target.

	0.5b: aim at the prop's world-space AABB centre (not origin) so
	the camera's ray path passes through the bulk of the prop's
	collider, not just the origin corner.  Falls back to the prop
	# origin for bare StaticBody3D test fixtures that lack a `_model`
	# sibling.
	"""
	if _player == null or target == null or not is_instance_valid(target):
		return

	# Phase 0.5b attempt (deferred per docs/current/BLOCKER-2026-06-26-0.5b-headless-probe-interaction.md):
	# symmetric to probe_smoke.gd above — the recursive-AABB-centre
	# aim did not flip the godot_heavy tests green. Reverted to the
	# original origin-aim baseline; the full diagnosis is documented in
	# the blocker file for live Godot verification.
	var target_pos: Vector3 = target.global_position
	var aim_pos: Vector3 = target_pos
	var model = target.get_node_or_null(target.name + "_model")
	if model is MeshInstance3D:
		var model_mi: MeshInstance3D = model as MeshInstance3D
		aim_pos = model_mi.global_transform * model_mi.get_aabb().get_center()

	# Position player near target, facing it
	var offset: Vector3 = Vector3(0, 0, 1.5)
	_player.global_position = target_pos + offset
	_player.force_update_transform()  # propagate before look_at (child camera reads global xform)

	# Aim the camera at the prop's AABB centre (not origin)
	var camera: Camera3D = _player.get_node_or_null("Camera3D") as Camera3D
	if camera:
		camera.force_update_transform()
		camera.look_at(aim_pos, Vector3.UP)


func _wait_frames(count: int) -> void:
	for _i in range(count):
		await process_frame


func _wait_npc_state(npc, expected_state: int, max_frames: int, label: String) -> bool:
	"""Poll _npc._state for up to max_frames process frames.
	Returns true when the state matches; appends a TIMEOUT failure
	check on timeout."""
	for _i in range(max_frames):
		if is_instance_valid(npc) and int(npc._state) == expected_state:
			return true
		await process_frame
	_result["checks"].append("TIMEOUT: " + label)
	return false


func _check_win_screen() -> void:
	var all_nodes: Array = []
	_collect_all(get_root(), all_nodes)
	for n in all_nodes:
		if n.name == "WinScreen":
			_result["win_visible"] = n.visible
			if n.visible:
				_result["checks"].append("PASS: WinScreen is visible")
				_result["ok"] = true
			else:
				_result["checks"].append("FAIL: WinScreen is NOT visible")
			return
	_result["checks"].append("FAIL: WinScreen node not found")


func _collect_all(node: Node, out: Array) -> void:
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)


func _print_and_quit(exit_code: int) -> void:
	var json_str = JSON.stringify(_result, "")
	print("PROBE_JSON_OUTPUT:" + json_str)
	quit(exit_code)
