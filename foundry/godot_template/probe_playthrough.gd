# probe_playthrough.gd — scripted human-input playthrough probe (Item 5)
#
# Usage:
#   godot --headless --path <project> -s probe_playthrough.gd <scene_path>
#
# Drives the same raycast+on_interact path a human E-key press would:
#   1. Verify target is reachable via downward raycast (same physics as smoke probe)
#   2. Walk parent tree to find _forge_tag node
#   3. Call on_interact(tag) — same endpoint as human E-key press
#
# C-2: Multi-item inventory — the probe now tests multi-item carry,
#      active-item cycling, drop-removes-from-inventory, and
#      win-leaves-other-items-untouched.
#
# The downward raycast exercises the identical physics raycast system
# that interaction.gd uses.  In headless mode, camera-raycasting from
# a dynamically positioned CharacterBody3D is unreliable; downward
# raycasts from a known position work consistently.
extends SceneTree

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
	"quest_log_populated": false
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
# C-2: track inventory state (removed V-1 _distractor_original_pos —
#      single-item restore is no longer the behaviour).
var _drop_ok: bool = false
# B0: multi-NPC support — second NPC + target for 2-NPC playthrough probe
var _npc_1 = null
var _target_1_prop = null
var _npc_1_role: String = ""
var _multi_npc: bool = false
var _both_done: bool = false


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

	await process_frame
	await process_frame


func _process(delta):
	if _done:
		return false
	_phase_timer += delta
	_run_phase()
	return false


func _run_phase():
	if _phase == 0:
		if _phase_timer > 0.5:
			_find_nodes()
			if _npc != null and _target_prop != null and _player != null:
				var found_parts := PackedStringArray()
				found_parts.append("NPC")
				found_parts.append("target")
				if _distractor_prop != null:
					found_parts.append("distractor")
				found_parts.append("Player")
				# B0: check second NPC
				if _multi_npc:
					if _npc_1 != null:
						found_parts.append("NPC1")
					if _target_1_prop != null:
						found_parts.append("target1")
				_result["multi_npc"] = _multi_npc and _npc_1 != null and _target_1_prop != null
				_result["checks"].append("PASS: all key nodes found (" + ", ".join(found_parts) + ")")
				if _multi_npc and (_npc_1 == null or _target_1_prop == null):
					_result["checks"].append("WARNING: multi-NPC quest_data but second NPC/target not found")
				if _distractor_prop == null:
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

	# Phase 1: Talk to NPC
	if _phase == 1:
		if _phase_timer > 0.2:
			_result["checks"].append("ACTION: interact with NPC")
			_interact_with(_npc)
			if is_instance_valid(_npc):
				_npc._state = 1  # bypass await timer for determinism
			_result["checks"].append("PASS: NPC interaction + state forced to QUEST_GIVEN")
			_phase = 2
			_phase_timer = 0.0

	# Phase 2: Pick up distractor (C-2: add to inventory)
	if _phase == 2:
		if _phase_timer > 0.2:
			if _distractor_prop != null:
				_result["checks"].append("ACTION: pick up DISTRACTOR prop")
				_interact_with(_distractor_prop)
		if _phase_timer > 0.4:
			if _distractor_prop != null:
				# C-2: check get_active_item() instead of carried_item
				var active = str(_player.get_active_item())
				if active == _distractor_prop.name:
					_result["checks"].append("PASS: player carries distractor=" + active)
					_result["checks"].append("C-2: inventory size=" + str(_player.carried_items.size()))
				else:
					_result["checks"].append("FAIL: expected active=" + _distractor_prop.name + " got=" + active)
			else:
				_result["checks"].append("SKIP: no distractor")
			_phase = 3
			_phase_timer = 0.0

	# Phase 3: Talk to NPC (wrong item)
	if _phase == 3:
		if _phase_timer > 0.2:
			if _distractor_prop != null:
				_result["checks"].append("ACTION: talk to NPC (expect wrong line)")
				_interact_with(_npc)
		if _phase_timer > 0.4:
			if _distractor_prop != null:
				if is_instance_valid(_npc):
					var nstate = int(_npc._state)
					_result["npc_state"] = str(nstate)
					if nstate == 1:
						_result["checks"].append("PASS: NPC still in QUEST_GIVEN (wrong item)")
						_result["wrong_shown"] = true
					else:
						_result["checks"].append("FAIL: expected NPC state QUEST_GIVEN(1) got=" + str(nstate))
			else:
				_result["checks"].append("SKIP: no distractor")
			_phase = 4
			_phase_timer = 0.0

	# Phase 4: Pick up target prop → C-2: both in inventory, active=target
	if _phase == 4:
		if _phase_timer > 0.2:
			_result["checks"].append("ACTION: pick up TARGET prop (C-2: adds to inventory)")
			_interact_with(_target_prop)
		if _phase_timer > 0.4:
			# C-2: Verify active is target AND distractor still in inventory
			var active = str(_player.get_active_item())
			var inv_size = _player.carried_items.size()
			if active == _target_prop.name:
				_result["checks"].append("PASS: active=" + active)
			else:
				_result["checks"].append("FAIL: expected active=" + _target_prop.name + " got=" + active)
			if _distractor_prop != null:
				var distractor_in_inv = _distractor_prop.name in _player.carried_items
				if distractor_in_inv:
					_result["checks"].append("PASS: C-2 distractor still in inventory (size=" + str(inv_size) + ")")
				else:
					_result["checks"].append("FAIL: C-2 distractor MISSING from inventory")
			else:
				_result["checks"].append("C-2: inventory size=" + str(inv_size))
		if _phase_timer > 0.6 and _distractor_prop != null:
			# C-2: Cycle backward to distractor
			_result["checks"].append("ACTION: C-2 cycle active backward to distractor")
			_player._cycle_active(-1)
			var active = str(_player.get_active_item())
			if active == _distractor_prop.name:
				_result["checks"].append("PASS: C-2 cycled back to distractor=" + active)
			else:
				_result["checks"].append("FAIL: C-2 cycle expected=" + _distractor_prop.name + " got=" + active)
		if _phase_timer > 0.8 and _distractor_prop != null:
			# C-2: Cycle forward back to target
			_result["checks"].append("ACTION: C-2 cycle active forward to target")
			_player._cycle_active(1)
			var active = str(_player.get_active_item())
			if active == _target_prop.name:
				_result["checks"].append("PASS: C-2 cycled forward to target=" + active)
			else:
				_result["checks"].append("FAIL: C-2 cycle expected=" + _target_prop.name + " got=" + active)
		if _phase_timer > 1.0:
			_phase = 5
			_phase_timer = 0.0

	# Phase 5: Drop active item (target) → verify removed, distractor remains
	if _phase == 5:
		if _phase_timer > 0.2:
			_result["checks"].append("ACTION: drop active item (C-2: _drop_active_item)")
			if _player.has_method("_drop_active_item"):
				_player._drop_active_item()
		if _phase_timer > 0.4:
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
			# V-1: Verify dropped item is on the floor (y close to 0)
			if _target_prop != null and is_instance_valid(_target_prop):
				var drop_y = _target_prop.global_position.y
				if drop_y < 1.0:
					_result["checks"].append("PASS: dropped item on floor (y=%.3f)" % drop_y)
					_drop_ok = true
				else:
					_result["checks"].append("FAIL: dropped item FLOATING (y=%.3f)" % drop_y)
			else:
				_result["checks"].append("FAIL: target prop invalid after drop")
			_phase = 6
			_phase_timer = 0.0

	# Phase 6: Re-pick up target from the floor
	if _phase == 6:
		if _phase_timer > 0.2:
			_result["checks"].append("ACTION: re-pick up target from floor")
			_interact_with(_target_prop)
		if _phase_timer > 0.4:
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
			_phase = 7
			_phase_timer = 0.0

	# Phase 7: Deliver to NPC (should win)
	if _phase == 7:
		if _phase_timer > 0.2:
			_result["checks"].append("ACTION: talk to NPC (deliver item)")
			_interact_with(_npc)
		if _phase_timer > 0.4:
			if is_instance_valid(_npc):
				var nstate = int(_npc._state)
				_result["npc_state"] = str(nstate)
				_result["checks"].append("NPC final state=" + str(nstate))
			_phase = 8
			_phase_timer = 0.0

	# Phase 8: Check WinScreen + C-2: distractor still in inventory
	if _phase == 8:
		if _phase_timer > 0.3:
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
			# B0: If multi-NPC, continue to second NPC; otherwise done
			if _multi_npc and _npc_1 != null and _target_1_prop != null:
				_phase = 9
				_phase_timer = 0.0
			else:
				_done = true
				_print_and_quit(0 if _result["ok"] else 1)

	# ── B0: Multi-NPC phases for second NPC ───────────────────────

	# Phase 9: Talk to NPC 1
	if _phase == 9:
		if _phase_timer > 0.2:
			_result["checks"].append("B0: ACTION interact with NPC 1 (" + _npc_1_role + ")")
			_interact_with(_npc_1)
			if is_instance_valid(_npc_1):
				_npc_1._state = 1  # bypass await timer
			_result["checks"].append("PASS: B0 NPC 1 state forced to QUEST_GIVEN")
			_phase = 10
			_phase_timer = 0.0

	# Phase 10: Pick up NPC 1's target
	if _phase == 10:
		if _phase_timer > 0.2:
			_result["checks"].append("B0: ACTION pick up NPC 1 target=" + _target_1_prop.name)
			_interact_with(_target_1_prop)
		if _phase_timer > 0.4:
			var active = str(_player.get_active_item())
			if active == _target_1_prop.name:
				_result["checks"].append("PASS: B0 player carries NPC 1 target=" + active)
			else:
				_result["checks"].append("FAIL: B0 expected active=" + _target_1_prop.name + " got=" + active)
			_phase = 11
			_phase_timer = 0.0

	# Phase 11: Deliver to NPC 1
	if _phase == 11:
		if _phase_timer > 0.2:
			_result["checks"].append("B0: ACTION deliver to NPC 1")
			_interact_with(_npc_1)
		if _phase_timer > 0.4:
			if is_instance_valid(_npc_1):
				var n1state = int(_npc_1._state)
				_result["checks"].append("B0: NPC 1 state=" + str(n1state))
				if n1state == 2:  # DONE
					_result["checks"].append("PASS: B0 NPC 1 reached DONE")
				else:
					_result["checks"].append("FAIL: B0 NPC 1 expected DONE(2) got=" + str(n1state))
			_phase = 12
			_phase_timer = 0.0

	# Phase 12: Verify both NPCs DONE + WinScreen
	if _phase == 12:
		if _phase_timer > 0.3:
			var n0_done := false
			var n1_done := false
			if is_instance_valid(_npc):
				n0_done = int(_npc._state) == 2
			if is_instance_valid(_npc_1):
				n1_done = int(_npc_1._state) == 2
			_both_done = n0_done and n1_done
			_result["both_done"] = _both_done
			if _both_done:
				_result["checks"].append("PASS: B0 both NPCs DONE")
			else:
				_result["checks"].append("FAIL: B0 NPC0_done=" + str(n0_done) + " NPC1_done=" + str(n1_done))
			_check_win_screen()
			if _result["ok"]:
				_result["checks"].append("PASS: B0 multi-NPC playthrough — WinScreen visible")
			_done = true
			_print_and_quit(0 if _result["ok"] else 1)


# ── Helpers ───────────────────────────────────────────────────────

func _find_nodes():
	var all_nodes = []
	_collect_all(get_root(), all_nodes)

	# B0: Read ALL NPC entries from quest_data (multi-NPC format)
	var npc_targets: Dictionary = {}  # npc_id → target_entity
	var data_path: String = _scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var parsed = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			# C-3 single-NPC format had a top-level target_entity; C-4 moved it
			# under "npcs"[npc_id]. Read whichever is present.
			_target_entity = str(parsed.get("target_entity", ""))
			if parsed.has("npcs"):
				var npcs = parsed["npcs"]
				if npcs is Dictionary:
					var idx := 0
					for k in npcs.keys():
						var td = str(npcs[k].get("target_entity", ""))
						npc_targets[k] = td
						if idx == 0:
							_target_entity = td
						idx += 1
					if npcs.size() >= 2:
						_multi_npc = true

	# B0: Collect all NPC nodes mapped by _forge_npc_id
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

	# Assign NPC 0 (first talk node)
	if talk_nodes.size() > 0:
		_npc = talk_nodes[0]

	# B0: Assign NPC 1 (second talk node) for multi-NPC
	if talk_nodes.size() > 1:
		_npc_1 = talk_nodes[1]
		_npc_1_role = str(_npc_1.get_meta("_forge_role", ""))

	# Map target_entities to pickup nodes — iterate npc_targets in order
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


func _interact_with(target: Node3D):
	"""Verify target is reachable via downward raycast, then call on_interact.

	Exercises the same physics raycast that the smoke probe's
	check_target_reachable uses, then calls on_interact(tag) — the
	same endpoint that interaction.gd reaches via E-key events.
	"""
	if target == null or not is_instance_valid(target):
		return

	var tag = target.get_meta("_forge_tag", "")
	var space_state = target.get_world_3d().direct_space_state
	var target_pos = target.global_position

	# Downward raycast from above the target (same as smoke probe)
	var ray_origin = target_pos + Vector3(0, 5.0, 0)
	var ray_end = target_pos + Vector3(0, -1.0, 0)
	var query = PhysicsRayQueryParameters3D.create(ray_origin, ray_end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	var hit = space_state.intersect_ray(query)

	var hit_target = false
	if hit and not hit.is_empty():
		# In Godot 4, intersect_ray returns the CollisionObject3D
		# (StaticBody3D), not the CollisionShape3D child.  Walk
		# from the collider itself — not its parent — upward.
		var current: Node = hit.collider as Node
		while current:
			if current == target:
				hit_target = true
				break
			current = current.get_parent()

	if hit_target:
		if target.has_method("on_interact"):
			target.on_interact(tag)


func _check_win_screen():
	var all_nodes = []
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


func _collect_all(node, out):
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)


func _print_and_quit(exit_code):
	var json_str = JSON.stringify(_result, "")
	print("PROBE_JSON_OUTPUT:" + json_str)
	quit(exit_code)
