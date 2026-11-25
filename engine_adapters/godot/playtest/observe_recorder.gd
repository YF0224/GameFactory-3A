extends SceneTree

## Plan-driven playtest recorder with runtime observation (engine-adapter
## owned; the game project is never modified).
##
## Launched by GodotPlaytestClient.record() as:
##
##     godot --path <project> --resolution WxH -s <this script> -- \
##          --a3-scenario <scenario.json> --a3-output <evidence dir>
##
## The scenario (written by the client next to the evidence) carries the
## frozen action plan plus capture settings: {"actions": [...], "fps": int,
## "duration": seconds, "input_bindings": {...}}.
##
## What this recorder does, all game-agnostic:
##
##   1. loads the project's main scene (application/run/main_scene, then
##      res://scenes/main.tscn) and runs it under this tree — the game
##      itself stays untouched;
##   2. binds runtime observation through the game's runtime adapter
##      autoload when it follows the adapter contract (signal
##      ``event_emitted`` + ``get_state_snapshot()``). Without an adapter
##      the playtest still records inputs and frames; the runtime traces
##      simply stay absent and downstream metrics keep UNKNOWN;
##   3. reaches the operable state: issues the ``start_match`` command when
##      the game supports it, then waits for the snapshot's
##      ``input_enabled`` flag when it exposes one (fixed boot delay
##      otherwise);
##   4. executes the action plan by injecting physical-key input events.
##      The verb → key mapping is resolved from the scenario's
##      ``input_bindings`` when provided (rubric-authoritative), falling
##      back to the shared default vocabulary: move W/A/S/D, jump Space,
##      attack J, dash U, interact H, restart Enter, pause Esc.
##   5. observes the runtime every physics frame: state_trace.jsonl rows
##      {t_ms, state} from get_state_snapshot() and event_trace.jsonl
##      rows {t_ms, event, payload} from the event_emitted signal;
##   6. captures viewport frames at the requested fps into frames/.
##
## Evidence honesty: every row is written from what actually happened in
## this session — nothing is inferred, defaulted or backfilled. A trace
## with no rows is left unwritten so the loader reports it as *not
## captured* (UNKNOWN), never as a confirmed empty observation.

const DEFAULT_FPS := 20
const DEFAULT_DURATION := 12.0
const READY_TIMEOUT_MS := 6000
const FALLBACK_BOOT_MS := 1500
const MIN_ACTION_MS := 1

var _scenario_path := ""
var _output_dir := ""
var _actions: Array = []
var _fps := DEFAULT_FPS
var _duration := DEFAULT_DURATION
# verb → key name from rubric input_bindings (e.g. {"interact": "Enter"})
var _input_bindings: Dictionary = {}

var _game: Node = null
var _adapter: Node = null
var _session_origin := 0
var _action_rows: Array = []
var _state_rows: Array = []
var _event_rows: Array = []
var _frame_index := 0
var _audio_record: AudioEffectRecord
var _audio_effect_index := -1
var _audio_started_ms := 0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size() - 1):
		if args[i] == "--a3-scenario":
			_scenario_path = args[i + 1]
		elif args[i] == "--a3-output":
			_output_dir = args[i + 1]
	if _scenario_path == "" or _output_dir == "":
		print("A3PLAYTEST_ERROR: --a3-scenario and --a3-output are required")
		quit(1)
		return
	var parsed = _load_json(_scenario_path)
	if typeof(parsed) != TYPE_DICTIONARY:
		print("A3PLAYTEST_ERROR: scenario is not a JSON object: ", _scenario_path)
		quit(1)
		return
	_actions = parsed.get("actions", [])
	if typeof(_actions) != TYPE_ARRAY:
		print("A3PLAYTEST_ERROR: scenario 'actions' must be a list")
		quit(1)
		return
	_fps = maxi(1, int(parsed.get("fps", DEFAULT_FPS)))
	_duration = maxf(0.0, float(parsed.get("duration", DEFAULT_DURATION)))
	var bindings = parsed.get("input_bindings", {})
	if typeof(bindings) == TYPE_DICTIONARY:
		_input_bindings = bindings
	call_deferred("_run")


func _run() -> void:
	_session_origin = Time.get_ticks_msec()
	_start_audio_capture()

	# 1. run the game's main scene under this tree
	var packed := _load_main_scene()
	if packed == null:
		print("A3PLAYTEST_ERROR: no loadable main scene found")
		quit(1)
		return
	_game = packed.instantiate()
	root.add_child(_game)
	await _sleep_ms(300)

	# 2. bind runtime observation before any command or input so the whole
	#    session (match start included) is covered by the traces
	_adapter = _find_runtime_adapter()
	if _adapter != null:
		_adapter.event_emitted.connect(_on_event)

	# 3. reach the operable state (harness setup, not a player action)
	_enter_gameplay()
	await _wait_for_operable_state()

	# 4.-6. execute the plan, observe every physics frame, capture frames
	var frames_dir := _output_dir + "/frames"
	DirAccess.make_dir_recursive_absolute(frames_dir)
	var capture_interval := maxi(1, int(round(60.0 / float(_fps))))
	var schedule: Array[int] = []
	var accumulated := 0
	for action in _actions:
		schedule.append(accumulated)
		accumulated += maxi(MIN_ACTION_MS, int(action.get("duration_ms", 100)))
	var total_ms := int(_duration * 1000.0)
	var loop_start := Time.get_ticks_msec()
	var index := -1
	var held: Array[int] = []
	var physics_tick := 0
	while true:
		var now_ms := Time.get_ticks_msec() - loop_start
		# observe first: every state row for this frame predates the input
		# work below, so a row at t is a valid pre-action baseline
		_sample_state(Time.get_ticks_msec() - _session_origin)
		if index + 1 < _actions.size() and now_ms >= schedule[index + 1]:
			index += 1
			_release_keys(held)
			held = _start_action(index)
		if physics_tick % capture_interval == 0:
			_capture_frame(frames_dir)
		if now_ms >= total_ms:
			break
		await physics_frame
		physics_tick += 1
	_release_keys(held)

	_finish_audio_capture()
	_write_jsonl(_output_dir + "/actions.jsonl", _action_rows)
	_write_jsonl(_output_dir + "/state_trace.jsonl", _state_rows)
	_write_jsonl(_output_dir + "/event_trace.jsonl", _event_rows)
	print("A3PLAYTEST complete actions=%d states=%d events=%d frames=%d adapter=%s" % [
		_action_rows.size(), _state_rows.size(), _event_rows.size(),
		_frame_index, str(_adapter.name if _adapter != null else "<none>"),
	])
	quit(0)


# ── game discovery (never game-specific fields) ─────────────────────────────


func _load_main_scene() -> PackedScene:
	var candidates: Array[String] = []
	var setting = ProjectSettings.get_setting("application/run/main_scene", "")
	if typeof(setting) == TYPE_STRING and str(setting) != "":
		candidates.append(str(setting))
	candidates.append("res://scenes/main.tscn")
	candidates.append("res://main.tscn")
	for path in candidates:
		if ResourceLoader.exists(path):
			var packed := load(path)
			if packed is PackedScene:
				return packed
	return null


func _find_runtime_adapter() -> Node:
	# Autoloads are root children added before the game scene; the runtime
	# adapter contract is the signal `event_emitted` plus a
	# `get_state_snapshot()` method.
	for child in root.get_children():
		if child == _game:
			continue
		if child.has_signal("event_emitted") and child.has_method("get_state_snapshot"):
			return child
	return null


func _enter_gameplay() -> void:
	if _adapter != null:
		if _adapter.has_method("handle_runtime_command"):
			_adapter.handle_runtime_command("start_match", {})
			return
		if _adapter.has_method("start_match"):
			_adapter.start_match()
			return
	if _game != null and _game.has_method("start_match"):
		_game.start_match()


func _wait_for_operable_state() -> void:
	# Games that expose an `input_enabled` snapshot flag are waited for;
	# anything else falls back to a fixed boot delay so the plan still runs
	# (the traces then show honestly what did or did not respond).
	if _adapter == null:
		await _sleep_ms(FALLBACK_BOOT_MS)
		return
	var exposes_flag := false
	var waited := 0
	while waited < READY_TIMEOUT_MS:
		var snapshot: Dictionary = _adapter.get_state_snapshot()
		if snapshot.has("input_enabled"):
			exposes_flag = true
			if snapshot.get("input_enabled") == true:
				return
		elif not snapshot.is_empty():
			break
		await _sleep_ms(100)
		waited += 100
	if not exposes_flag:
		await _sleep_ms(FALLBACK_BOOT_MS)
	# flag never turned true within the timeout: proceed anyway — the
	# recorded evidence will show what actually happened


# ── plan execution (verb → physical key, rubric bindings override defaults) ──

# Default verb → key name for games that do not declare input_bindings.
# These are the shared playtest vocabulary defaults.
const _DEFAULT_BINDINGS := {
	"jump":     "Space",
	"attack":   "J",
	"dash":     "U",
	"interact": "H",
	"restart":  "Enter",
	"pause":    "Escape",
}

# Map a key name string (as stored in rubric input_bindings) to a Godot KEY_*
# constant.  Only the keys the playtest vocabulary can produce are listed;
# unknown names return KEY_NONE so the verb is recorded as unsent.
# Mouse buttons (LMB/RMB/MMB) return KEY_NONE here and are handled separately
# in _keys_for_action via _mouse_button_for_name().
func _key_from_name(name: String) -> int:
	match name.to_upper():
		"ENTER", "RETURN":  return KEY_ENTER
		"SPACE":            return KEY_SPACE
		"ESCAPE", "ESC":    return KEY_ESCAPE
		"LMB", "RMB", "MMB": return KEY_NONE  # mouse buttons, handled separately
		"W":                return KEY_W
		"A":                return KEY_A
		"S":                return KEY_S
		"D":                return KEY_D
		"J":                return KEY_J
		"U":                return KEY_U
		"H":                return KEY_H
		"F":                return KEY_F
		"E":                return KEY_E
		"R":                return KEY_R
		"Q":                return KEY_Q
		_:                  return KEY_NONE


# Map a key name to a mouse button index (MOUSE_BUTTON_*), or -1 if not a mouse button.
func _mouse_button_for_name(name: String) -> int:
	match name.to_upper():
		"LMB": return MOUSE_BUTTON_LEFT
		"RMB": return MOUSE_BUTTON_RIGHT
		"MMB": return MOUSE_BUTTON_MIDDLE
		_:     return -1


func _keys_for_action(action: Dictionary) -> Array[int]:
	var keys: Array[int] = []
	var verb := str(action.get("action", ""))
	match verb:
		"move":
			var x := int(action.get("x", 0))
			var y := int(action.get("y", 0))
			# when no direction is given, default to forward (up / -y in screen space)
			if x == 0 and y == 0:
				y = -1
			if y < 0:
				keys.append(KEY_W)
			elif y > 0:
				keys.append(KEY_S)
			if x < 0:
				keys.append(KEY_A)
			elif x > 0:
				keys.append(KEY_D)
		_:
			# Resolve verb → key name: rubric binding first, default fallback
			var key_name := ""
			if _input_bindings.has(verb):
				key_name = str(_input_bindings[verb])
			elif _DEFAULT_BINDINGS.has(verb):
				key_name = str(_DEFAULT_BINDINGS[verb])
			if key_name != "":
				var key_code := _key_from_name(key_name)
				if key_code != KEY_NONE:
					keys.append(key_code)
				# mouse button verbs return no keys here — _start_action handles them
	return keys


func _start_action(index: int) -> Array[int]:
	var action: Dictionary = _actions[index]
	var name := str(action.get("action", ""))
	var keys := _keys_for_action(action)
	var sent := true
	if name == "wait":
		pass  # the scheduled pause itself is the step; nothing to inject
	elif keys.is_empty():
		# check if this verb maps to a mouse button via input_bindings
		var key_name := ""
		if _input_bindings.has(name):
			key_name = str(_input_bindings[name])
		elif _DEFAULT_BINDINGS.has(name):
			key_name = str(_DEFAULT_BINDINGS[name])
		var mouse_btn := _mouse_button_for_name(key_name)
		if mouse_btn >= 0:
			_click_mouse_button(mouse_btn)
		else:
			sent = false  # unmapped verb or empty move direction: never sent
	else:
		for key in keys:
			_press_key(key)
	var row := {
		"seq": index + 1,
		"t_monotonic_ms": Time.get_ticks_msec() - _session_origin,
		"action": name,
		"duration_ms": maxi(MIN_ACTION_MS, int(action.get("duration_ms", 100))),
		"sent": sent,
		"source": "runtime",
	}
	for key in action:
		if key is String and not row.has(key) and key != "action" and key != "duration_ms":
			row[key] = _jsonify(action[key])
	_action_rows.append(row)
	print("A3PLAYTEST action seq=%d %s sent=%s t=%dms" % [
		index + 1, name, str(sent), row["t_monotonic_ms"],
	])
	return keys


func _press_key(keycode: int) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = keycode
	event.pressed = true
	Input.parse_input_event(event)


func _release_keys(keys: Array[int]) -> void:
	for keycode in keys:
		var event := InputEventKey.new()
		event.physical_keycode = keycode
		event.pressed = false
		Input.parse_input_event(event)


func _click_mouse_button(button_index: int) -> void:
	# Send a press + release pair at the viewport centre so the game receives
	# a full click regardless of where the cursor is positioned.
	var vp_size := get_root().get_viewport().get_visible_rect().size
	var centre := vp_size / 2.0
	var press := InputEventMouseButton.new()
	press.button_index = button_index
	press.pressed = true
	press.position = centre
	press.global_position = centre
	Input.parse_input_event(press)
	var release := InputEventMouseButton.new()
	release.button_index = button_index
	release.pressed = false
	release.position = centre
	release.global_position = centre
	Input.parse_input_event(release)


# ── runtime observation ──────────────────────────────────────────────────────


func _sample_state(t_ms: int) -> void:
	if _adapter == null:
		return
	var snapshot: Dictionary = _adapter.get_state_snapshot()
	if snapshot.is_empty():
		return
	_state_rows.append({"t_ms": t_ms, "state": _jsonify(snapshot)})


func _on_event(event_name: String, payload: Dictionary) -> void:
	_event_rows.append({
		"t_ms": Time.get_ticks_msec() - _session_origin,
		"event": str(event_name),
		"payload": _jsonify(payload),
	})


func _capture_frame(frames_dir: String) -> void:
	var image := root.get_texture().get_image()
	if image == null:
		return
	_frame_index += 1
	image.save_png(frames_dir + "/f%05d.png" % _frame_index)


# ── serialization helpers ───────────────────────────────────────────────────


func _jsonify(value: Variant) -> Variant:
	match typeof(value):
		TYPE_VECTOR2, TYPE_VECTOR2I:
			return {"x": value.x, "y": value.y}
		TYPE_VECTOR3, TYPE_VECTOR3I:
			return {"x": value.x, "y": value.y, "z": value.z}
		TYPE_VECTOR4, TYPE_VECTOR4I:
			return {"x": value.x, "y": value.y, "z": value.z, "w": value.w}
		TYPE_COLOR:
			return {"r": value.r, "g": value.g, "b": value.b, "a": value.a}
		TYPE_FLOAT:
			return value if is_finite(value) else null
		TYPE_ARRAY:
			var items: Array = []
			for item in value:
				items.append(_jsonify(item))
			return items
		TYPE_DICTIONARY:
			var mapped := {}
			for key in value:
				mapped[key] = _jsonify(value[key])
			return mapped
		TYPE_OBJECT:
			return str(value)
		_:
			return value


func _write_jsonl(path: String, rows: Array) -> void:
	# An empty observation is left unwritten: an absent file reads as
	# "not captured" (UNKNOWN), never as a confirmed empty trace.
	if rows.is_empty():
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		print("A3PLAYTEST_ERROR: cannot write ", path)
		return
	for row in rows:
		file.store_line(JSON.stringify(row))
	file.close()


func _load_json(path: String) -> Variant:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var parsed = JSON.parse_string(file.get_as_text())
	file.close()
	return parsed


func _sleep_ms(ms: int) -> void:
	var end := Time.get_ticks_msec() + ms
	while Time.get_ticks_msec() < end:
		await physics_frame


# Capture only this process's master bus, never microphone/system audio.
func _write_audio_metadata(metadata: Dictionary) -> void:
	var file := FileAccess.open(_output_dir + "/audio_capture.json", FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(metadata))
		file.close()


func _start_audio_capture() -> void:
	if AudioServer.get_driver_name().to_lower() == "dummy":
		_write_audio_metadata({"status": "unavailable", "source": "game_output",
			"error": "dummy_audio_driver"})
		return
	_audio_record = AudioEffectRecord.new()
	_audio_record.format = AudioStreamWAV.FORMAT_16_BITS
	_audio_effect_index = AudioServer.get_bus_effect_count(0)
	AudioServer.add_bus_effect(0, _audio_record)
	_audio_started_ms = Time.get_ticks_msec() - _session_origin
	_audio_record.set_recording_active(true)
	_write_audio_metadata({"status": "recording", "source": "game_output",
		"start_t_ms": _audio_started_ms, "clock": "monotonic_session_ms"})


func _finish_audio_capture() -> void:
	if _audio_record == null:
		return
	_audio_record.set_recording_active(false)
	var stream := _audio_record.get_recording()
	var metadata := {"status": "capture_failed", "source": "game_output",
		"start_t_ms": _audio_started_ms, "clock": "monotonic_session_ms",
		"end_t_ms": Time.get_ticks_msec() - _session_origin,
		"synchronization_precision": "audio_buffer; not sample-aligned to frames",
		"driver": AudioServer.get_driver_name()}
	if stream != null and not stream.data.is_empty():
		var error := stream.save_to_wav(_output_dir + "/audio.wav")
		if error == OK:
			metadata["status"] = "captured"
			metadata["duration_s"] = stream.get_length()
		else:
			metadata["error"] = "wav_write_failed"
	else:
		metadata["error"] = "no_audio_samples"
	_write_audio_metadata(metadata)
	AudioServer.remove_bus_effect(0, _audio_effect_index)
