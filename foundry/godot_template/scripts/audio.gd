# Audio.gd — C-1 in-engine procedural audio autoload.
#
# Registered as an autoload in project.godot so every script can call
# Audio.play_footstep() / Audio.play_pickup() / Audio.play_talk() / Audio.play_win().
#
# Uses Godot 4 AudioStreamGenerator for real-time procedural DSP.
# No sound files — everything is synthesized from sine waves, noise bursts,
# and frequency sweeps with per-sample envelope shaping.
#
# Each cue gets its own short-lived AudioStreamPlayer that self-frees
# after playback.  Multiple cues can overlap (polyphony).
extends Node

# ── Quality D: Ambient bed state ──────────────────────────────────

# Persistent ambient player (single, crossfaded on theme change)
var _ambient_player: AudioStreamPlayer = null
var _ambient_gen: AudioStreamGenerator = null
var _ambient_playback: AudioStreamGeneratorPlayback = null
var _ambient_phase: float = 0.0  # continuous phase for seamless loop
var _ambient_target_theme: String = ""
var _ambient_fade: float = 0.0  # 0..1 crossfade progress
var _ambient_fade_dir: int = 0  # 1=fade in, -1=fade out, 0=steady


# ── Cue definitions ──────────────────────────────────────────────

const MIX_RATE := 44100

# Cue: (duration_seconds, generator_func, volume)
const CUES := {
	"footstep": [0.08, "_gen_footstep", 0.35],
	"pickup":   [0.12, "_gen_pickup",   0.40],
	"talk":     [0.18, "_gen_talk",     0.25],
	"win":      [0.70, "_gen_win",      0.45],
}


# ── Public API ────────────────────────────────────────────────────

func play_footstep(surface: String = "stone") -> void:
	_play_cue("footstep", {"surface": surface})


func play_pickup() -> void:
	_play_cue("pickup")


func play_talk() -> void:
	_play_cue("talk")


func play_win() -> void:
	_play_cue("win")


# ── Internal playback engine ──────────────────────────────────────

func _play_cue(cue_name: String, extra: Dictionary = {}) -> void:
	var info = CUES.get(cue_name)
	if info == null:
		return
	var duration: float = info[0]
	var gen_func: String = info[1]
	var volume: float = info[2]

	# Create a disposable AudioStreamPlayer
	var player := AudioStreamPlayer.new()
	player.bus = "Master"
	player.volume_db = linear_to_db(volume)
	add_child(player)

	# Create the generator stream + playback
	var generator := AudioStreamGenerator.new()
	generator.mix_rate = MIX_RATE
	generator.buffer_length = max(0.02, duration * 1.1)  # slight headroom

	player.stream = generator
	player.play()

	# Fill the buffer with synthesized samples
	var playback: AudioStreamGeneratorPlayback = player.get_stream_playback()
	var sample_count := int(MIX_RATE * duration)

	# B2: Pass extra params (e.g. surface for footstep)
	callv(gen_func, [playback, sample_count, MIX_RATE, duration, extra])

	# Clean up after playback
	await get_tree().create_timer(duration + 0.05).timeout
	player.stop()
	player.queue_free()


# ── Sound generators (pure synthesis, no assets) ──────────────────

func _gen_footstep(playback, n: int, rate: int, duration: float, extra: Dictionary = {}) -> void:
	"""
	B2: Surface-aware footstep.
	stone: low thump ~55 Hz
	wood:  mid thump ~80 Hz with warm resonance
	rug:   soft muffled ~40 Hz with faster decay
	"""
	var surface: String = extra.get("surface", "stone")
	var base_freq: float = 55.0
	var decay_rate: float = 40.0
	var noise_amt: float = 0.075
	var sine_weight: float = 0.85

	match surface:
		"wood":
			base_freq = 80.0
			decay_rate = 35.0
			noise_amt = 0.05
			sine_weight = 0.75
		"rug":
			base_freq = 40.0
			decay_rate = 65.0
			noise_amt = 0.1
			sine_weight = 0.5
		_:  # stone / default
			base_freq = 55.0
			decay_rate = 40.0
			noise_amt = 0.075
			sine_weight = 0.85

	var frames := maxi(1, n)
	for i in range(frames):
		var t: float = float(i) / rate
		var envelope: float = exp(-t * decay_rate)
		var sine: float = sin(t * base_freq * TAU)
		var noise: float = sin(t * 997.0) * noise_amt
		var sample: float = (sine * sine_weight + noise) * envelope
		playback.push_frame(Vector2(sample, sample))


func _gen_pickup(playback, n: int, rate: int, duration: float, _extra: Dictionary = {}) -> void:
	"""
	Rising tone sweep ~200→600 Hz with soft attack/decay.
	"""
	var frames := maxi(1, n)
	for i in range(frames):
		var t: float = float(i) / rate
		var progress: float = t / duration
		var freq: float = lerpf(200.0, 600.0, progress)
		var phase: float = fmod(t * freq, 1.0)  # manual phase avoids integration drift
		var envelope: float = sin(progress * PI)  # smooth attack + decay
		var sample: float = sin(phase * TAU) * envelope
		playback.push_frame(Vector2(sample, sample))


func _gen_talk(playback, n: int, rate: int, duration: float, _extra: Dictionary = {}) -> void:
	"""
	Two-tone blip: ~330 Hz for first half, ~440 Hz for second half.
	Soft triangle-ish waveform.  Gentle attack/decay.
	"""
	var frames := maxi(1, n)
	for i in range(frames):
		var t: float = float(i) / rate
		var progress: float = t / duration
		var freq: float = 330.0 if progress < 0.5 else 440.0
		var phase: float = fmod(t * freq, 1.0)
		# Sawtooth wave (downward ramp) via phase fold
		var tri: float = 1.0 - 2.0 * phase
		var envelope: float = sin(progress * PI) * 0.5
		var sample: float = tri * envelope
		playback.push_frame(Vector2(sample, sample))


func _gen_win(playback, n: int, rate: int, duration: float, _extra: Dictionary = {}) -> void:
	"""
	Ascending four-note arpeggio: C4→E4→G4→C5 (~262→330→392→523 Hz).
	Each note ~0.17s with overlap, final note sustains with decay.
	"""
	var notes := [262.0, 330.0, 392.0, 523.0]
	var note_dur := duration / float(len(notes))
	var frames := maxi(1, n)
	for i in range(frames):
		var t: float = float(i) / rate
		# Determine which note is active
		var note_idx := mini(int(t / note_dur), len(notes) - 1)
		var note_progress: float = fmod(t, note_dur) / note_dur
		var freq: float = notes[note_idx]
		var phase: float = fmod(t * freq, 1.0)
		# Sine + soft second harmonic for richness
		var sample: float = sin(phase * TAU) * 0.7 + sin(phase * TAU * 2.0) * 0.3
		# Envelope: attack on each note, overall decay on last note
		var note_env: float = min(note_progress * 4.0, 1.0)  # quick attack
		if note_idx == len(notes) - 1:
			note_env *= exp(-max(0.0, t - note_idx * note_dur) * 2.0)  # sustain decay
		sample *= note_env * 0.45
		playback.push_frame(Vector2(sample, sample))


# ── Quality D: Simple ambient bed ─────────────────────────────────

func start_ambient(theme: String) -> void:
	"""Start or crossfade the ambient bed for *theme*.
	Creates a persistent AudioStreamPlayer and begins filling its
	buffer in _process().  If already playing, triggers a crossfade
	to the new theme."""
	if _ambient_player and is_instance_valid(_ambient_player):
		if _ambient_target_theme != theme:
			_ambient_target_theme = theme
			_ambient_fade_dir = -1
		return

	_ambient_target_theme = theme
	_ambient_fade = 1.0
	_ambient_fade_dir = 0

	_ambient_player = AudioStreamPlayer.new()
	_ambient_player.bus = "Master"
	_ambient_player.volume_db = linear_to_db(0.08)  # very quiet
	add_child(_ambient_player)

	_ambient_gen = AudioStreamGenerator.new()
	_ambient_gen.mix_rate = MIX_RATE
	_ambient_gen.buffer_length = 0.1
	_ambient_player.stream = _ambient_gen
	_ambient_player.play()
	_ambient_playback = _ambient_player.get_stream_playback()


func _process(_delta: float) -> void:
	if not _ambient_playback:
		return

	if _ambient_fade_dir == -1:
		_ambient_fade = maxf(0.0, _ambient_fade - 0.5 * _delta)
		if _ambient_fade <= 0.0:
			_ambient_fade = 0.0
			_ambient_fade_dir = 1
	elif _ambient_fade_dir == 1:
		_ambient_fade = minf(1.0, _ambient_fade + 0.5 * _delta)
		if _ambient_fade >= 1.0:
			_ambient_fade = 1.0
			_ambient_fade_dir = 0

	var frames_to_fill: int = _ambient_gen.mix_rate / 60
	var to_fill: int = mini(frames_to_fill, _ambient_playback.get_frames_available())

	if to_fill > 0:
		_generate_ambient_frames(to_fill, _ambient_target_theme, _ambient_fade)


func _generate_ambient_frames(count: int, theme: String, volume: float) -> void:
	"""Quality D: Simple, quiet room tone — one soft low sine with
	gentle LFO.  Theme-flavoured base frequency, unobtrusive.
	
	- hermit:    55 Hz (warm low)
	- blacksmith: 65 Hz (low rumble)
	- wizard:    70 Hz (airy low)
	- kitchen:   50 Hz (soft bass)
	- noble:     48 Hz (rich low)
	- dungeon:   40 Hz (deep)
	- attic:     60 Hz (dusty mid-low)
	- ship:      45 Hz (low swell)
	- crypt:     35 Hz (deep thrum)
	- armory:    62 Hz (low metal)
	- workshop:  58 Hz (steady hum)
	- tavern:    52 Hz (warm)
	- default:   55 Hz
	"""
	var base_freq: float = 55.0
	match theme:
		"hermit":     base_freq = 55.0
		"blacksmith": base_freq = 65.0
		"wizard":     base_freq = 70.0
		"kitchen":    base_freq = 50.0
		"noble":      base_freq = 48.0
		"dungeon":    base_freq = 40.0
		"attic":      base_freq = 60.0
		"ship":       base_freq = 45.0
		"crypt":      base_freq = 35.0
		"armory":     base_freq = 62.0
		"workshop":   base_freq = 58.0
		"tavern":     base_freq = 52.0
		_:            base_freq = 55.0

	for _i in range(count):
		_ambient_phase += 1.0 / MIX_RATE
		if _ambient_phase > 3600.0:
			_ambient_phase -= 3600.0

		var t: float = _ambient_phase

		# Simple soft sine with slow amplitude modulation
		var lfo: float = sin(t * 0.12 * TAU) * 0.15 + 0.85  # subtle 8.3s swell
		var sine: float = sin(t * base_freq * TAU) * 0.35 * lfo
		var sample: float = sine * volume * 0.3
		sample = clampf(sample, -1.0, 1.0)
		_ambient_playback.push_frame(Vector2(sample, sample))
