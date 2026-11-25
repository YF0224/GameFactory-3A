extends SceneTree
## External read-only observer. Only allowlisted real player inputs mutate game state.
var cfg: Dictionary
var out := ""
var origin := 0
var next_frame := 0
var frame_count := 0
var state_count := 0
var action_count := 0
var active_probe := "boot"
var active_step := "boot"
var states: FileAccess
var actions: FileAccess
var frames: FileAccess
var probes: Array = []
var held: Array = []
var stopped := false
var condition_errors := {}
var writer: Thread
var pending_frame := {}
var skipped_slots := 0
var capture_errors: Array = []
var finalized := false
var screenshot_total_ms := 0
var capture_intervals: Array = []
var last_capture_ms := -1

func _initialize():
	call_deferred("_run")

func _run():
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("PILOT_HARNESS_ERROR expected config and output")
		quit(2)
		return
	cfg = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	out = args[1]
	DirAccess.make_dir_recursive_absolute(out + "/frames")
	states = FileAccess.open(out + "/state_trace.jsonl", FileAccess.WRITE)
	actions = FileAccess.open(out + "/actions.jsonl", FileAccess.WRITE)
	frames = FileAccess.open(out + "/frame_index.jsonl", FileAccess.WRITE)
	origin = Time.get_ticks_msec()
	RenderingServer.frame_post_draw.connect(_capture_frame)
	var main_path = ProjectSettings.get_setting("application/run/main_scene", "")
	var scene = load(main_path)
	if not scene is PackedScene:
		printerr("PILOT_PRODUCT_ERROR cannot load main scene")
		quit(3)
		return
	var game = scene.instantiate()
	root.add_child(game)
	# Absolute edge timeline; conditions never delay unrelated simultaneous input.
	var pending: Array = []
	for edge in cfg["actions"]:
		while _time() < int(edge["at_ms"]):
			await _tick()
			_check_pending(pending, false)
		active_step = edge["source_action_id"]
		var allowed := true
		for c in edge["preconditions"]:
			if not _condition(_snapshot(), c): allowed = false
		var kind: String = edge["kind"]
		# Releases must follow an actual down, even if a later precondition changed.
		var token: String = edge["key"] if kind.begins_with("key_") else "mouse:" + edge["button"]
		if kind in ["key_up", "mouse_up"]: allowed = held.has(token)
		var sent := false
		var error := ""
		if allowed:
			if kind in ["wait", "wait_until"]:
				pending.append({"edge": edge, "deadline": int(edge["at_ms"]) + int(edge["duration_ms"])})
			else:
				sent = _send_edge(edge)
				if not sent: error = "input mapping rejected"
		_log_edge(edge, sent, error, "" if allowed else "PRECONDITION_NOT_MET")
		_check_pending(pending, false)
	while _time() < int(cfg["max_duration_ms"]):
		await _tick()
		_check_pending(pending, false)
	_check_pending(pending, true)
	RenderingServer.frame_post_draw.disconnect(_capture_frame)
	_finish(true)
	quit(0 if frame_count >= 2 and capture_errors.is_empty() else 4)

func _log_edge(edge: Dictionary, sent: bool, error: String = "", skipped: String = ""):
	action_count += 1
	var row = edge.duplicate(true)
	row["seq"] = action_count
	row["requested_at_ms"] = edge["at_ms"]
	row["t_ms"] = _time()
	row["executed_at_ms"] = _time()
	row["input_transport"] = "godot_Input.parse_input_event"
	row["sent"] = sent
	row["skip_reason"] = skipped
	row["focus_required"] = false
	if error != "": row["error"] = error
	actions.store_line(JSON.stringify(row))
	actions.flush()

func _check_pending(pending: Array, force: bool):
	for i in range(pending.size()-1, -1, -1):
		var item: Dictionary = pending[i]
		var edge: Dictionary = item["edge"]
		var met: bool = not edge["condition"].is_empty()
		for c in edge["condition"]:
			if not _condition(_snapshot(), c): met = false
		if met or force or _time() >= int(item["deadline"]):
			var row = edge.duplicate(true)
			row["kind"] = "condition_result"
			row["condition_met"] = met
			_log_edge(row, false)
			pending.remove_at(i)

func _send_edge(edge: Dictionary) -> bool:
	var kind: String = edge["kind"]
	if kind.begins_with("key_"):
		var key: String = edge["key"]
		var code = OS.find_keycode_from_string(key)
		if code == KEY_NONE: return false
		var event := InputEventKey.new()
		event.keycode = code
		event.physical_keycode = code
		event.pressed = kind == "key_down"
		Input.parse_input_event(event)
		if event.pressed: held.append(key)
		else: held.erase(key)
		return true
	var pos = Vector2(float(edge["x"]), float(edge["y"])) * root.get_visible_rect().size
	if kind == "mouse_move":
		var event := InputEventMouseMotion.new()
		event.position = pos
		event.global_position = pos
		event.relative = pos - root.get_mouse_position()
		Input.parse_input_event(event)
		return true
	if kind in ["mouse_down", "mouse_up", "wheel"]:
		var event := InputEventMouseButton.new()
		event.position = pos
		event.global_position = pos
		if kind == "wheel":
			event.button_index = MOUSE_BUTTON_WHEEL_DOWN if float(edge["delta"]) > 0 else MOUSE_BUTTON_WHEEL_UP
			event.factor = absf(float(edge["delta"]))
		else:
			event.button_index = {"left": MOUSE_BUTTON_LEFT, "right": MOUSE_BUTTON_RIGHT, "middle": MOUSE_BUTTON_MIDDLE}[edge["button"]]
		event.pressed = kind != "mouse_up"
		Input.parse_input_event(event)
		if kind == "wheel":
			event.pressed = false
			Input.parse_input_event(event)
		else:
			var token: String = "mouse:" + edge["button"]
			if event.pressed: held.append(token)
			else: held.erase(token)
		return true
	return false

func _time() -> int:
	return Time.get_ticks_msec() - origin

func _wait(ms: int):
	var deadline = mini(_time() + ms, int(cfg.get("max_duration_ms", 60000)))
	while _time() < deadline:
		await _tick()

func _tick():
	await process_frame
	_flush_writer(false)
	_sample()

func _save_frame(img: Image, name: String) -> Dictionary:
	# Only file encoding runs on this worker. No access to game objects or inputs.
	var error = img.save_png(out + "/" + name)
	return {"error": error, "completed_ms": _time()}

func _flush_writer(wait: bool):
	if writer == null or (writer.is_alive() and not wait):
		return
	var result = writer.wait_to_finish()
	writer = null
	if result["error"] != OK:
		capture_errors.append({"frame_id": pending_frame["frame_id"], "error": result["error"], "t_ms": result["completed_ms"]})
		printerr("PILOT_HARNESS_ERROR frame write failed: " + str(result["error"]))
	else:
		pending_frame["capture_completed_ms"] = result["completed_ms"]
		pending_frame["screenshot_duration_ms"] = result["completed_ms"] - pending_frame["timestamp_ms"]
		screenshot_total_ms += pending_frame["screenshot_duration_ms"]
		frame_count += 1
		frames.store_line(JSON.stringify(pending_frame))
		frames.flush()
	pending_frame = {}

func _capture_frame():
	_flush_writer(false)
	var now := _time()
	if stopped or now >= int(cfg.get("max_duration_ms", 60000)) or now < next_frame:
		return
	# Advance to the next future slot, never catch up overdue screenshots.
	var due := (now - next_frame) / 100 + 1
	skipped_slots += maxi(0, due - 1)
	next_frame += due * 100
	if writer != null:
		skipped_slots += 1
		return
	var img = root.get_texture().get_image()
	if img == null or img.is_empty():
		capture_errors.append({"t_ms": now, "error": "empty viewport image"})
		return
	var name = "frames/f%05d.png" % (frame_count + 1)
	if last_capture_ms >= 0:
		capture_intervals.append(now - last_capture_ms)
	last_capture_ms = now
	pending_frame = {"frame_id": "FRAME:%05d" % (frame_count + 1),
		"path": name, "raw_path": name, "source_path": name, "delivered_path": null,
		"timestamp_ms": now, "t_ms": now, "readback_completed_ms": _time(),
		"probe": active_probe, "step": active_step, "capture_status": "captured",
		"viewport": {"width": img.get_width(), "height": img.get_height()},
		"window": {"id": root.get_window_id(), "visible": root.visible, "focused": root.has_focus()},
		"engine": "godot", "clock": "session_monotonic", "video_position_ms": null}
	writer = Thread.new()
	var error = writer.start(_save_frame.bind(img, name))
	if error != OK:
		writer = null
		capture_errors.append({"t_ms": now, "error": error})

func _finish(completed: bool):
	if finalized or states == null:
		return
	finalized = true
	stopped = true
	_release_all()
	# Exactly one in-flight write. Flush its successful final frame before closing.
	_flush_writer(true)
	states.flush()
	actions.flush()
	frames.flush()
	var valid := completed and frame_count >= 2 and capture_errors.is_empty()
	var record := {"probes": probes, "frames": frame_count, "states": state_count,
		"duration_ms": _time(), "clock": "session_monotonic", "no_state_injection": true,
		"status": "CAPTURED" if valid else "HARNESS_ERROR", "complete": valid,
        "recording_completed": valid, "outcome_observed": "JUDGE_REQUIRED", "coverage_complete": "JUDGE_REQUIRED",
        "input_transport": "godot_Input.parse_input_event", "plan_sha256": cfg.get("plan_sha256", ""),
		"planned_fps": 10, "actual_fps": frame_count * 1000.0 / maxf(1, _time()),
		"skipped_sample_slots": skipped_slots, "sampling_intervals_ms": capture_intervals,
		"screenshot_total_ms": screenshot_total_ms, "capture_errors": capture_errors,
		"video_mapping": "UNAVAILABLE_VIDEO_CHANNEL; raw frames use session_monotonic timestamps"}
	var f = FileAccess.open(out + "/execution.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(record, "  "))
	f.close()
	if not valid:
		f = FileAccess.open(out + "/harness_error.json", FileAccess.WRITE)
		f.store_string(JSON.stringify({"phase": "capture", "frames": frame_count, "reason": "incomplete frame capture", "score": null}))
		f.close()
	states.close()
	actions.close()
	frames.close()

func _finalize():
	_finish(false)

func _all_nodes(n: Node, result: Array):
	result.append(n)
	for child in n.get_children():
		_all_nodes(child, result)

func _snapshot() -> Dictionary:
	var nodes: Array = []
	_all_nodes(root, nodes)
	var values := {}
	var provenance := {}
	for w in cfg["watchers"]:
		var matches: Array = []
		for n in nodes:
			var sc = n.get_script()
			if sc != null and sc.resource_path == w["script"]:
				matches.append(n)
		var ix = int(w["index"])
		if ix >= matches.size():
			continue
		var node: Node = matches[ix]
		var prop = w["property"]
		var readout = _read_property_path(node, prop)
		if not readout["found"]:
			continue
		values[w["id"]] = _json(readout["value"])
		provenance[w["id"]] = {"node": str(node.get_path()), "instance_id": node.get_instance_id(), "script": w["script"], "property": prop}
	return {"values": values, "provenance": provenance}

func _read_property_path(target, path: String) -> Dictionary:
	# Bounded field/array reads only: no expression evaluation or method calls.
	var selector := RegEx.new()
	selector.compile("^([A-Za-z_][A-Za-z_0-9]*)(?:\\[([0-9]{1,3})\\])?$|^([0-9]{1,3})$")
	var current = target
	for part in path.split("."):
		var parsed = selector.search(part)
		if parsed == null:
			return {"found": false}
		if parsed.get_string(3) != "":
			var dotted_index = int(parsed.get_string(3))
			if not current is Array or dotted_index >= current.size():
				return {"found": false}
			current = current[dotted_index]
			continue
		var field = parsed.get_string(1)
		if current is Object and is_instance_valid(current):
			var found := false
			for p in current.get_property_list():
				if p["name"] == field:
					found = true
					break
			if not found:
				return {"found": false}
			current = current.get(field)
		elif current is Dictionary and current.has(field):
			current = current[field]
		else:
			return {"found": false}
		if parsed.get_string(2) != "":
			var index = int(parsed.get_string(2))
			if not current is Array or index >= current.size():
				return {"found": false}
			current = current[index]
	return {"found": true, "value": current}

func _sample():
	var snap = _snapshot()
	state_count += 1
	states.store_line(JSON.stringify({"t_ms": _time(), "probe": active_probe, "step": active_step, "values": snap["values"], "provenance": snap["provenance"]}))
	states.flush()

func _condition(snap: Dictionary, c: Dictionary) -> bool:
	var values: Dictionary = snap["values"]
	if not values.has(c["watch"]):
		return false
	var a = values[c["watch"]]
	var b = c["value"]
	# JSON plan conditions encode booleans as 0/1; avoid bool/number
	# comparison errors without changing the observed game property.
	if a is bool and b is bool:
		return a == b if c["op"] == "eq" else a != b
	if a is bool and (b is int or b is float):
		if c["op"] == "eq":
			return a == (float(b) != 0.0)
		if c["op"] == "ne":
			return a != (float(b) != 0.0)
		return false
	if c["op"] != "distance_lt" and (not (a is int or a is float) or not (b is int or b is float)):
		var signature = str(c["watch"]) + ":" + str(c["op"])
		if not condition_errors.has(signature):
			condition_errors[signature] = true
			printerr("PILOT_HARNESS_ERROR incompatible observation condition " + signature)
		return false
	match c["op"]:
		"eq": return a == b
		"ne": return a != b
		"gt": return (a is float or a is int) and a > b
		"lt": return (a is float or a is int) and a < b
		"distance_lt":
			if not values.has(c.get("target_watch", "")) or not a is Dictionary:
				return false
			var target = values[c["target_watch"]]
			if not target is Dictionary:
				return false
			return Vector3(a.get("x",0),a.get("y",0),a.get("z",0)).distance_to(Vector3(target.get("x",0),target.get("y",0),target.get("z",0))) < float(b)
	return false

func _press(key: String) -> bool:
	if "+" in key:
		for part in key.split("+"):
			if not _press(part):
				return false
		return true
	if key in ["LMB", "RMB"]:
		var e := InputEventMouseButton.new()
		e.button_index = MOUSE_BUTTON_LEFT if key == "LMB" else MOUSE_BUTTON_RIGHT
		e.pressed = true
		Input.parse_input_event(e)
		held.append(key)
		return true
	var lookup = {"Esc": "Escape", "Return": "Enter"}.get(key, key)
	var code = OS.find_keycode_from_string(lookup)
	if code == KEY_NONE:
		return false
	var e := InputEventKey.new()
	e.physical_keycode = code
	e.keycode = code
	e.pressed = true
	Input.parse_input_event(e)
	held.append(key)
	return true

func _release_all():
	for token in held.duplicate():
		var mouse: bool = str(token).begins_with("mouse:")
		var edge = {"id": "safety_release", "source_action_id": "safety_release", "kind": "mouse_up" if mouse else "key_up", "key": "" if mouse else token, "button": str(token).trim_prefix("mouse:") if mouse else "", "x": 0.5, "y": 0.5, "at_ms": _time(), "rubric_ids": [], "safety_release": true}
		var sent := _send_edge(edge)
		_log_edge(edge, sent)

func _json(v):
	if v is Vector3:
		return {"x": v.x, "y": v.y, "z": v.z}
	if v is Vector2:
		return {"x": v.x, "y": v.y}
	if v is Object:
		return str(v)
	if v is Array:
		var a: Array = []
		for x in v: a.append(_json(x))
		return a
	if v is Dictionary:
		var d := {}
		for k in v: d[str(k)] = _json(v[k])
		return d
	return v
