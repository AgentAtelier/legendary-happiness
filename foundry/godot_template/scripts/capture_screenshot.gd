extends Node
## V Task 1: Offscreen screenshot capture via SubViewport.
##
## Reads _forge_capture JSON from project metadata to determine
## what to capture (scene or prop) and writes PNGs to the output
## directory.

const CAPTURE_SIZE := 512


func _ready() -> void:
	# Read capture config from project settings
	var config_str: String = ProjectSettings.get_setting("application/_forge_capture", "")
	if config_str.is_empty():
		printerr("_forge_capture not set — nothing to capture")
		get_tree().quit(1)
		return

	var config: Dictionary = JSON.parse_string(config_str)
	if config == null:
		printerr("_forge_capture is not valid JSON")
		get_tree().quit(1)
		return

	var mode: String = config.get("mode", "scene")
	var out_dir: String = config.get("out_dir", "")
	var angles: Array = config.get("angles", [])
	if angles.is_empty():
		angles = [0.0]  # default: one shot forward

	var png_paths: Array[String] = []

	for i in angles.size():
		var angle: float = float(angles[i])
		var img: Image = await _capture_at_angle(angle, config)
		if img == null or img.is_empty():
			printerr("capture failed at angle ", angle)
			continue
		var fname: String = out_dir.path_join(
			"capture_%s_%d.png" % [mode, i]
		)
		var err := img.save_png(fname)
		if err == OK:
			png_paths.append(fname)
			print("SAVED ", fname)
		else:
			printerr("failed to save ", fname, " error=", err)

	# Write results manifest so the Python caller knows what was produced
	var manifest_path := out_dir.path_join("capture_manifest.json")
	var f := FileAccess.open(manifest_path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"paths": png_paths}, "\t"))
		f.close()

	get_tree().quit(0 if png_paths.size() > 0 else 1)


func _capture_at_angle(yaw: float, config: Dictionary) -> Image:
	# Create an offscreen SubViewport.  Roadmap-0.11 capture-harness fix:
	# in headless mode with software Mesa (llvmpipe + EGL surfaceless) the
	# main render loop does NOT fire `frame_post_draw` (no buffer swap), so
	# `UPDATE_ALWAYS` viewports are never actually rendered and
	# `vp.get_texture().get_image()` returns a null texture from the
	# DUMMY storage path.  `UPDATE_ONCE` queues a single explicit render
	# for the next frame, which works deterministically in headless.
	# Reset the mode BEFORE every await so the loop iteration sees a fresh
	# queued render even if the previous one already completed.
	var vp := SubViewport.new()
	vp.size = Vector2i(CAPTURE_SIZE, CAPTURE_SIZE)
	vp.render_target_update_mode = SubViewport.UPDATE_ONCE
	# Solid neutral background (not transparent) so a failed/empty render is
	# visibly distinct and the VLM sees the prop against a clean backdrop.
	vp.transparent_bg = false
	add_child(vp)

	# Add a Camera3D at the requested angle. It MUST be inside the tree
	# before look_at() — look_at uses the global transform, which is only
	# valid once the node is parented (otherwise: "Node not inside tree").
	var cam := Camera3D.new()
	cam.current = true
	vp.add_child(cam)
	# Position: orbit at radius, looking at origin
	var radius: float = config.get("radius", 4.0)
	var height: float = config.get("height", 1.5)
	cam.position = Vector3(
		sin(yaw) * radius,
		height,
		cos(yaw) * radius,
	)
	cam.look_at(Vector3(0, 0.5, 0))

	# Add a directional light so props aren't just silhouettes
	var light := DirectionalLight3D.new()
	light.rotation = Vector3(-0.5, 0.5, 0.0)
	vp.add_child(light)

	# Instance the scene or prop GLB as a child of the viewport
	var mode: String = config.get("mode", "scene")
	var scene_inst: Node = null
	if mode == "scene":
		var scene_path: String = config.get("scene_path", "res://scenes/main.tscn")
		var scene_res := load(scene_path)
		if scene_res:
			scene_inst = scene_res.instantiate()
			vp.add_child(scene_inst)
		else:
			printerr("failed to load scene ", scene_path)
	elif mode == "prop":
		var glb_path: String = config.get("glb_path", "")
		if not glb_path.is_empty():
			var glb_res := load(glb_path)
			if glb_res:
				var prop_inst: Node = glb_res.instantiate()
				vp.add_child(prop_inst)
				scene_inst = prop_inst
			else:
				printerr("failed to load prop GLB ", glb_path)

	# ── Problem B: room-aware camera placement ─────────────────
	# Compute the scene AABB so the camera stays INSIDE the room
	# (not outside looking at wall backfaces).  Falls back to the
	# legacy config radius/height when no scene was instantiated.
	if scene_inst:
		var aabb := _compute_scene_aabb(scene_inst)
		var centre := aabb.get_center()
		var half_extent := aabb.size * 0.5
		var room_radius: float = minf(half_extent.x, half_extent.z) * 0.6
		var eye_height := centre.y + 0.2  # slight offset above centre
		# clamp: don't go below 1.5 m eye height
		if eye_height < 1.5:
			eye_height = 1.5
		# place camera on the XZ plane at the computed radius
		cam.position = Vector3(
			centre.x + sin(yaw) * room_radius,
			eye_height,
			centre.z + cos(yaw) * room_radius,
		)
		cam.look_at(centre)

	# Re-arm UPDATE_ONCE — but only on the software-Mesa path.  Godot
	# resets the mode to UPDATE_DISABLED after each render, and software
	# Mesa (llvmpipe + EGL surfaceless) often needs two or three
	# process_frame ticks to compile shaders, build SDFGI, and allocate
	# non-dummy intermediate textures on its first encounter with a
	# complex scene.  On a real-GPU build (FORGE_HARDWARE_GPU=1 in the
	# capture config) one arm is enough — multiple arms would cost 3×
	# GPU time per angle for no quality difference.
	var hardware_gpu: bool = bool(config.get("hardware_gpu", false))
	if hardware_gpu:
		vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		await get_tree().process_frame
	else:
		vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		await get_tree().process_frame
		vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		await get_tree().process_frame
		vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		await get_tree().process_frame

	# Capture the SubViewport texture
	var tex: Texture2D = vp.get_texture()
	if tex == null:
		return null
	return tex.get_image()


# ── Scene AABB computation ──────────────────────────────────────

func _compute_scene_aabb(root: Node) -> AABB:
	var corners: Array = []
	_collect_mesh_corners(root, corners)
	if corners.is_empty():
		# Fallback: no visible meshes — use a default room-sized box
		return AABB(Vector3(-5, 0, -5), Vector3(10, 3, 10))
	var result := AABB(corners[0], Vector3.ZERO)
	for i in range(1, corners.size()):
		result = result.expand(corners[i])
	return result


func _collect_mesh_corners(node: Node, corners: Array) -> void:
	if node is MeshInstance3D:
		var mi: MeshInstance3D = node as MeshInstance3D
		if mi.mesh:
			var aabb: AABB = mi.mesh.get_aabb()
			var t: Transform3D = mi.global_transform
			# 8 corners of the local AABB, transformed to world space
			var p := aabb.position
			var s := aabb.size
			var local_corners := [
				p,
				p + Vector3(s.x, 0, 0),
				p + Vector3(0, s.y, 0),
				p + Vector3(0, 0, s.z),
				p + Vector3(s.x, s.y, 0),
				p + Vector3(s.x, 0, s.z),
				p + Vector3(0, s.y, s.z),
				p + s,
			]
			for c in local_corners:
				corners.append(t * c)
	for child in node.get_children():
		_collect_mesh_corners(child, corners)
