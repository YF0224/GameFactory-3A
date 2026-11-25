extends "bounded_telemetry_recorder.gd"
## Restore native render work only when a frozen screenshot slot is due.
## force_draw's zero frame_step does not advance the game's simulation clock.
var last_draw_ms := -1
var forced_draws := 0

func _capture_frame():
	last_draw_ms = _time()
	super._capture_frame()

func _tick():
	await super._tick()
	if stopped or finalized or cfg.is_empty() or not is_instance_valid(root):
		return
	var now := _time()
	if writer != null or now >= int(cfg.get("recording_ms", cfg.get("max_duration_ms", 60000))):
		return
	var due := not readiness_captured
	if readiness_captured and not sparse_schedule.is_empty():
		var points: Array = sparse_schedule["points"]
		due = sparse_cursor < points.size() and now >= int(points[sparse_cursor]["at_ms"])
	elif sparse_schedule.is_empty():
		due = now >= next_frame
	if due and now - last_draw_ms >= 25:
		forced_draws += 1
		_telemetry("force_draw_before")
		RenderingServer.force_draw(false, 0.0)
		_telemetry("force_draw_after")
