# probe_smoke.gd — Godot-in-the-loop smoke test probe
#
# Usage:
#   godot --headless --path <project> -s probe_smoke.gd <scene_path>
#
# Loads the compiled scene, inspects the scene tree, and writes a single-
# line JSON result to stdout preceded by a marker so the Python harness
# can extract it cleanly from Godot engine output.
#
# Checks:
#   1. MeshInstance3D_count > 0 (props rendered)
#   2. A floor StaticBody3D + CollisionShape3D exists
#   3. Player has a CollisionShape3D
#   4. No "Resource file not found" / "non-existent resource" errors
#      in the output log (checked by Python harness via stderr)
#   5. The target prop is reachable by a downward/forward raycast
#   6. WorldEnvironment node exists (Item 1)
#   7. DirectionalLight3D exists (Item 1)
#   8. Visible room shell: FloorMesh, walls, Ceiling (Item 2)
#   9. Player body MeshInstance3D exists (Item 4)
#  10. Player is_on_floor() after physics step (Item 4)
extends SceneTree

var _result := {
	"ok": false,
	"mesh_count": 0,
	"floor_collision": false,
	"player_collision": false,
	"target_reachable": false,
	"world_env": false,
	"directional_light": false,
	"room_shell_ok": false,
	"player_body": false,
	"player_grounded": false,
	"audio_synth": false,
	"checks": []
}


func _init():
	var args := OS.get_cmdline_args()
	var scene_path := ""
	for i in range(len(args)):
		if args[i].ends_with("probe_smoke.gd") and i + 1 < len(args):
			scene_path = args[i + 1]
			break

	if scene_path == "":
		for i in range(len(args)):
			if not args[i].begins_with("-") and not args[i].ends_with(".gd"):
				scene_path = args[i]
				break

	if scene_path == "":
		_result["checks"].append("ERROR: no scene path provided")
		_print_and_quit(1)

	var err = change_scene_to_file(scene_path)
	if err != OK:
		_result["checks"].append("ERROR: failed to load scene %s (err=%d)" % [scene_path, err])
		_print_and_quit(1)

	await process_frame
	await process_frame

	_run_checks()
	_print_and_quit(0 if _result["ok"] else 1)


func _run_checks():
	var all_nodes: Array[Node] = []
	_collect_all(get_root(), all_nodes)

	if all_nodes.is_empty():
		_result["checks"].append("FAIL: no nodes in scene tree")
		_result["ok"] = false
		return

	_check_mesh_count(all_nodes)
	_check_floor(all_nodes)
	_check_player_collision(all_nodes)
	_check_target_reachable(all_nodes)
	_check_lights(all_nodes)
	_check_room_shell(all_nodes)
	_check_player_body(all_nodes)
	_check_player_grounded(all_nodes)
	_check_audio_synth(all_nodes)

	_result["ok"] = true
	for check in _result["checks"]:
		if check.begins_with("FAIL") or check.begins_with("ERROR"):
			_result["ok"] = false
			break


func _collect_all(node: Node, out: Array[Node]):
	out.append(node)
	for child in node.get_children():
		_collect_all(child, out)


func _check_mesh_count(all_nodes: Array[Node]):
	var count := 0
	for n in all_nodes:
		if n is MeshInstance3D:
			count += 1
	_result["mesh_count"] = count
	if count == 0:
		_result["checks"].append("FAIL: MeshInstance3D_count=0 (no props rendered)")
	else:
		_result["checks"].append("PASS: MeshInstance3D_count=%d" % count)


func _check_floor(all_nodes: Array[Node]):
	var floor_body: StaticBody3D = null
	for n in all_nodes:
		if n is StaticBody3D:
			if n.name.to_lower() == "floor":
				floor_body = n
				break

	if floor_body == null:
		for n in all_nodes:
			if n is StaticBody3D and "floor" in n.name.to_lower():
				floor_body = n
				break

	if floor_body == null:
		_result["checks"].append("FAIL: no floor StaticBody3D found")
		return

	for child in floor_body.get_children():
		if child is CollisionShape3D:
			var shape = child.shape
			if shape is BoxShape3D:
				_result["floor_collision"] = true
				_result["checks"].append("PASS: floor collision (BoxShape3D) found")
				return
	_result["checks"].append("FAIL: floor has no CollisionShape3D with BoxShape3D")


func _check_player_collision(all_nodes: Array[Node]):
	for n in all_nodes:
		if n is CharacterBody3D and n.name == "Player":
			for child in n.get_children():
				if child is CollisionShape3D:
					_result["player_collision"] = true
					_result["checks"].append("PASS: player CollisionShape3D found")
					return
			_result["checks"].append("FAIL: Player has no CollisionShape3D")
			return

	_result["checks"].append("FAIL: Player CharacterBody3D not found")


func _check_target_reachable(all_nodes: Array[Node]):
	var target_node: Node3D = null
	for n in all_nodes:
		if n is Node3D and n.has_meta("_forge_tag"):
			var tag = n.get_meta("_forge_tag")
			if tag == "pickup":
				target_node = n
				break

	if target_node == null:
		_result["checks"].append("FAIL: no node with _forge_tag='pickup' found")
		return

	var space_state = target_node.get_world_3d().direct_space_state
	if space_state == null:
		_result["checks"].append("FAIL: no physics space state available")
		return

	var target_pos = target_node.global_position
	var ray_origin = target_pos + Vector3(0, 5.0, 0)
	var ray_end = target_pos + Vector3(0, -1.0, 0)

	var query = PhysicsRayQueryParameters3D.create(ray_origin, ray_end)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	query.collision_mask = 0xFFFFFFFF

	var hit = space_state.intersect_ray(query)
	if hit and not hit.is_empty():
		_result["target_reachable"] = true
		_result["checks"].append("PASS: target prop reachable by raycast")
	else:
		var player_pos = Vector3(0, 1.0, 0)
		for n in all_nodes:
			if n is CharacterBody3D and n.name == "Player":
				player_pos = n.global_position
				break

		var to_target = target_pos - player_pos
		var dist = to_target.length()
		if dist < 0.01:
			_result["checks"].append("FAIL: target too close to player for raycast")
			return

		var dir = to_target.normalized()
		var ray_origin2 = player_pos
		var ray_end2 = target_pos + dir * 0.5
		var query2 = PhysicsRayQueryParameters3D.create(ray_origin2, ray_end2)
		query2.collide_with_areas = true
		query2.collide_with_bodies = true
		query2.collision_mask = 0xFFFFFFFF

		var hit2 = space_state.intersect_ray(query2)
		if hit2 and not hit2.is_empty():
			_result["target_reachable"] = true
			_result["checks"].append("PASS: target prop reachable by forward raycast")
		else:
			_result["checks"].append("FAIL: target prop not reachable by raycast")


# ── Item 1: Lights ───────────────────────────────────────────────

func _check_lights(all_nodes: Array[Node]):
	var has_env := false
	var has_light := false

	for n in all_nodes:
		if n is WorldEnvironment:
			has_env = true
		if n is DirectionalLight3D:
			has_light = true

	_result["world_env"] = has_env
	_result["directional_light"] = has_light

	if has_env:
		_result["checks"].append("PASS: WorldEnvironment node found")
	else:
		_result["checks"].append("FAIL: no WorldEnvironment node")

	if has_light:
		_result["checks"].append("PASS: DirectionalLight3D found")
	else:
		_result["checks"].append("FAIL: no DirectionalLight3D")


# ── Item 2: Room shell ───────────────────────────────────────────

func _check_room_shell(all_nodes: Array[Node]):
	var has_floor_mesh := false
	var has_wall_n := false
	var has_wall_s := false
	var has_wall_e := false
	var has_wall_w := false
	var has_ceiling := false

	for n in all_nodes:
		if n.name == "FloorMesh" and n is MeshInstance3D:
			has_floor_mesh = true
		if n.name == "WallN" and n is StaticBody3D:
			has_wall_n = true
		if n.name == "WallS" and n is StaticBody3D:
			has_wall_s = true
		if n.name == "WallE" and n is StaticBody3D:
			has_wall_e = true
		if n.name == "WallW" and n is StaticBody3D:
			has_wall_w = true
		if n.name == "Ceiling" and n is MeshInstance3D:
			has_ceiling = true

	_result["room_shell_ok"] = (
		has_floor_mesh and has_wall_n and has_wall_s
		and has_wall_e and has_wall_w and has_ceiling
	)

	if _result["room_shell_ok"]:
		_result["checks"].append("PASS: room shell complete (floor mesh + 4 walls + ceiling)")
	else:
		var missing := PackedStringArray()
		if not has_floor_mesh: missing.append("FloorMesh")
		if not has_wall_n: missing.append("WallN")
		if not has_wall_s: missing.append("WallS")
		if not has_wall_e: missing.append("WallE")
		if not has_wall_w: missing.append("WallW")
		if not has_ceiling: missing.append("Ceiling")
		_result["checks"].append("FAIL: room shell missing: " + ", ".join(missing))


# ── Item 4: Player body ─────────────────────────────────────────

func _check_player_body(all_nodes: Array[Node]):
	for n in all_nodes:
		if n.name == "Player" and n is CharacterBody3D:
			for child in n.get_children():
				if child.name == "BodyMesh" and child is MeshInstance3D:
					_result["player_body"] = true
					_result["checks"].append("PASS: player body MeshInstance3D found")
					return
			_result["checks"].append("FAIL: Player has no BodyMesh MeshInstance3D")
			return
	_result["checks"].append("FAIL: Player node not found")


# ── Item 4: Player grounded ─────────────────────────────────────

func _check_player_grounded(all_nodes: Array[Node]):
	var player: CharacterBody3D = null
	for n in all_nodes:
		if n is CharacterBody3D and n.name == "Player":
			player = n
			break

	if player == null:
		_result["checks"].append("FAIL: cannot check grounding — Player not found")
		return

	# Apply downward velocity and step physics
	player.velocity = Vector3(0, -1.0, 0)
	player.move_and_slide()

	if player.is_on_floor():
		_result["player_grounded"] = true
		_result["checks"].append("PASS: player is_on_floor() after physics step")
	else:
		_result["checks"].append("FAIL: player not on floor after move_and_slide() (y=%.2f)" % player.global_position.y)


func _print_and_quit(exit_code: int):
	var json_str = JSON.stringify(_result, "")
	print("PROBE_JSON_OUTPUT:" + json_str)
	quit(exit_code)


# ── C-1: Audio synthesis check ───────────────────────────────────

func _check_audio_synth(_all_nodes: Array[Node]):
	"""Verify that AudioStreamGenerator can be created, filled, and
	played without errors (no sound files required — pure synthesis)."""
	var generator = AudioStreamGenerator.new()
	if generator == null:
		_result["checks"].append("FAIL: AudioStreamGenerator.new() returned null")
		return
	generator.mix_rate = 44100
	generator.buffer_length = 0.05

	var player = AudioStreamPlayer.new()
	player.stream = generator
	add_child(player)
	player.play()

	var playback = player.get_stream_playback()
	if playback == null:
		_result["checks"].append("FAIL: get_stream_playback() returned null")
		player.queue_free()
		return

	# Push a short test waveform (sine at 440 Hz, 0.05s)
	var can_push: bool = playback.can_push_buffer(256)
	if not can_push:
		_result["checks"].append("FAIL: can_push_buffer(256) returned false")
		player.queue_free()
		return

	for _i in range(2205):  # 44100 * 0.05 ≈ 2205 frames
		var v: float = sin(float(_i) / 44100.0 * 440.0 * TAU) * 0.3
		playback.push_frame(Vector2(v, v))

	# Give it a frame to start playing
	await get_tree().process_frame

	if player.playing:
		_result["audio_synth"] = true
		_result["checks"].append("PASS: AudioStreamGenerator plays synthesized audio")
	else:
		_result["checks"].append("FAIL: AudioStreamGenerator not playing after push")

	player.stop()
	player.queue_free()

	# C-1: Also exercise the actual Audio autoload (end-to-end)
	var audio_autoload = get_node_or_null("/root/Audio")
	if audio_autoload and audio_autoload.has_method("play_footstep"):
		audio_autoload.play_footstep()
		_result["checks"].append("PASS: Audio autoload play_footstep() called without error")
	else:
		_result["checks"].append("WARNING: Audio autoload not found (may not be registered)")
