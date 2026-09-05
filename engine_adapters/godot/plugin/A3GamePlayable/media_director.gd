class_name A3GameMediaDirector
extends Node
## Engine-native audio / video CG / animation CG / VFX trigger surface.
##
## The agent/gameplay layer only supplies a canonical event key. Asset binding
## stays here, while the returned event record is suitable for runtime evidence
## collection. VFX nodes should expose the native ``restart`` method (for
## example CPUParticles2D or GPUParticles2D).

signal media_event(record: Dictionary)
## Emitted when a CG acquires/releases the combat-only pause lock.
signal gameplay_pause_changed(paused: bool)

func _ready() -> void:
	_started_ms = Time.get_ticks_msec()

var _audio_bindings: Dictionary = {}
var _cg_bindings: Dictionary = {}
var _animation_bindings: Dictionary = {}
var _vfx_bindings: Dictionary = {}
var _audio_players: Dictionary = {}
var _cg_players: Dictionary = {}
var _events: Array[Dictionary] = []
var _seq := 0
var _started_ms := 0
var _gameplay_paused := false

var gameplay_paused: bool:
	get:
		return _gameplay_paused

func register_audio(event_key: String, stream: AudioStream, volume_db: float = 0.0, pitch_scale: float = 1.0) -> Dictionary:
	if event_key.strip_edges() == "":
		return {"ok": false, "error": "event_key must not be empty"}
	if stream == null:
		return {"ok": false, "error": "audio stream is null", "event_key": event_key}
	var player := AudioStreamPlayer.new()
	player.name = "Audio_" + event_key
	player.stream = stream
	player.volume_db = volume_db
	player.pitch_scale = pitch_scale
	add_child(player)
	_audio_bindings[event_key] = stream
	_audio_players[event_key] = player
	return {"ok": true, "event_key": event_key, "kind": "audio", "player": player.name}

func register_cg(event_key: String, stream: VideoStream, loop: bool = false) -> Dictionary:
	if event_key.strip_edges() == "":
		return {"ok": false, "error": "event_key must not be empty"}
	if stream == null:
		return {"ok": false, "error": "video stream is null", "event_key": event_key}
	var player := VideoStreamPlayer.new()
	player.name = "CG_" + event_key
	player.stream = stream
	player.loop = loop
	player.autoplay = false
	player.visible = false
	player.finished.connect(func(): _finish_cg(event_key))
	add_child(player)
	_cg_bindings[event_key] = stream
	_cg_players[event_key] = player
	return {"ok": true, "event_key": event_key, "kind": "cg", "player": player.name}

func register_animation(event_key: String, player: AnimationPlayer, animation_name: String) -> Dictionary:
	if event_key.strip_edges() == "" or player == null:
		return {"ok": false, "error": "invalid animation binding", "event_key": event_key}
	if not player.has_animation(animation_name):
		return {"ok": false, "error": "animation does not exist: " + animation_name, "event_key": event_key}
	_animation_bindings[event_key] = {"player": player, "animation_name": animation_name}
	return {"ok": true, "event_key": event_key, "kind": "animation", "player": player.name, "animation": animation_name}

func trigger_animation(event_key: String, trigger_source: String = "gameplay", metadata: Dictionary = {}) -> Dictionary:
	var binding: Dictionary = _animation_bindings.get(event_key, {})
	var player: AnimationPlayer = binding.get("player")
	var animation_name: String = binding.get("animation_name", "")
	var issued := player != null and animation_name != "" and player.has_animation(animation_name)
	if issued:
		player.play(animation_name)
	var record := _record("cg_animation_triggered", event_key, trigger_source, issued, metadata)
	emit_signal("media_event", record)
	return record

func register_vfx(event_key: String, effect_node: Node) -> Dictionary:
	if event_key.strip_edges() == "" or effect_node == null:
		return {"ok": false, "error": "invalid VFX binding", "event_key": event_key}
	if not effect_node.has_method("restart") and not effect_node.has_method("play"):
		return {"ok": false, "error": "VFX node must expose restart() or play()", "event_key": event_key}
	_vfx_bindings[event_key] = effect_node
	return {"ok": true, "event_key": event_key, "kind": "vfx", "node": effect_node.name}

func trigger_vfx(event_key: String, trigger_source: String = "gameplay", metadata: Dictionary = {}) -> Dictionary:
	var effect_node: Node = _vfx_bindings.get(event_key)
	var issued := effect_node != null and (effect_node.has_method("restart") or effect_node.has_method("play"))
	if issued:
		if effect_node.has_method("restart"):
			effect_node.call("restart")
		else:
			effect_node.call("play")
	var record := _record("vfx_triggered", event_key, trigger_source, issued, metadata)
	emit_signal("media_event", record)
	return record

func stop_vfx(event_key: String) -> Dictionary:
	var effect_node: Node = _vfx_bindings.get(event_key)
	if effect_node == null:
		return {"ok": false, "error": "VFX event is not registered", "event_key": event_key}
	if effect_node.has_method("stop"):
		effect_node.call("stop")
	return {"ok": true, "event_key": event_key, "kind": "vfx"}

func trigger_audio(event_key: String, trigger_source: String = "gameplay", metadata: Dictionary = {}) -> Dictionary:
	var player: AudioStreamPlayer = _audio_players.get(event_key)
	var issued := player != null and player.stream != null
	if issued:
		player.play()
	var record := _record("audio_triggered", event_key, trigger_source, issued, metadata)
	emit_signal("media_event", record)
	return record

func trigger_cg(event_key: String, trigger_source: String = "gameplay", metadata: Dictionary = {}) -> Dictionary:
	var player: VideoStreamPlayer = _cg_players.get(event_key)
	var issued := player != null and player.stream != null
	if issued:
		_set_gameplay_paused(true)
		player.visible = true
		player.play()
	var record := _record("cg_triggered", event_key, trigger_source, issued, metadata)
	emit_signal("media_event", record)
	return record

func stop_cg(event_key: String) -> Dictionary:
	var player: VideoStreamPlayer = _cg_players.get(event_key)
	if player == null:
		return {"ok": false, "error": "CG event is not registered", "event_key": event_key}
	player.stop()
	player.visible = false
	_set_gameplay_paused(false)
	return {"ok": true, "event_key": event_key, "kind": "cg"}

func _finish_cg(event_key: String) -> void:
	var player: VideoStreamPlayer = _cg_players.get(event_key)
	if player != null:
		player.visible = false
	_set_gameplay_paused(false)

func _set_gameplay_paused(paused: bool) -> void:
	if _gameplay_paused == paused:
		return
	_gameplay_paused = paused
	emit_signal("gameplay_pause_changed", paused)

func get_event_log() -> Array[Dictionary]:
	return _events.duplicate(true)

func _record(event_type: String, event_key: String, trigger_source: String, issued: bool, metadata: Dictionary) -> Dictionary:
	_seq += 1
	var record := {
		"schema_version": "gamefactory3a.media_runtime_event.v1",
		"seq": _seq,
		"t_monotonic_ms": Time.get_ticks_msec() - _started_ms,
		"event_type": event_type,
		"event_key": event_key,
		"trigger_source": trigger_source,
		"playback_call_issued": issued,
		"metadata": metadata.duplicate(true)
	}
	_events.append(record)
	return record
