extends SceneTree
# Instrumentation only: native input and read-only observation of the authored scene.
var output := ""
var profile := ""
var role := ""
var game: Node
var serial := 0
var busy := false
var stopping := false
var held: Array[int] = []
var origin := 0
var next_frame := 0
var frame := 0

func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--pair-output="): output = arg.trim_prefix("--pair-output=")
		if arg.begins_with("--pair-profile="): profile = arg.trim_prefix("--pair-profile=")
		if arg.begins_with("--pair-role="): role = arg.trim_prefix("--pair-role=")
	call_deferred("boot")

func put(name: String, value) -> void:
	var file := FileAccess.open(output.path_join(name + ".tmp"), FileAccess.WRITE)
	file.store_string(JSON.stringify(value)); file.close()
	DirAccess.rename_absolute(output.path_join(name + ".tmp"), output.path_join(name))

func append(name: String, value) -> void:
	var path := output.path_join(name)
	var file := FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE)
	file.seek_end(); file.store_line(JSON.stringify(value)); file.close()

func clean(value):
	if value is Vector2: return [value.x, value.y]
	if value is Vector3: return [value.x, value.y, value.z]
	if value is Dictionary:
		var result := {}
		for key in value: result[str(key)] = clean(value[key])
		return result
	if value is Array:
		var result := []
		for item in value: result.append(clean(item))
		return result
	if value is Object: return null
	return value

func boot() -> void:
	origin = Time.get_ticks_msec()
	var packed = load(ProjectSettings.get_setting("application/run/main_scene", ""))
	if not packed is PackedScene:
		put("boot_error.json", {"error":"main scene not loadable"}); quit(2); return
	game = packed.instantiate(); root.add_child(game); current_scene = game
	DirAccess.make_dir_recursive_absolute(output.path_join("frames"))
	put("process.json", {"pid":OS.get_process_id(), "role":role, "project":ProjectSettings.globalize_path("res://"), "origin_unix":Time.get_unix_time_from_system()})
	while not stopping:
		await process_frame
		if Time.get_ticks_msec() >= next_frame:
			next_frame = Time.get_ticks_msec() + 250
			await RenderingServer.frame_post_draw
			observe()
		if not busy and FileAccess.file_exists(output.path_join("command.json")):
			var command = JSON.parse_string(FileAccess.get_file_as_string(output.path_join("command.json")))
			if command is Dictionary and int(command.get("id",0)) > serial:
				serial = int(command.id); busy = true; execute(command)
		if Time.get_ticks_msec() - origin >= 75000:
			await RenderingServer.frame_post_draw
			observe()
			put("recording_complete.json", {"duration_ms":Time.get_ticks_msec()-origin,"requested_duration_ms":75000,"pid":OS.get_process_id(),"role":role})
			finish()

func observe() -> void:
	var state := {}
	var room := ""
	if profile == "opus_g043": state = game.get("snap"); room = str(game.get("room_code"))
	elif profile == "sol_g043": state = game.get("state"); room = str(game.get("address"))
	elif profile == "astra_g043":
		var net = game.get("net"); state = net.get("state"); room = str(net.get("room"))
	elif profile == "glm_g043":
		room = str(game.get("port"))
		state = {"ready":game.get("ready_state"),"snapshot":game.get("last_snapshot")}
	var mp = game.multiplayer
	var peers := []
	var uid := 0
	if mp.has_multiplayer_peer() and mp.multiplayer_peer.get_connection_status() == MultiplayerPeer.CONNECTION_CONNECTED:
		uid = mp.get_unique_id()
		for peer in mp.get_peers(): peers.append(peer)
	var row := {"t_ms":Time.get_ticks_msec()-origin,"unix":Time.get_unix_time_from_system(),"pid":OS.get_process_id(),"role":role,"peer_id":uid,"peers":peers,"room":room,"state":clean(state)}
	append("state_trace.jsonl",row); put("latest.json",row)
	var image := root.get_texture().get_image()
	if image != null and not image.is_empty():
		var path := "frames/%06d.png" % frame
		if image.save_png(output.path_join(path)) == OK:
			append("frame_index.jsonl", {"frame_id":str(frame),"t_ms":row.t_ms,"path":path,"unix":row.unix})
			frame += 1

func find_control(node: Node, command: Dictionary):
	if node is Control and node.is_visible_in_tree():
		if command.kind == "click" and node is Button and not node.disabled and node.text == command.text: return node
		if command.kind == "text" and node is LineEdit:
			if str(command.get("placeholder","")) == "" or node.placeholder_text == command.placeholder: return node
	for child in node.get_children():
		var result = find_control(child,command)
		if result != null: return result
	return null

func key(code: int, down: bool, unicode_value := 0) -> void:
	var event := InputEventKey.new(); event.keycode = code; event.physical_keycode = code; event.unicode = unicode_value; event.pressed = down
	Input.parse_input_event(event)
	if down and not held.has(code): held.append(code)
	elif not down: held.erase(code)

func click_at(position: Vector2) -> void:
	var motion := InputEventMouseMotion.new(); motion.position = position; motion.global_position = position; Input.parse_input_event(motion)
	for down in [true,false]:
		var event := InputEventMouseButton.new(); event.button_index = MOUSE_BUTTON_LEFT; event.position = position; event.global_position = position; event.pressed = down
		Input.parse_input_event(event); await process_frame

func execute(command: Dictionary) -> void:
	var start := Time.get_ticks_msec()-origin
	var ok := true
	var error := ""
	if command.kind in ["click","text"]:
		var control = find_control(game,command)
		if control == null: ok = false; error = "visible authored control not found"
		else:
			await click_at(control.get_global_rect().get_center())
			if command.kind == "text":
				# Select text using real Home/Shift+End key events, never set LineEdit.text.
				key(KEY_HOME,true); key(KEY_HOME,false)
				var end := InputEventKey.new(); end.keycode = KEY_END; end.physical_keycode = KEY_END; end.shift_pressed = true; end.pressed = true; Input.parse_input_event(end)
				end = end.duplicate(); end.pressed = false; Input.parse_input_event(end)
				for character in str(command.text):
					key(0,true,character.unicode_at(0)); key(0,false); await process_frame
	elif command.kind == "key":
		var code := OS.find_keycode_from_string(command.key)
		key(code,true); await create_timer(float(command.get("duration",0.2))).timeout; key(code,false)
	elif command.kind == "stop":
		finish(); return
	else: ok = false; error = "unsupported native command"
	var row := {"action_id":role+":"+str(command.id),"action":command.kind,"t_ms":start,"end_t_ms":Time.get_ticks_msec()-origin,"unix":Time.get_unix_time_from_system(),"command":command,"sent":ok,"ok":ok,"error":error,"route":"Input.parse_input_event"}
	append("actions.jsonl",row); put("ack.json",row); busy = false

func finish() -> void:
	if stopping: return
	stopping = true
	for code in held.duplicate(): key(code,false)
	put("input_view_cleanup.json", {"input_cleanup":held.is_empty(),"view_cleanup":true,"role":role,"pid":OS.get_process_id()})
	quit()
