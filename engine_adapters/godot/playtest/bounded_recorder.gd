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
var active_metadata: Dictionary = {}
var states: FileAccess
var actions: FileAccess
var frames: FileAccess
var probes: Array = []
var held: Array = []
var mouse_position := Vector2.ZERO
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
var sparse_schedule: Dictionary = {}
var sparse_cursor := 0
var readiness_captured := false

func _initialize():
	call_deferred("_run")

func _run():
	var args := OS.get_cmdline_user_args()
	if args.size() < 2 or args.size() > 3:
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
	if cfg.has("native_capture_schedule"):
		sparse_schedule = cfg["native_capture_schedule"]
		var schedule_file = FileAccess.open(out + "/capture_schedule.json", FileAccess.WRITE)
		schedule_file.store_string(JSON.stringify(sparse_schedule, "  "))
		schedule_file.close()
		var ready_file = FileAccess.open(out + "/play_started.json", FileAccess.WRITE)
		ready_file.store_string(JSON.stringify({"recorder_elapsed_ms": 0, "clock": "session_monotonic", "origin_ticks_ms": origin}))
		ready_file.close()
	RenderingServer.frame_post_draw.connect(_capture_frame)
	var main_path = args[2] if args.size() > 2 else ProjectSettings.get_setting("application/run/main_scene", "")
	var scene = load(main_path)
	if not scene is PackedScene:
		printerr("PILOT_PRODUCT_ERROR cannot load main scene")
		quit(3)
		return
	var game = scene.instantiate()
	root.add_child(game)
	# Bootstrap code may replace its own scene. Observe root, never assume it survives.
	await _wait(1800)
	for probe in cfg.get("probes", []):
		active_probe = probe["id"]
		var record = {"id": active_probe, "start_ms": _time(), "preconditions_met": true, "steps": []}
		var snap = _snapshot()
		for c in probe.get("preconditions", []):
			if not _condition(snap, c):
				record["preconditions_met"] = false
		if not record["preconditions_met"]:
			record["status"] = "TRIGGER_FAILED"
			probes.append(record)
			continue
		for step in probe["steps"]:
			if _time() > int(cfg.get("max_duration_ms", 60000)):
				record["status"] = "BUDGET_EXHAUSTED"
				break
			active_step = step["id"]
			active_metadata = {"action_id": str(active_probe) + "/" + str(active_step),
				"probe_id": active_probe, "step_id": active_step,
				"criterion_ids": probe.get("criterion_ids", []),
				"purpose": step.get("purpose", probe.get("purpose", "")),
				"expected_observation": step.get("expected_observation", "")}
			_write_action({"t_ms": _time(), "kind": "observation", "phase": "start"})
			var sr = {"id": active_step, "start_ms": _time(), "planned_time_ms": _time(), "kind": step["kind"]}
			_sample()
			var kind = step["kind"]
			if kind == "input":
				var sent = _press(step["key"])
				action_count += 1
				_write_action({"seq": action_count, "t_ms": _time(), "probe": active_probe, "step": active_step, "key": step["key"], "sent": sent, "kind": "press"})
				actions.flush()
				await _wait(int(step["duration_ms"]))
				_release_all(true, step["key"])
				sr["sent"] = sent
			elif kind in ["mouse_move", "mouse_click", "mouse_drag", "mouse_down", "mouse_up", "mouse_hold", "mouse_wheel"]:
				await _mouse_gesture(step)
				sr["sent"] = true
			elif kind == "look":
				var motion := InputEventMouseMotion.new()
				var amount := float(step["value"])
				match step["key"]:
					"Left": motion.relative = Vector2(-amount, 0)
					"Right": motion.relative = Vector2(amount, 0)
					"Up": motion.relative = Vector2(0, -amount)
					"Down": motion.relative = Vector2(0, amount)
				_move_mouse(mouse_position + motion.relative, motion.relative)
				_write_action({"t_ms": _time(), "probe": active_probe, "step": active_step, "key": "MouseMotion", "kind": "press", "sent": true, "dx": motion.relative.x, "dy": motion.relative.y})
				actions.flush()
				await _wait(int(step["duration_ms"]))
				sr["sent"] = true
			elif kind == "wait":
				actions.flush()
				await _wait(int(step["duration_ms"]))
			elif kind == "wait_until" or kind == "move_until":
				if kind == "move_until":
					var sent = _press(step["key"])
					action_count += 1
					_write_action({"seq": action_count, "t_ms": _time(), "probe": active_probe, "step": active_step, "key": step["key"], "sent": sent, "kind": "press"})
				actions.flush()
				var deadline = mini(_time() + int(step["timeout_ms"]), int(cfg.get("max_duration_ms", 60000)))
				while _time() < deadline and not _condition(_snapshot(), step):
					await _tick()
				sr["condition_met"] = _condition(_snapshot(), step)
				_release_all(true, step["key"])
				if not sr["condition_met"]:
					record["status"] = "TRIGGER_FAILED"
			else:
				printerr("PILOT_HARNESS_ERROR unknown step kind")
			_sample()
			sr["end_ms"] = _time()
			_write_action({"t_ms": _time(), "kind": "observation", "phase": "end"})
			record["steps"].append(sr)
			if record.get("status", "") == "TRIGGER_FAILED":
				break
		record["end_ms"] = _time()
		if not record.has("status"):
			record["status"] = "EXECUTED"
		probes.append(record)
	active_probe = "tail"
	_release_all()
	active_metadata = {}
	if cfg.has("recording_ms"):
		# Capture the rest of the pinned observation window after actions finish.
		while _time() < int(cfg["recording_ms"]):
			await _tick()
	else:
		await _wait(500)
	_release_all()
	RenderingServer.frame_post_draw.disconnect(_capture_frame)
	_finish(true)
	if frame_count < 2 or not capture_errors.is_empty():
		printerr("PILOT_HARNESS_ERROR insufficient or failed frame capture frames=%d" % frame_count)
		quit(4)
	else:
		print("PILOT_COMPLETE frames=%d states=%d" % [frame_count, state_count])
		quit(0)

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
	if stopped or now >= int(cfg.get("recording_ms", cfg.get("max_duration_ms", 60000))) or now < next_frame:
		return
	var sparse_point: Dictionary = {}
	if not sparse_schedule.is_empty():
		if writer != null:
			return
		if not readiness_captured:
			sparse_point = {"at_ms": -1, "capture_ids": ["readiness"], "criterion_ids": []}
		else:
			var points: Array = sparse_schedule["points"]
			while sparse_cursor < points.size() and now - int(points[sparse_cursor]["at_ms"]) > int(sparse_schedule["tolerance_ms"]):
				skipped_slots += 1
				sparse_cursor += 1
			if sparse_cursor >= points.size() or now < int(points[sparse_cursor]["at_ms"]):
				return
			sparse_point = points[sparse_cursor]
	else:
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
	if not sparse_schedule.is_empty():
		pending_frame["sample_at_ms"] = sparse_point["at_ms"]
		pending_frame["capture_ids"] = sparse_point["capture_ids"]
		pending_frame["criterion_ids"] = sparse_point["criterion_ids"]
		if readiness_captured:
			sparse_cursor += 1
		else:
			readiness_captured = true
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
	var held_after_release := held.size()
	var cleanup_file = FileAccess.open(out + "/input_view_cleanup.json", FileAccess.WRITE)
	cleanup_file.store_string(JSON.stringify({"input_cleanup": held_after_release == 0, "held_keys_after_release": held_after_release,
		"capture_callback_disconnected": not RenderingServer.frame_post_draw.is_connected(_capture_frame),
		"window_id": root.get_window_id(), "t_ms": _time(), "process_exit_requested": true}))
	cleanup_file.close()
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
	# Bounded fields, arrays and integer-key dictionaries; no calls or expressions.
	var selector := RegEx.new()
	selector.compile("^([A-Za-z_][A-Za-z_0-9]*)(?:\\[([0-9]{1,3})\\])?$|^([0-9]{1,3})$")
	var current = target
	for part in path.split("."):
		var parsed = selector.search(part)
		if parsed == null:
			return {"found": false}
		if parsed.get_string(3) != "":
			var dotted_index = int(parsed.get_string(3))
			if current is Array:
				if dotted_index >= current.size(): return {"found": false}
			elif current is Dictionary:
				if not current.has(dotted_index): return {"found": false}
			else:
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
		elif current is Vector2 or current is Vector2i:
			# Component selectors are read-only fields, never expressions/methods.
			if field == "x": current = current.x
			elif field == "y": current = current.y
			else: return {"found": false}
		elif current is Vector3 or current is Vector3i:
			if field == "x": current = current.x
			elif field == "y": current = current.y
			elif field == "z": current = current.z
			else: return {"found": false}
		else:
			return {"found": false}
		if parsed.get_string(2) != "":
			var index = int(parsed.get_string(2))
			if current is Array:
				if index >= current.size(): return {"found": false}
			elif current is Dictionary:
				# Integer keys only. Never coerce a numeric string or invoke a method.
				if not current.has(index): return {"found": false}
			else:
				return {"found": false}
			current = current[index]
	return {"found": true, "value": current}

func _sample():
	var snap = _snapshot()
	state_count += 1
	states.store_line(JSON.stringify({"t_ms": _time(), "probe": active_probe, "step": active_step, "values": snap["values"], "provenance": snap["provenance"]}))
	states.flush()

func _write_action(row: Dictionary):
	row.merge(active_metadata)
	actions.store_line(JSON.stringify(row))
	actions.flush()

func _condition(snap: Dictionary, c: Dictionary) -> bool:
	var values: Dictionary = snap["values"]
	if not values.has(c["watch"]):
		return false
	var a = values[c["watch"]]
	var b = c["value"]
	# JSON plan conditions encode booleans as 0/1; avoid bool/number
	# comparison errors without changing the observed game property.
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

func _mouse_mask() -> int:
	var mask := 0
	if "LMB" in held: mask |= MOUSE_BUTTON_MASK_LEFT
	if "RMB" in held: mask |= MOUSE_BUTTON_MASK_RIGHT
	if "MMB" in held: mask |= MOUSE_BUTTON_MASK_MIDDLE
	return mask

func _mouse_button(key: String, pressed: bool):
	var event := InputEventMouseButton.new()
	event.button_index = {"LMB": MOUSE_BUTTON_LEFT, "RMB": MOUSE_BUTTON_RIGHT, "MMB": MOUSE_BUTTON_MIDDLE}[key]
	# Input.parse_input_event expects window pixels; the viewport applies its inverse stretch.
	event.position = root.get_final_transform() * mouse_position
	event.global_position = event.position
	event.button_mask = _mouse_mask()
	event.pressed = pressed
	Input.parse_input_event(event)

func _move_mouse(position: Vector2, relative = null):
	var size := root.get_visible_rect().size
	var clamped := position.clamp(Vector2.ZERO, (size - Vector2.ONE).max(Vector2.ZERO))
	var event := InputEventMouseMotion.new()
	var transform := root.get_final_transform()
	event.relative = transform.basis_xform(clamped - mouse_position) if relative == null else relative
	event.position = transform * clamped
	event.global_position = event.position
	event.button_mask = _mouse_mask()
	mouse_position = clamped
	Input.parse_input_event(event)

func _mouse_gesture(step: Dictionary):
	var size := root.get_visible_rect().size
	var start := Vector2(float(step["x"]), float(step["y"])) * (size - Vector2.ONE)
	_move_mouse(start)
	var kind: String = step["kind"]
	var key: String = {"left": "LMB", "right": "RMB", "middle": "MMB"}.get(step.get("button", "left"), "LMB")
	if kind in ["mouse_click", "mouse_drag", "mouse_down", "mouse_hold"]:
		_press(key)
	elif kind == "mouse_up":
		held.erase(key)
		_mouse_button(key, false)
	elif kind == "mouse_wheel":
		for axis in ["delta_x", "delta_y"]:
			var delta := int(step[axis])
			if delta == 0: continue
			var event := InputEventMouseButton.new()
			event.button_index = (MOUSE_BUTTON_WHEEL_RIGHT if delta > 0 else MOUSE_BUTTON_WHEEL_LEFT) if axis == "delta_x" else (MOUSE_BUTTON_WHEEL_DOWN if delta > 0 else MOUSE_BUTTON_WHEEL_UP)
			# The protocol expresses CSS-style pixels; one notch is 100 pixels.
			event.factor = absf(delta) / 100.0
			event.position = root.get_final_transform() * mouse_position
			event.global_position = event.position
			event.button_mask = _mouse_mask()
			event.pressed = true
			Input.parse_input_event(event)
			var released := event.duplicate()
			released.pressed = false
			Input.parse_input_event(released)
	var began := _time()
	var duration := int(step["duration_ms"])
	var deadline := mini(began + duration, int(cfg.get("max_duration_ms", 60000)))
	if kind == "mouse_drag":
		var end := Vector2(float(step["to_x"]), float(step["to_y"])) * (size - Vector2.ONE)
		while _time() < deadline:
			await _tick()
			_move_mouse(start.lerp(end, clampf(float(_time() - began) / duration, 0.0, 1.0)))
		# Only reach the declared endpoint if the actual gesture duration fit.
		if _time() >= began + duration:
			_move_mouse(end)
	else:
		await _wait(duration)
	if kind in ["mouse_click", "mouse_drag", "mouse_hold"]:
		held.erase(key)
		_mouse_button(key, false)
		_write_action({"t_ms": _time(), "kind": "release", "key": key, "sent": true})
	action_count += 1
	_write_action({"seq": action_count, "t_ms": began, "end_ms": _time(), "probe": active_probe, "step": active_step, "kind": kind, "gesture": step, "viewport": {"x": size.x, "y": size.y}, "position": {"x": mouse_position.x, "y": mouse_position.y}, "sent": true})
	actions.flush()

const PHYSICAL_KEYS = {"0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "a": "A", "alt": "Alt", "altleft": "Alt", "altright": "Alt", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right", "arrowup": "Up", "b": "B", "backspace": "Backspace", "c": "C", "control": "Ctrl", "controlleft": "Ctrl", "controlright": "Ctrl", "ctrl": "Ctrl", "d": "D", "del": "Delete", "delete": "Delete", "digit0": "0", "digit1": "1", "digit2": "2", "digit3": "3", "digit4": "4", "digit5": "5", "digit6": "6", "digit7": "7", "digit8": "8", "digit9": "9", "down": "Down", "down_arrow": "Down", "e": "E", "end": "End", "enter": "Enter", "esc": "Escape", "escape": "Escape", "f": "F", "f1": "F1", "f10": "F10", "f11": "F11", "f12": "F12", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8", "f9": "F9", "g": "G", "h": "H", "home": "Home", "i": "I", "ins": "Insert", "insert": "Insert", "j": "J", "k": "K", "keya": "A", "keyb": "B", "keyc": "C", "keyd": "D", "keye": "E", "keyf": "F", "keyg": "G", "keyh": "H", "keyi": "I", "keyj": "J", "keyk": "K", "keyl": "L", "keym": "M", "keyn": "N", "keyo": "O", "keyp": "P", "keyq": "Q", "keyr": "R", "keys": "S", "keyt": "T", "keyu": "U", "keyv": "V", "keyw": "W", "keyx": "X", "keyy": "Y", "keyz": "Z", "l": "L", "left": "Left", "left_arrow": "Left", "leftalt": "Alt", "leftctrl": "Ctrl", "leftshift": "Shift", "lmb": "LMB", "m": "M", "mmb": "MMB", "n": "N", "o": "O", "p": "P", "pagedown": "PageDown", "pageup": "PageUp", "pgdn": "PageDown", "pgup": "PageUp", "q": "Q", "r": "R", "return": "Enter", "right": "Right", "right_arrow": "Right", "rmb": "RMB", "s": "S", "shift": "Shift", "shiftleft": "Shift", "shiftright": "Shift", "space": "Space", "spacebar": "Space", "t": "T", "tab": "Tab", "u": "U", "up": "Up", "up_arrow": "Up", "v": "V", "w": "W", "x": "X", "y": "Y", "z": "Z"}

func _press(key: String) -> bool:
	if "+" in key:
		for part in key.split("+"):
			if not _press(part):
				return false
		return true
	key = PHYSICAL_KEYS.get(key.to_lower(), "")
	if key.is_empty():
		printerr("PILOT_HARNESS_ERROR unsupported physical key")
		return false
	if key in ["LMB", "RMB", "MMB"]:
		if not key in held:
			held.append(key)
		_mouse_button(key, true)
		return true
	var lookup = key
	var code = (KEY_ALT if lookup == "Alt" else OS.find_keycode_from_string(lookup))
	if code == KEY_NONE:
		return false
	var e := InputEventKey.new()
	e.physical_keycode = code
	e.keycode = code
	e.pressed = true
	Input.parse_input_event(e)
	if not key in held: held.append(key)
	if actions != null:
		_write_action({"t_ms": _time(), "kind": "physical_press", "key": key, "code": code, "sent": true})
	return true

func _release_all(keys_only := false, requested := ""):
	var requested_keys := []
	for part in requested.split("+"):
		requested_keys.append(PHYSICAL_KEYS.get(part.to_lower(), ""))
	for key in held.duplicate():
		if keys_only and key in ["LMB", "RMB", "MMB"] and not key in requested_keys: continue
		held.erase(key)
		if key in ["LMB", "RMB", "MMB"]:
			_mouse_button(key, false)
		else:
			var e := InputEventKey.new()
			var lookup = key
			e.physical_keycode = (KEY_ALT if lookup == "Alt" else OS.find_keycode_from_string(lookup))
			e.keycode = e.physical_keycode
			e.pressed = false
			Input.parse_input_event(e)
		# Both press and release are actual events, never backfilled from the plan.
		_write_action({"t_ms": _time(), "probe": active_probe, "step": active_step, "key": key, "sent": true, "kind": "release"})
	if actions != null:
		actions.flush()

func _json(v):
	if v is Vector3 or v is Vector3i:
		return {"x": v.x, "y": v.y, "z": v.z}
	if v is Vector2 or v is Vector2i:
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
