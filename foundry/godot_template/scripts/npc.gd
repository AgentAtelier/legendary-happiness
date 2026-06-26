# NPC — handles talk (dialogue) and give (item check).
# State machine: IDLE -> QUEST_GIVEN -> DONE.
# Loads quest data from _quest_data.json alongside the scene.
# C-3: Quest-state persistence via the world-model transactional log.
#       On _ready(), replays the log to find current npc_state.
#       On state change, appends a "replace" event to the log.
# B1: Emits quest_state_changed signal so HUD can track multi-quest progress.
# B1: Idle micro-animation — breath scale + sway via Tween.
# CB-3: NavigationAgent3D + idle-wander — NPCs path to random points
#       on the navmesh and pause between moves.
# CB-7: Skeleton3D + AnimationPlayer — procedural humanoid rig with
#       idle/walk skeletal animations.
extends Node3D

enum State { IDLE, QUEST_GIVEN, DONE }

signal quest_state_changed(npc_id: String, state: int)

var _state: int = State.IDLE
var _quest_data: Dictionary = {}
# Spine Slice 3: NPC soul (substrate + axes)
var _soul: Dictionary = {}
# C-3: world log persistence
var _npc_id: String = ""
var _world_log_path: String = ""
var _base_placement: Dictionary = {}
# EB-6: idle bark rotation
var _idle_barks: Array[String] = []
var _idle_bark_index: int = -1
var _idle_bark_timer: float = 0.0
const _IDLE_BARK_INTERVAL: float = 12.0  # seconds between barks

# B1: idle anim (fallback when no Skeleton3D)
var _idle_tween: Tween = null
var _breath_scale_high: float = 1.03
var _breath_period: float = 3.5  # seconds for one breath cycle
# Spine Slice 3: courage-based idle tweak — timid NPCs breathe slower +
# less pronounced sway (smaller visual presence)
var _breath_scale_low: float = 1.0
var _sway_angle: float = 0.02
var _sway_direction_sign: float = 1.0

# CB-7: Skeleton + AnimationPlayer refs
var _skeleton: Skeleton3D = null
var _anim_player: AnimationPlayer = null
var _has_skeletal_rig: bool = false
var _last_wander_state: int = -1  # CB-7: track state transitions for animation


func _ready() -> void:
	_load_quest_data()
	# C-3: Restore NPC state from the world log (survives reload)
	_restore_state_from_log()
	# CB-7: Set up skeletal rig first (before animation)
	_setup_skeleton()
	# B1: Start idle micro-animation (breath + sway) — fallback if no skeleton
	_start_idle_anim()
	# CB-3: Set up NavigationAgent3D for idle-wander
	_setup_navigation()


func _load_quest_data() -> void:
	var scene_path: String = get_tree().current_scene.scene_file_path
	var data_path: String = scene_path.replace(".tscn", "_quest_data.json")
	var file = FileAccess.open(data_path, FileAccess.READ)
	if file:
		var text: String = file.get_as_text()
		var parsed = JSON.parse_string(text)
		if parsed is Dictionary:
			# C-4: Read npc_id from this node's metadata (set by scene_compiler)
			_npc_id = str(get_meta("_forge_npc_id", "NPC"))
			_world_log_path = str(parsed.get("world_log_path", ""))
			# C-4: Look up this NPC's data in the shared npcs dict
			var npcs_data = parsed.get("npcs", {})
			var my_data = npcs_data.get(_npc_id, {})
			if my_data and not my_data.is_empty():
				_quest_data = my_data
				_base_placement = my_data.get("npc_placement", {})
				# Spine Slice 3: read soul from quest_data
				var raw_soul = my_data.get("soul", {})
				if raw_soul is Dictionary and not raw_soul.is_empty():
					_soul = raw_soul
			else:
				# Fallback: single-NPC format (C-3 backward compat)
				_quest_data = parsed
				_base_placement = parsed.get("npc_placement", {})
		# EB-6: Load idle barks
		var raw_barks = _quest_data.get("idle_barks", [])
		if raw_barks is Array and raw_barks.size() > 0:
			for b in raw_barks:
				_idle_barks.append(str(b))
			_idle_bark_index = 0
			_idle_bark_timer = _IDLE_BARK_INTERVAL  # start after interval


func on_interact(tag: String) -> void:
	if tag != "talk":
		return
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_talk()
	var hud = get_node("/root/Root/HUD")
	match _state:
		State.IDLE:
			_show_line(hud, "greet")
			await _wait_for_advance()
			_show_line(hud, "ask")
			_state = State.QUEST_GIVEN
			# B1: Emit signal for HUD quest tracking
			quest_state_changed.emit(_npc_id, _state)
			# C-3: Persist state change to world log
			_append_state_to_log("quest_given")
			# B1: subtitle — push greet + ask to subtitle panel
			_push_subtitle("greet")
			_push_subtitle("ask")
		State.QUEST_GIVEN:
			var player = get_node("/root/Root/Player")
			# C-2: Use get_active_item() for multi-item inventory
			var carried: String = ""
			if player.has_method("get_active_item"):
				carried = player.get_active_item()

			# CB-1: Check if this NPC's quest is locked by depends_on chain
			var quest_id: String = _quest_data.get("quest_id", "")
			var qm = get_node_or_null("/root/QuestManager")
			if qm and quest_id != "" and qm.has_method("is_quest_locked"):
				if qm.is_quest_locked(quest_id):
					_show_line(hud, "greet")  # friendly but no quest yet
					if hud.has_method("set_objective"):
						hud.set_objective("This quest is not yet available.")
					return

			# CB-1: Try deliver first (player carrying item to recipient NPC)
			var matched := false
			if qm and qm.has_method("try_complete_deliver"):
				if qm.try_complete_deliver(_npc_id, carried):
					matched = true
			# CB-1: Try talk (player speaking to target NPC)
			if not matched and qm and qm.has_method("try_complete_talk"):
				if qm.try_complete_talk(_npc_id):
					matched = true

			if matched:
				_show_line(hud, "thank")
				_state = State.DONE
				quest_state_changed.emit(_npc_id, _state)
				_append_state_to_log("done")
				_push_subtitle("thank")
				_try_emit_win()
				return

			# Default: fetch — check if carried item matches target
			var target: String = _quest_data.get("target_entity", "")
			if carried == target:
				# CB-1: Mark quest complete via QuestManager
				if qm and quest_id != "" and qm.has_method("complete_quest"):
					qm.complete_quest(quest_id)
				_show_line(hud, "thank")
				_state = State.DONE
				# B1: Emit signal for HUD quest tracking
				quest_state_changed.emit(_npc_id, _state)
				# C-3: Persist state change to world log
				_append_state_to_log("done")
				# B1: subtitle — push thank line
				_push_subtitle("thank")
				# B1: Defer win emission to HUD (multi-quest gate)
				_try_emit_win()
			else:
				_show_line(hud, "wrong")
				# B1: subtitle — push wrong line
				_push_subtitle("wrong")
				await _wait_for_advance()
				_show_line(hud, "ask")
		State.DONE:
			_show_line(hud, "thank")


func _wait_for_advance() -> void:
	"""Wait for Space/Enter key press, showing 'Space to continue' hint.

	U-6: In headless mode (Godot smoke tests), skip the wait entirely
	so the V-1 probe can drive the dialogue without keyboard input."""
	if OS.has_feature("headless"):
		return
	var hud = get_node("/root/Root/HUD")
	if hud.has_method("show_interact"):
		hud.show_interact("Space to continue")
	# Wait for Space or Enter key
	while true:
		await get_tree().process_frame
		if Input.is_key_pressed(KEY_SPACE) or Input.is_key_pressed(KEY_ENTER):
			break
	if hud.has_method("show_interact"):
		hud.show_interact("")
	# Debounce: wait until keys are released
	while Input.is_key_pressed(KEY_SPACE) or Input.is_key_pressed(KEY_ENTER):
		await get_tree().process_frame


# ── C-3: World-log persistence ──────────────────────────────────────

func _restore_state_from_log() -> void:
	"""C-3: Replay the world log backwards to find this NPC's last
	state, then set _state accordingly.  Survives scene reload.

	Note: Reads the entire log into memory and scans backwards — O(n)
	in log size.  Fine for C-3 with a single NPC and short logs.
	For C-4, consider seeking to end and scanning backwards in chunks."""
	if _world_log_path == "":
		return
	var file = FileAccess.open(_world_log_path, FileAccess.READ)
	if not file:
		return
	var text: String = file.get_as_text()
	var lines: PackedStringArray = text.split("\n")
	# Walk backwards — first matching event wins (most recent state)
	for i in range(lines.size() - 1, -1, -1):
		var line: String = lines[i].strip_edges()
		if line == "":
			continue
		var event = JSON.parse_string(line)
		if event is Dictionary:
			var placement = event.get("placement", {})
			if placement.get("id") == _npc_id:
				var attrs = placement.get("attrs", {})
				var saved_state: String = str(attrs.get("npc_state", "idle"))
				_state = _state_from_string(saved_state)
				return


func _append_state_to_log(state_name: String) -> void:
	"""C-3: Append a 'replace' event to the world log with the new
	npc_state.  Uses the full base_placement from quest_data so we
	don't lose asset_hash or other attrs."""
	if _world_log_path == "" or _base_placement.is_empty():
		return
	var placement: Dictionary = _base_placement.duplicate(true)
	var attrs: Dictionary = placement.get("attrs", {}).duplicate(true)
	attrs["npc_state"] = state_name
	placement["attrs"] = attrs
	var event: Dictionary = {
		"action": "replace",
		"placement": placement,
	}
	# Use READ_WRITE (non-truncating) so we don't destroy previous
	# log entries.  Fall back to WRITE (which creates+truncates) only
	# when the log doesn't exist yet.
	var file = FileAccess.open(_world_log_path, FileAccess.READ_WRITE)
	if not file:
		file = FileAccess.open(_world_log_path, FileAccess.WRITE)
	if file:
		file.seek_end()
		file.store_line(JSON.stringify(event))


func _state_from_string(state_name: String) -> int:
	match state_name:
		"quest_given":
			return State.QUEST_GIVEN
		"done":
			return State.DONE
		_:
			return State.IDLE


# ── Dialogue display + win ───────────────────────────────────────────

func _show_line(hud: Node, key: String) -> void:
	var line: String = _quest_data.get("dialogue", {}).get(key, "...")
	# C-4: Prepend NPC role to the objective line for player context
	var npc_role: String = _quest_data.get("npc_role", "")
	if npc_role != "" and key in ["greet", "ask", "wrong", "thank"]:
		line = npc_role.capitalize() + ": " + line
	if hud.has_method("set_objective"):
		hud.set_objective(line)


func _emit_win() -> void:
	# C-1: audio feedback
	if has_node("/root/Audio"):
		get_node("/root/Audio").play_win()
	var win = get_node("/root/Root/WinScreen")
	if win.has_method("show_win"):
		win.show_win()


# ── B1: Multi-quest win gate ─────────────────────────────────────

func _try_emit_win() -> void:
	"""Check if all NPCs in the scene are DONE.  If so, emit win.
	Otherwise, just let the HUD counter update."""
	var all_nodes: Array = []
	var root = get_node("/root/Root")
	_collect_all(root, all_nodes)
	var total_npcs := 0
	var done_npcs := 0
	for n in all_nodes:
		if n.has_meta("_forge_tag") and n.get_meta("_forge_tag") == "talk":
			total_npcs += 1
			if int(n._state) == State.DONE:
				done_npcs += 1
	# Update HUD counter
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("update_quest_counter"):
		hud.update_quest_counter(done_npcs, total_npcs)
	# Win only when ALL NPCs are done
	if total_npcs > 0 and done_npcs >= total_npcs:
		_emit_win()


func _collect_all(node, out: Array) -> void:
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)


# ── B1: Subtitle push ────────────────────────────────────────────

func _push_subtitle(line_key: String) -> void:
	"""Push a dialogue line to the subtitle scrollback panel."""
	var line: String = _quest_data.get("dialogue", {}).get(line_key, "")
	if line == "":
		return
	var npc_role: String = _quest_data.get("npc_role", "")
	var prefix = npc_role.capitalize() if npc_role != "" else "NPC"
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("push_subtitle"):
		hud.push_subtitle(prefix + ": " + line)


# ── CB-7: Skeletal rig + procedural animations ───────────────────

# Bone hierarchy (mirrors _BONE_DEFS in scene_compiler.py):
# (bone_name, parent_index, rest_x, rest_y, rest_z)
const _BONE_HIERARCHY: Array = [
	{"name": "Hips",        "parent": -1, "rest": Vector3(0.0, 1.0, 0.0)},
	{"name": "Spine",       "parent": 0,  "rest": Vector3(0.0, 1.3, 0.0)},
	{"name": "Chest",       "parent": 1,  "rest": Vector3(0.0, 1.6, 0.0)},
	{"name": "Neck",        "parent": 2,  "rest": Vector3(0.0, 1.85, 0.0)},
	{"name": "Head",        "parent": 3,  "rest": Vector3(0.0, 2.0, 0.0)},
	{"name": "UpperArm.L",  "parent": 2,  "rest": Vector3(0.35, 1.55, 0.0)},
	{"name": "LowerArm.L",  "parent": 5,  "rest": Vector3(0.35, 1.25, 0.0)},
	{"name": "Hand.L",      "parent": 6,  "rest": Vector3(0.35, 0.95, 0.0)},
	{"name": "UpperArm.R",  "parent": 2,  "rest": Vector3(-0.35, 1.55, 0.0)},
	{"name": "LowerArm.R",  "parent": 8,  "rest": Vector3(-0.35, 1.25, 0.0)},
	{"name": "Hand.R",      "parent": 9,  "rest": Vector3(-0.35, 0.95, 0.0)},
	{"name": "UpperLeg.L",  "parent": 0,  "rest": Vector3(0.15, 0.8, 0.0)},
	{"name": "LowerLeg.L",  "parent": 11, "rest": Vector3(0.15, 0.4, 0.0)},
	{"name": "Foot.L",      "parent": 12, "rest": Vector3(0.15, 0.05, 0.1)},
	{"name": "UpperLeg.R",  "parent": 0,  "rest": Vector3(-0.15, 0.8, 0.0)},
	{"name": "LowerLeg.R",  "parent": 14, "rest": Vector3(-0.15, 0.4, 0.0)},
	{"name": "Foot.R",      "parent": 15, "rest": Vector3(-0.15, 0.05, 0.1)},
]

# Animation params
const _WALK_PERIOD: float = 1.0       # seconds for one walk cycle
const _IDLE_BREATH_PERIOD: float = 4.0 # seconds for one idle breath cycle
const _LEG_SWING_ANGLE: float = 0.4    # radians leg swing during walk
const _ARM_SWING_ANGLE: float = 0.3    # radians arm swing during walk
const _BODY_BOB_HEIGHT: float = 0.04   # metres body bob during walk


func _setup_skeleton() -> void:
	"""CB-7: Build the bone hierarchy on the Skeleton3D child node."""
	_skeleton = get_node_or_null("Skeleton")
	if not _skeleton or not (_skeleton is Skeleton3D):
		return

	# Add bones
	for b in _BONE_HIERARCHY:
		var bone_idx = _skeleton.get_bone_count()
		_skeleton.add_bone(str(b["name"]))
		_skeleton.set_bone_parent(bone_idx, int(b["parent"]))
		# Set rest pose
		var rest_xform = Transform3D.IDENTITY
		rest_xform.origin = b["rest"] as Vector3
		_skeleton.set_bone_rest(bone_idx, rest_xform)

	# Find AnimationPlayer
	_anim_player = get_node_or_null("AnimationPlayer")
	if _anim_player and (_anim_player is AnimationPlayer):
		_anim_player.root_node = NodePath("../Skeleton")
		_setup_animations()
		_has_skeletal_rig = true


func _setup_animations() -> void:
	"""CB-7: Create procedural idle and walk animation libraries."""
	if not _anim_player:
		return

	# Create animation library
	var lib = AnimationLibrary.new()

	# --- idle animation: subtle breathing on spine + gentle arm sway ---
	var idle_anim = Animation.new()
	idle_anim.length = _IDLE_BREATH_PERIOD
	idle_anim.loop_mode = Animation.LOOP_LINEAR

	var spine_idx = _skeleton.find_bone("Spine")
	var chest_idx = _skeleton.find_bone("Chest")
	var arm_l_idx = _skeleton.find_bone("UpperArm.L")
	var arm_r_idx = _skeleton.find_bone("UpperArm.R")

	# Spine scale breathing (Y scale oscillates)
	if spine_idx >= 0:
		var track_idx = idle_anim.add_track(Animation.TYPE_POSITION_3D)
		idle_anim.track_set_path(track_idx, "Spine")
		idle_anim.position_track_insert_key(track_idx, 0.0, Vector3(0, 1.3, 0))
		idle_anim.position_track_insert_key(track_idx, _IDLE_BREATH_PERIOD * 0.5, Vector3(0, 1.32, 0))
		idle_anim.position_track_insert_key(track_idx, _IDLE_BREATH_PERIOD, Vector3(0, 1.3, 0))

	# Chest scale breathing
	if chest_idx >= 0:
		var track_idx = idle_anim.add_track(Animation.TYPE_POSITION_3D)
		idle_anim.track_set_path(track_idx, "Chest")
		idle_anim.position_track_insert_key(track_idx, 0.0, Vector3(0, 1.6, 0))
		idle_anim.position_track_insert_key(track_idx, _IDLE_BREATH_PERIOD * 0.5, Vector3(0, 1.62, 0))
		idle_anim.position_track_insert_key(track_idx, _IDLE_BREATH_PERIOD, Vector3(0, 1.6, 0))

	# Arms gentle sway during idle
	if arm_l_idx >= 0:
		var track_idx = idle_anim.add_track(Animation.TYPE_ROTATION_3D)
		idle_anim.track_set_path(track_idx, "UpperArm.L")
		idle_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion.IDENTITY)
		idle_anim.rotation_track_insert_key(track_idx, _IDLE_BREATH_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), 0.04))
		idle_anim.rotation_track_insert_key(track_idx, _IDLE_BREATH_PERIOD, Quaternion.IDENTITY)

	if arm_r_idx >= 0:
		var track_idx = idle_anim.add_track(Animation.TYPE_ROTATION_3D)
		idle_anim.track_set_path(track_idx, "UpperArm.R")
		idle_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion.IDENTITY)
		idle_anim.rotation_track_insert_key(track_idx, _IDLE_BREATH_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), -0.04))
		idle_anim.rotation_track_insert_key(track_idx, _IDLE_BREATH_PERIOD, Quaternion.IDENTITY)

	lib.add_animation("idle", idle_anim)

	# --- walk animation: leg/arm swing + body bob ---
	var walk_anim = Animation.new()
	walk_anim.length = _WALK_PERIOD
	walk_anim.loop_mode = Animation.LOOP_LINEAR

	var hip_idx = _skeleton.find_bone("Hips")
	var uleg_l_idx = _skeleton.find_bone("UpperLeg.L")
	var lleg_l_idx = _skeleton.find_bone("LowerLeg.L")
	var uleg_r_idx = _skeleton.find_bone("UpperLeg.R")
	var lleg_r_idx = _skeleton.find_bone("LowerLeg.R")

	# Hips vertical bob
	if hip_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_POSITION_3D)
		walk_anim.track_set_path(track_idx, "Hips")
		walk_anim.position_track_insert_key(track_idx, 0.0, Vector3(0, 1.0, 0))
		walk_anim.position_track_insert_key(track_idx, _WALK_PERIOD * 0.25, Vector3(0, 1.0 + _BODY_BOB_HEIGHT, 0))
		walk_anim.position_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Vector3(0, 1.0, 0))
		walk_anim.position_track_insert_key(track_idx, _WALK_PERIOD * 0.75, Vector3(0, 1.0 + _BODY_BOB_HEIGHT, 0))
		walk_anim.position_track_insert_key(track_idx, _WALK_PERIOD, Vector3(0, 1.0, 0))

	# Left leg swing (forward at t=0, back at t=0.5)
	if uleg_l_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "UpperLeg.L")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), _LEG_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), -_LEG_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), _LEG_SWING_ANGLE))

	# Left lower leg follow-through
	if lleg_l_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "LowerLeg.L")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), -0.2))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.25, Quaternion(Vector3(1, 0, 0), -0.1))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), -0.3))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.75, Quaternion(Vector3(1, 0, 0), -0.1))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), -0.2))

	# Right leg swing (opposite phase — back at t=0, forward at t=0.5)
	if uleg_r_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "UpperLeg.R")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), -_LEG_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), _LEG_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), -_LEG_SWING_ANGLE))

	if lleg_r_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "LowerLeg.R")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), -0.3))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.25, Quaternion(Vector3(1, 0, 0), -0.1))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), -0.2))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.75, Quaternion(Vector3(1, 0, 0), -0.1))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), -0.3))

	# Arms swing opposite to legs
	if arm_l_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "UpperArm.L")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), -_ARM_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), _ARM_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), -_ARM_SWING_ANGLE))

	if arm_r_idx >= 0:
		var track_idx = walk_anim.add_track(Animation.TYPE_ROTATION_3D)
		walk_anim.track_set_path(track_idx, "UpperArm.R")
		walk_anim.rotation_track_insert_key(track_idx, 0.0, Quaternion(Vector3(1, 0, 0), _ARM_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD * 0.5, Quaternion(Vector3(1, 0, 0), -_ARM_SWING_ANGLE))
		walk_anim.rotation_track_insert_key(track_idx, _WALK_PERIOD, Quaternion(Vector3(1, 0, 0), _ARM_SWING_ANGLE))

	lib.add_animation("walk", walk_anim)

	# Add library and start idle
	_anim_player.add_animation_library("npc_anim", lib)
	_anim_player.play("npc_anim/idle")


func _get_body_node():
	"""CB-7: Find the Body GLB instance — now under HipsAttachment when rig exists."""
	if _has_skeletal_rig:
		var ha = get_node_or_null("HipsAttachment")
		if ha:
			return ha.get_node_or_null("Body")
		return null
	return get_node_or_null("Body")


# ── CB-3: Navigation + idle-wander ─────────────────────────────

# Idle-wander states
enum WanderState { IDLE, WANDER, PAUSE }
var _wander_state: int = WanderState.IDLE
var _wander_timer: float = 0.0
var _wander_pause_time: float = 4.0  # seconds between moves
var _wander_speed: float = 1.2       # NPC walk speed (m/s)
var _nav_agent: NavigationAgent3D = null
var _needs: Dictionary = {}          # CB-3: per-NPC needs


func _setup_navigation() -> void:
	"""CB-3: Create a NavigationAgent3D child and set up wander params."""
	_nav_agent = NavigationAgent3D.new()
	_nav_agent.radius = 0.3
	_nav_agent.height = 2.0
	_nav_agent.max_speed = _wander_speed
	_nav_agent.path_desired_distance = 0.5
	_nav_agent.target_desired_distance = 0.3
	add_child(_nav_agent)

	# Read needs from quest_data
	var raw_needs = _quest_data.get("needs", {})
	if raw_needs is Dictionary:
		_needs = raw_needs

	# Start wandering after a short delay
	_wander_state = WanderState.PAUSE
	_wander_timer = 2.0


func _pick_wander_target() -> Vector3:
	"""Pick a random reachable point on the navmesh within the room bounds."""
	var nav_region = get_node_or_null("/root/Root/NavigationRegion3D")
	if not nav_region:
		return global_position  # fallback: stay put

	# CB-3: derive bounds from current position offset (stays within the room)
	# Default room is ~20×20 with wall margins; keep targets within 8 m radius
	# Synchronous pick (no await → not a coroutine, so callers don't need
	# await). The wander state machine re-checks reachability as it paths there.
	var spread := 7.0
	var tx := global_position.x + randf_range(-spread, spread)
	var tz := global_position.z + randf_range(-spread, spread)
	return Vector3(tx, 0.0, tz)


func _wander_move(delta: float) -> void:
	"""Move the NPC toward the nav target.  npc.gd is attached to
	the NPC StaticBody3D, so self IS the NPC node."""
	if _nav_agent.is_navigation_finished():
		return
	var next_pos := _nav_agent.get_next_path_position()
	var dir := (next_pos - global_position).normalized()
	if dir.length() > 0.01:
		# CB-3 fix: move self (the NPC StaticBody3D), not the parent (Root)
		global_position += dir * _wander_speed * delta
		# CB-7: Rotate the Body (under HipsAttachment) to face movement direction
		var body = _get_body_node()
		if body:
			var look_dir := Vector3(dir.x, 0, dir.z).normalized()
			if look_dir.length() > 0.01:
				body.look_at(body.global_position + look_dir, Vector3.UP)


# ── EB-6: Idle bark process ──────────────────────────────────

func _process(delta: float) -> void:
	"""Drive the idle bark timer + CB-3 idle-wander."""
	# CB-3: Idle-wander state machine
	_wander_timer -= delta
	match _wander_state:
		WanderState.PAUSE:
			if _wander_timer <= 0.0:
				# Pick a new wander target
				var target := _pick_wander_target()
				if target != global_position:
					_nav_agent.target_position = target
					_wander_state = WanderState.WANDER
		WanderState.WANDER:
			if _nav_agent.is_navigation_finished():
				# Reached target — pause before next move
				_wander_state = WanderState.PAUSE
				_wander_timer = _wander_pause_time + randf_range(-1.5, 1.5)
			else:
				_wander_move(delta)
		WanderState.IDLE:
			# Initial state — transition to pause
			_wander_state = WanderState.PAUSE
			_wander_timer = 1.0

	# CB-7: Play skeletal animation on state transition (not every frame)
	if _has_skeletal_rig and _anim_player and _wander_state != _last_wander_state:
		_last_wander_state = _wander_state
		if _wander_state == WanderState.WANDER:
			_anim_player.play("npc_anim/walk")
		elif _wander_state == WanderState.PAUSE:
			_anim_player.play("npc_anim/idle")

	# EB-6: Idle bark timer
	if _idle_barks.is_empty():
		return
	_idle_bark_timer -= delta
	if _idle_bark_timer <= 0.0:
		_idle_bark_timer = _IDLE_BARK_INTERVAL
		if _idle_bark_index >= 0 and _idle_bark_index < _idle_barks.size():
			_push_subtitle_line(_idle_barks[_idle_bark_index])
			_idle_bark_index = (_idle_bark_index + 1) % _idle_barks.size()


func _push_subtitle_line(line: String) -> void:
	"""Push a raw line to the subtitle without NPC prefix."""
	var hud = get_node_or_null("/root/Root/HUD")
	if hud and hud.has_method("push_subtitle"):
		hud.push_subtitle("[" + str(get_meta("_forge_role", "NPC")) + "] " + line)


# ── B1: Idle micro-animation ─────────────────────────────────────

func _start_idle_anim() -> void:
	"""Start a looping Tween that animates breath scale + slight sway.

	Spine Slice 3: timid NPCs (courage <= -0.33) get slower breathing,
	subtler sway — a small visible cue of their personality.

	CB-7: When skeletal rig exists, the AnimationPlayer handles idle
	animation. This Tween is a fallback for scenes without Skeleton3D."""
	if _has_skeletal_rig:
		return  # Skeletal animation handles idle/walk
	if _idle_tween and _idle_tween.is_valid():
		_idle_tween.kill()

	# Spine Slice 3: adjust animation params from soul
	var anim_period := _breath_period
	var anim_scale_high := _breath_scale_high
	var anim_sway := _sway_angle
	if not _soul.is_empty():
		var sub = _soul.get("substrate", {})
		if sub is Dictionary:
			var courage: float = float(sub.get("courage", 0.0))
			if courage <= -0.33:
				# Timid: slower, shallower, randomised sway dir
				anim_period = _breath_period * 1.6
				anim_scale_high = 1.015
				anim_sway = 0.01
				_sway_direction_sign = -1.0 if randi() % 2 == 0 else 1.0

	_idle_tween = create_tween()
	_idle_tween.set_loops(0)  # infinite
	# Breath: scale oscillates between 1.0 and anim_scale_high
	# Sway: slight rotation on Z axis (timid NPCs sway opposite direction)
	var body = _get_body_node()
	if body:
		var half_period := anim_period / 2.0
		# Breath in
		_idle_tween.tween_property(body, "scale", Vector3(anim_scale_high, anim_scale_high, anim_scale_high), half_period).set_ease(Tween.EASE_IN_OUT)
		# Sway right while breathing in
		_idle_tween.parallel().tween_property(body, "rotation:z", anim_sway * _sway_direction_sign, half_period).set_ease(Tween.EASE_IN_OUT)
		# Breath out
		_idle_tween.tween_property(body, "scale", Vector3(1.0, 1.0, 1.0), half_period).set_ease(Tween.EASE_IN_OUT)
		# Sway left while breathing out
		_idle_tween.parallel().tween_property(body, "rotation:z", -anim_sway * _sway_direction_sign, half_period).set_ease(Tween.EASE_IN_OUT)
