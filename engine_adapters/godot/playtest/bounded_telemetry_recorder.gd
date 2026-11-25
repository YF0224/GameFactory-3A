extends "bounded_recorder.gd"
## Versioned read-only telemetry. Original inputs, clocks and pixels are retained.
var telemetry: FileAccess
var callback_count := 0
var tick_count := 0
var next_telemetry := 0

func _initialize():
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() >= 2:
		DirAccess.make_dir_recursive_absolute(arguments[1])
		telemetry = FileAccess.open(arguments[1] + "/capture_telemetry.jsonl", FileAccess.WRITE)
	super._initialize()

func _telemetry(reason: String):
	if telemetry == null:
		return
	var window = root
	var record := {"reason": reason, "t_ms": _time(), "callbacks": callback_count,
		"ticks": tick_count, "engine_frames_drawn": Engine.get_frames_drawn(),
		"writer_present": writer != null, "writer_alive": writer != null and writer.is_alive(),
		"frame_count": frame_count, "sparse_cursor": sparse_cursor,
		"readiness_captured": readiness_captured, "stopped": stopped,
		"callback_connected": RenderingServer.frame_post_draw.is_connected(_capture_frame),
		"root_valid": is_instance_valid(window), "paused": paused,
		"no_state_injection": true}
	if is_instance_valid(window):
		record["window"] = {"id": window.get_window_id(), "visible": window.visible,
			"focused": window.has_focus(), "size": [window.size.x, window.size.y]}
	telemetry.store_line(JSON.stringify(record))
	telemetry.flush()

func _tick():
	await super._tick()
	tick_count += 1
	if _time() >= next_telemetry:
		next_telemetry = _time() + 1000
		_telemetry("tick")

func _capture_frame():
	callback_count += 1
	super._capture_frame()

func _finish(completed: bool):
	# SceneTree._finalize may run after its root Window has been freed. Preserve
	# actual cleanup even then, without pretending an interrupted take completed.
	if finalized or states == null:
		return
	_telemetry("finish_completed" if completed else "finish_interrupted")
	finalized = true
	stopped = true
	if RenderingServer.frame_post_draw.is_connected(_capture_frame):
		RenderingServer.frame_post_draw.disconnect(_capture_frame)
	_release_all()
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
	var file = FileAccess.open(out + "/execution.json", FileAccess.WRITE)
	file.store_string(JSON.stringify(record, "  "))
	file.close()
	if not valid:
		file = FileAccess.open(out + "/harness_error.json", FileAccess.WRITE)
		file.store_string(JSON.stringify({"phase": "capture", "frames": frame_count,
			"reason": "incomplete frame capture", "score": null}))
		file.close()
	var window = root
	var window_id = window.get_window_id() if is_instance_valid(window) else null
	file = FileAccess.open(out + "/input_view_cleanup.json", FileAccess.WRITE)
	file.store_string(JSON.stringify({"input_cleanup": held.is_empty(),
		"held_keys_after_release": held.size(), "window_id": window_id,
		"root_valid_at_cleanup": is_instance_valid(window), "t_ms": _time(),
		"capture_callback_disconnected": not RenderingServer.frame_post_draw.is_connected(_capture_frame),
		"process_exit_requested": true}))
	file.close()
	states.close()
	actions.close()
	frames.close()
	_telemetry("cleanup_complete")
	if telemetry != null:
		telemetry.close()
		telemetry = null
