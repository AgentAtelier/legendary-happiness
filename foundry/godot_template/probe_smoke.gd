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

extends SceneTree

var _result := {
	"ok": false,
	"mesh_count": 0,
	"floor_collision": false,
	"player_collision": false,
	"target_reachable": false,
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


func _print_and_quit(exit_code: int):
	# Print compact single-line JSON so the Python harness can find it
	# among Godot engine log output.  The marker prefix makes extraction
	# unambiguous.
	var json_str = JSON.stringify(_result, "")
	print("PROBE_JSON_OUTPUT:" + json_str)
	quit(exit_code)
