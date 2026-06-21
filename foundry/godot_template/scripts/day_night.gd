# day_night.gd — B2 runtime day/night cycle.
#
# Placed on the DayNight node (child of Root) by the scene compiler.
# In _ready() it finds the DirectionalLight3D and WorldEnvironment siblings,
# duplicates the Environment resource so runtime changes don't mutate
# the shared sub_resource, then drives time-of-day progression in
# _process().
#
# Time flows 0→24 (hours), configurable speed (real seconds per game hour).
# The cycle adjusts:
#   - Sun angle (DirectionalLight3D rotation — pitch from -10° at midnight
#     to +70° at noon, azimuth sweeps E→W)
#   - Light colour (warm at dawn/dusk, neutral at noon, cool at midnight)
#   - Light energy (dim at night, bright at day)
#   - Ambient light colour (dark blue at night, warm at day)
#   - Background/sky colour (same cycle as ambient)
#   - Fog colour + density (thicker/cooler at night)
extends Node


# ── Config ──────────────────────────────────────────────────────

# Real seconds per game hour (default: 60 = 24 min full cycle).
var seconds_per_hour: float = 60.0

# Paused state (set to true to freeze time)
var paused: bool = false

# Current time (0.0–24.0 hours; 0 = midnight, 6 = dawn, 12 = noon,
# 18 = dusk, 24 wraps to 0).
var time_of_day: float = 8.0  # start at morning


# ── Scene references ────────────────────────────────────────────

var _sun: DirectionalLight3D = null
var _world_env: WorldEnvironment = null
var _env: Environment = null

# ── Baked defaults (from scene compile-time) ────────────────────
# These are the original values set at compile time — used as the
# neutral baseline that the cycle modulates around.

var _base_ambient: Color = Color(0.15, 0.15, 0.2, 1.0)
var _base_background: Color = Color(0.05, 0.05, 0.1, 1.0)
var _base_fog_color: Color = Color(0.2, 0.18, 0.22, 1.0)
var _base_fog_density: float = 0.015
var _base_exposure: float = 1.0
var _base_sun_color: Color = Color(1.0, 0.95, 0.85, 1.0)
var _base_sun_energy: float = 2.5


func _ready() -> void:
	# Find scene siblings
	_sun = get_node_or_null("../DirectionalLight3D")
	_world_env = get_node_or_null("../WorldEnvironment")

	if _world_env and _world_env.environment:
		# Duplicate so runtime changes don't mutate the shared resource
		_env = _world_env.environment.duplicate()
		_world_env.environment = _env
		# Snapshot the compile-time defaults
		_base_ambient = _env.ambient_light_color
		_base_background = _env.background_color
		_base_fog_color = _env.fog_light_color
		_base_fog_density = _env.fog_density
		_base_exposure = _env.adjustment_brightness

	if _sun:
		_base_sun_color = _sun.light_color
		_base_sun_energy = _sun.light_energy

	# B2: Start ambient soundscape if theme is available
	var theme_meta = get_meta("_forge_theme", "")
	if theme_meta != "" and has_node("/root/Audio"):
		get_node("/root/Audio").start_ambient(str(theme_meta))

	# Apply initial state
	_apply_cycle()


func _process(delta: float) -> void:
	if paused:
		return

	# Advance time
	time_of_day += delta / seconds_per_hour
	if time_of_day >= 24.0:
		time_of_day -= 24.0

	_apply_cycle()


# ── Cycle applicator ────────────────────────────────────────────

func _apply_cycle() -> void:
	# Normalise: 0=midnight, 0.25=dawn(6), 0.5=noon(12), 0.75=dusk(18)
	var t: float = time_of_day / 24.0

	# Sun pitch: -10° at midnight, +70° at noon
	var sun_pitch: float = lerpf(deg_to_rad(-10.0), deg_to_rad(70.0),
		_smoothstep_pulse(t, 0.5))
	# Sun azimuth: sweeps from E (-90°) at dawn through S (0°) at noon
	# to W (+90°) at dusk, then back.
	# Use a sine wave that peaks at noon.
	var sun_yaw: float = lerpf(deg_to_rad(90.0), deg_to_rad(-90.0),
		_smoothstep_pulse(t, 0.5))

	# ── Sun position ───────────────────────────────────────────
	if _sun:
		# Reconstruct the light direction from pitch/yaw.
		# Godot DirectionalLight3D points -Z by default; we rotate
		# the node around X (pitch) and Y (yaw).
		var basis_x := Basis(Vector3(1, 0, 0), sun_pitch)
		var basis_y := Basis(Vector3(0, 1, 0), sun_yaw)
		_sun.transform.basis = basis_y * basis_x

		# Sun colour: warm at dawn/dusk, neutral at noon, dim blue at night
		var warmth: float = _day_warmth(t)
		_sun.light_color = Color(
			lerpf(0.15, _base_sun_color.r, warmth),
			lerpf(0.15, _base_sun_color.g, warmth),
			lerpf(0.2, _base_sun_color.b, warmth),
			1.0
		)
		# Energy: near zero at midnight, full at noon
		_sun.light_energy = _base_sun_energy * _day_brightness(t)

	# ── Environment modulation ──────────────────────────────────
	if _env:
		var bright: float = _day_brightness(t)
		var warmth_env: float = _day_warmth(t)

		# Ambient: dim blue at night → warm at day
		_env.ambient_light_color = Color(
			lerpf(0.02, _base_ambient.r, bright) * (0.6 + 0.4 * warmth_env),
			lerpf(0.02, _base_ambient.g, bright) * (0.7 + 0.3 * warmth_env),
			lerpf(0.04, _base_ambient.b, bright) * (1.4 - 0.4 * warmth_env),
			1.0
		).clamp(Color(0, 0, 0, 1), Color(1, 1, 1, 1))

		# Background/sky: same cycle
		_env.background_color = Color(
			lerpf(0.01, _base_background.r, bright) * (0.5 + 0.5 * warmth_env),
			lerpf(0.01, _base_background.g, bright) * (0.6 + 0.4 * warmth_env),
			lerpf(0.02, _base_background.b, bright) * (1.5 - 0.5 * warmth_env),
			1.0
		).clamp(Color(0, 0, 0, 1), Color(1, 1, 1, 1))

		# Fog: thicker at night, thinner during day
		_env.fog_density = lerpf(_base_fog_density * 2.5, _base_fog_density * 0.5, bright)
		_env.fog_light_color = Color(
			lerpf(0.04, _base_fog_color.r, bright) * (0.6 + 0.4 * warmth_env),
			lerpf(0.04, _base_fog_color.g, bright) * (0.7 + 0.3 * warmth_env),
			lerpf(0.08, _base_fog_color.b, bright) * (1.3 - 0.3 * warmth_env),
			1.0
		).clamp(Color(0, 0, 0, 1), Color(1, 1, 1, 1))

		# Exposure: dimmer at night
		_env.adjustment_brightness = lerpf(
			_base_exposure * 0.5, _base_exposure * 1.1, bright
		)


# ── Helper curves ───────────────────────────────────────────────

func _day_brightness(t: float) -> float:
	"""Return 0 (midnight) → 1 (noon) brightness factor.

	Uses a smoothstep pulse centred on noon (t=0.5)."""
	return _smoothstep_pulse(t, 0.5)


func _day_warmth(t: float) -> float:
	"""Return warmth factor: peaks at dawn (0.25) and dusk (0.75),
	dips at noon (0.5) and midnight (0.0)."""
	# Use abs(sin(2*PI*t)) so peaks at 0.25 and 0.75
	var raw: float = abs(sin(t * TAU))
	# Smooth the transition
	raw = raw * raw * (3.0 - 2.0 * raw)  # smoothstep
	return raw


func _smoothstep_pulse(t: float, centre: float) -> float:
	"""Smooth bell centred at *centre*: 0 at edges, 1 at centre."""
	var dist: float = abs(t - centre) * 2.0  # 0 at centre, 1 at edges
	if dist >= 1.0:
		return 0.0
	# smoothstep: 3x² - 2x³
	return 1.0 - (dist * dist * (3.0 - 2.0 * dist))


# ── Public API ──────────────────────────────────────────────────

func set_time(hours: float) -> void:
	"""Jump to a specific time (0–24)."""
	time_of_day = clampf(hours, 0.0, 23.999)
	_apply_cycle()


func get_phase() -> String:
	"""Return the named phase: 'night', 'dawn', 'day', 'dusk'."""
	var h := time_of_day
	if h < 5.0:
		return "night"
	elif h < 7.0:
		return "dawn"
	elif h < 17.0:
		return "day"
	elif h < 19.0:
		return "dusk"
	return "night"
