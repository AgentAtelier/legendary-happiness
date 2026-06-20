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

func play_footstep() -> void:
	_play_cue("footstep")


func play_pickup() -> void:
	_play_cue("pickup")


func play_talk() -> void:
	_play_cue("talk")


func play_win() -> void:
	_play_cue("win")


# ── Internal playback engine ──────────────────────────────────────

func _play_cue(cue_name: String) -> void:
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

	call(gen_func, playback, sample_count, MIX_RATE, duration)

	# Clean up after playback
	await get_tree().create_timer(duration + 0.05).timeout
	player.stop()
	player.queue_free()


# ── Sound generators (pure synthesis, no assets) ──────────────────

func _gen_footstep(playback, n: int, rate: int, duration: float) -> void:
	"""
	Low-frequency thump with quick exponential decay.
	Base ~55 Hz sine + subtle noise for ground texture.
	"""
	var frames := maxi(1, n)
	for i in range(frames):
		var t: float = float(i) / rate
		var envelope: float = exp(-t * 40.0)  # quick decay
		var sine: float = sin(t * 55.0 * TAU)
		# Tiny fixed-phase noise for texture (seeded from t to avoid randf)
		var noise: float = sin(t * 997.0) * 0.075
		var sample: float = (sine * 0.85 + noise) * envelope
		playback.push_frame(Vector2(sample, sample))


func _gen_pickup(playback, n: int, rate: int, duration: float) -> void:
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


func _gen_talk(playback, n: int, rate: int, duration: float) -> void:
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


func _gen_win(playback, n: int, rate: int, duration: float) -> void:
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
