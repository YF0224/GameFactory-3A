extends Node2D

const VECTORS = {"RIGHT": Vector2i(1,0), "DOWN": Vector2i(0,1), "LEFT": Vector2i(-1,0), "UP": Vector2i(0,-1)}
const FOODS = [Vector2i(5,2), Vector2i(5,4), Vector2i(2,4), Vector2i(2,1)]
var body: Array[Vector2i] = []
var direction = "RIGHT"
var pending = "RIGHT"
var eaten = 0
var ticks = 0
var alive = true
var won = false
var paused = false
var elapsed = 0.0
var test_out = ""
var test_actions: PackedStringArray
var trace: Array = []
var recording = false
var title: Label

func reset_game():
	body.assign([Vector2i(3,2),Vector2i(2,2),Vector2i(1,2)])
	direction = "RIGHT"
	pending = "RIGHT"
	eaten = 0
	ticks = 0
	alive = true
	won = false
	paused = false
	elapsed = 0.0

func turn(action: String):
	if VECTORS[action] != -VECTORS[direction]:
		pending = action

func step_game():
	if not alive or won or paused:
		return
	direction = pending
	var head: Vector2i = body[0] + VECTORS[direction]
	var eating = head == FOODS[eaten]
	var occupied = body if eating else body.slice(0,body.size()-1)
	ticks += 1
	if head.x < 0 or head.x >= 8 or head.y < 0 or head.y >= 6 or head in occupied:
		alive = false
	else:
		body.push_front(head)
		if eating:
			eaten += 1
			won = eaten >= 3
		else:
			body.pop_back()

func handle(action: String, advance: bool):
	if action == "RESET":
		reset_game()
	else:
		turn(action)
		if advance:
			step_game()
	refresh()

func state():
	var points = []
	for p in body:
		points.append([p.x,p.y])
	var food = FOODS[eaten]
	return {"body":points,"direction":direction,"food":[food.x,food.y],"foods":eaten,"alive":alive,"won":won,"ticks":ticks}

func _ready():
	title = Label.new()
	title.position = Vector2(32,24)
	title.add_theme_font_size_override("font_size",20)
	add_child(title)
	var help = Label.new()
	help.position = Vector2(32,510)
	help.text = "Arrows / WASD: turn   R: restart   Space: pause\nEat 3 apples. Avoid walls and yourself."
	add_child(help)
	reset_game()
	refresh()
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--snake-out="):
			test_out = arg.trim_prefix("--snake-out=")
	if test_out != "":
		test_actions = FileAccess.get_file_as_string(test_out.path_join("actions.txt")).strip_edges().split("\n")
		recording = true
		record_test.call_deferred()

func record_test():
	for index in range(test_actions.size()):
		var action = test_actions[index]
		handle(action,true)
		await RenderingServer.frame_post_draw
		var screenshot = "frames/%03d.png" % index
		var result = get_viewport().get_texture().get_image().save_png(test_out.path_join(screenshot))
		if result != OK:
			push_error("Screenshot save failed")
			get_tree().quit(2)
			return
		trace.append({"index":index,"action":action,"state":state(),"screenshot":screenshot})
	var file = FileAccess.open(test_out.path_join("trace.json"),FileAccess.WRITE)
	file.store_string(JSON.stringify(trace,"  "))
	file.close()
	file = FileAccess.open(test_out.path_join("runtime.json"),FileAccess.WRITE)
	file.store_string(JSON.stringify({"engine":"godot","version":Engine.get_version_info().string,"input":"in-engine scripted commands through shared gameplay handler","renderer":RenderingServer.get_video_adapter_name()},"  "))
	file.close()
	get_tree().quit()

func _unhandled_key_input(event):
	if recording or not event is InputEventKey or not event.pressed or event.echo:
		return
	var keys = {KEY_RIGHT:"RIGHT",KEY_D:"RIGHT",KEY_LEFT:"LEFT",KEY_A:"LEFT",KEY_UP:"UP",KEY_W:"UP",KEY_DOWN:"DOWN",KEY_S:"DOWN",KEY_R:"RESET"}
	if event.keycode in keys:
		handle(keys[event.keycode],false)
	elif event.keycode == KEY_SPACE:
		paused = not paused
		refresh()

func _process(delta):
	if recording:
		return
	elapsed += delta
	if elapsed >= 0.3:
		elapsed = 0.0
		step_game()
		refresh()

func refresh():
	var status = "GOAL REACHED" if won else ("GAME OVER" if not alive else ("PAUSED" if paused else "PLAYING"))
	title.text = "GODOT SNAKE — %s · FOOD %d/3" % [status,eaten]
	queue_redraw()

func _draw():
	if won or not alive:
		draw_rect(Rect2(24,12,744,65),Color8(35,135,70) if won else Color8(165,35,45))
	for y in range(6):
		for x in range(8):
			draw_rect(Rect2(32+x*64,96+y*64,63,63),Color8(35,40,50))
	if not won:
		var food = FOODS[eaten]
		draw_rect(Rect2(44+food.x*64,108+food.y*64,40,40),Color8(245,90,70))
	for i in range(body.size()):
		var p = body[i]
		draw_rect(Rect2(37+p.x*64,101+p.y*64,54,54),Color8(100,240,140) if i == 0 else Color8(45,170,90))
