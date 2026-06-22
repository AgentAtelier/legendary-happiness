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
	# Create an offscreen SubViewport
	var vp := SubViewport.new()
	vp.size = Vector2i(CAPTURE_SIZE, CAPTURE_SIZE)
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
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
	if mode == "scene":
		var scene_path: String = config.get("scene_path", "res://scenes/main.tscn")
		var scene_res := load(scene_path)
		if scene_res:
			var scene_inst: Node = scene_res.instantiate()
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
			else:
				printerr("failed to load prop GLB ", glb_path)

	# Wait for the SubViewport to actually draw before reading it back.
	# process_frame alone fires at the START of the idle frame — before the
	# GPU has drawn the viewport — so get_image() would grab a cleared/empty
	# texture. frame_post_draw fires after the draw completes; await it twice
	# so the UPDATE_ALWAYS viewport has a fully rendered frame.
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw

	# Capture the SubViewport texture
	var tex: Texture2D = vp.get_texture()
	if tex == null:
		return null
	return tex.get_image()
