"""Project-level exam for the Godot agent: 60 small (24 original + 36 added 10-13) 2D/3D projects, each with a contract (node names, variables,
input actions) stated in the prompt so behaviour can be checked automatically through gd_run probes.
Written by Claude -> EXAM ONLY, never training data (Anthropic terms). Writes eval/gd_projects.json.

check: frames, inputs, calls, probes (indexed in order), expect: list of
  {"p": i, "op": "found"} | {"p": i, "op": "eq", "v": value} | {"p": i, "op": "ge"/"le", "v": number}
  {"a": i, "b": j, "op": "ne"}  (value changed)  | {"a": i, "b": j, "op": "inc"/"dec", "axis": "x"/"y"/"z" or None}"""
import json
from pathlib import Path

ACT = ("Define the input actions in project.godot ([input] section) with keyboard events: ")


def P(node, prop, frame):
    return {"frame": frame, "node": node, "prop": prop}


T = []


def task(id_, kind, prompt, frames=180, inputs=(), calls=(), probes=(), expect=()):
    T.append({"id": id_, "kind": kind, "prompt": prompt, "check": {"frames": frames, "inputs": list(inputs),
              "calls": list(calls), "probes": list(probes), "expect": list(expect)}})


# ---------------- 2D ----------------
task("platformer", "2d",
     "Make a small 2D platformer. The main scene root is a Node2D named Main. It contains a CharacterBody2D named Player "
     "(with a CollisionShape2D and a visible Polygon2D or ColorRect body) standing on a StaticBody2D named Floor that has "
     "a wide RectangleShape2D collision. The player falls with gravity, walks left/right and jumps. "
     + ACT + "move_left (A, Left), move_right (D, Right), jump (Space).",
     frames=150, inputs=[{"frame": 40, "action": "move_right", "pressed": True}],
     probes=[P("Player", "position", 35), P("Player", "position", 140), P("Player", "is_on_floor()", 35)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}])
task("shooter2d", "2d",
     "Make a top-down 2D shooter prototype. Main scene root: Node2D named Main with a script that has "
     "`var shots_fired: int = 0`. A CharacterBody2D named Player moves in 8 directions. Pressing the shoot action spawns "
     "a bullet (Area2D created in code or from a bullet scene) that flies upward and frees itself off screen; each shot "
     "increments Main.shots_fired. Allow at most one shot every 0.2 s. "
     + ACT + "up (W), down (S), left (A), right (D), shoot (Space).",
     frames=120, inputs=[{"frame": 20, "action": "shoot", "pressed": True}, {"frame": 100, "action": "shoot", "pressed": False}],
     probes=[P(".", "shots_fired", 10), P(".", "shots_fired", 110)],
     expect=[{"p": 0, "op": "eq", "v": 0}, {"p": 1, "op": "ge", "v": 2}])
task("pong", "2d",
     "Make a Pong game. Main scene root: Node2D named Main. Nodes: LeftPaddle and RightPaddle (CharacterBody2D or "
     "AnimatableBody2D), Ball (CharacterBody2D) that starts moving by itself and bounces off the top/bottom walls and the "
     "paddles, and a Label named ScoreLabel. Main's script has `var left_score: int` and `var right_score: int`. "
     "The left paddle is player-controlled, the right paddle follows the ball. "
     + ACT + "p1_up (W), p1_down (S).",
     frames=120, inputs=[{"frame": 20, "action": "p1_down", "pressed": True}],
     probes=[P("Ball", "position", 5), P("Ball", "position", 60), P("LeftPaddle", "position", 15), P("LeftPaddle", "position", 100),
             P(".", "left_score", 5)],
     expect=[{"a": 0, "b": 1, "op": "ne"}, {"a": 2, "b": 3, "op": "inc", "axis": "y"}, {"p": 4, "op": "eq", "v": 0}])
task("snake", "2d",
     "Make a grid-based Snake game on a 20x15 grid of 32-px cells. Main scene root: Node2D named Main whose script has "
     "`var snake: Array[Vector2i]` (head first, starting length 3) and `var direction: Vector2i` starting as Vector2i.RIGHT. "
     "The snake advances one cell every 0.15 s, eats food to grow, and the game resets on hitting a wall or itself. "
     "Draw it with _draw() or ColorRect nodes. Use the built-in ui_up/ui_down/ui_left/ui_right actions.",
     frames=200, inputs=[{"frame": 60, "action": "ui_down", "pressed": True}, {"frame": 66, "action": "ui_down", "pressed": False}],
     probes=[P(".", "snake.size()", 5), P(".", "snake[0]", 5), P(".", "snake[0]", 55), P(".", "direction", 120)],
     expect=[{"p": 0, "op": "eq", "v": 3}, {"a": 1, "b": 2, "op": "inc", "axis": "x"}, {"p": 3, "op": "eq", "v": "Vector2i(0, 1)"}])
task("breakout", "2d",
     "Make a Breakout game. Main scene root: Node2D named Main whose script has `var bricks_left: int`. Build 5 rows x 8 "
     "columns of bricks in code (StaticBody2D with a collision shape and a ColorRect each) under a Node2D named Bricks, and "
     "set bricks_left to their count. A Paddle (CharacterBody2D) moves left/right; a Ball bounces and destroys bricks, "
     "decrementing bricks_left. " + ACT + "move_left (A, Left), move_right (D, Right).",
     frames=90, inputs=[{"frame": 20, "action": "move_left", "pressed": True}],
     probes=[P(".", "bricks_left", 5), P("Bricks", "get_child_count()", 5), P("Paddle", "position", 15), P("Paddle", "position", 80)],
     expect=[{"p": 0, "op": "eq", "v": 40}, {"p": 1, "op": "eq", "v": 40}, {"a": 2, "b": 3, "op": "dec", "axis": "x"}])
task("clicker", "2d",
     "Make a clicker game UI. Main scene root: Control named Main (full rect) whose script has `var score: int = 0` and "
     "`var per_click: int = 1`. Children: a Button named ClickButton (+per_click to score when pressed), a Button named "
     "UpgradeButton (costs 10 score, doubles per_click, disabled while unaffordable), and a Label named ScoreLabel "
     "always showing \"Score: <score>\".",
     frames=60, calls=[{"frame": 10, "node": "ClickButton", "method": "emit_signal", "args": ["pressed"]},
                       {"frame": 11, "node": "ClickButton", "method": "emit_signal", "args": ["pressed"]}],
     probes=[P(".", "score", 30), P("ScoreLabel", "text", 30), P("UpgradeButton", "disabled", 30)],
     expect=[{"p": 0, "op": "eq", "v": 2}, {"p": 1, "op": "eq", "v": "\"Score: 2\""}, {"p": 2, "op": "eq", "v": True}])
task("countdown", "2d",
     "Make a countdown timer screen. Main scene root: Control named Main whose script has `var time_left: float = 10.0`, "
     "counting down in real time and stopping at 0, with a Label named TimeLabel showing the remaining seconds with one "
     "decimal, and a Button named RestartButton that resets it to 10.",
     frames=150, probes=[P(".", "time_left", 5), P(".", "time_left", 140)],
     expect=[{"a": 0, "b": 1, "op": "dec", "axis": None}, {"p": 1, "op": "ge", "v": 7.0}])
task("health", "2d",
     "Make a health system demo. Main scene root: Node2D named Main. A Node2D named Player has a script with "
     "`var max_health: int = 100`, `var health: int = 100`, `signal health_changed(new_health: int)`, `signal died`, and "
     "`func take_damage(amount: int) -> void` that clamps health at 0 and emits died once at 0. A ProgressBar named "
     "HealthBar (child of Main) updates from health_changed.",
     frames=60, calls=[{"frame": 10, "node": "Player", "method": "take_damage", "args": [30]}],
     probes=[P("Player", "health", 30), P("HealthBar", "value", 30)],
     expect=[{"p": 0, "op": "eq", "v": 70}, {"p": 1, "op": "eq", "v": 70.0}])
task("inventory", "2d",
     "Make an inventory system. Main scene root: Control named Main whose script has `var items: Dictionary = {}` "
     "(item name -> count), `func add_item(item_name: String, count: int) -> void`, `func remove_item(item_name: String, "
     "count: int) -> bool` (false if not enough), and an ItemList named ItemsList that shows \"name x count\" lines and "
     "refreshes after every change.",
     frames=60, calls=[{"frame": 10, "node": ".", "method": "add_item", "args": ["potion", 2]},
                       {"frame": 11, "node": ".", "method": "add_item", "args": ["potion", 3]},
                       {"frame": 12, "node": ".", "method": "remove_item", "args": ["potion", 1]}],
     probes=[P(".", "items", 30), P("ItemsList", "item_count", 30)],
     expect=[{"p": 0, "op": "eq", "v": "{\n\"potion\": 4\n}"}, {"p": 1, "op": "eq", "v": 1}])
task("patrol", "2d",
     "Make an enemy patrol demo. Main scene root: Node2D named Main. A CharacterBody2D named Enemy starts at x=100 and "
     "patrols between x=100 and x=400 at 120 px/s using a small state machine (states PATROL_RIGHT, PATROL_LEFT, WAIT "
     "for 0.5 s at each end). Expose `var state: String` on the Enemy.",
     frames=300, probes=[P("Enemy", "position", 5), P("Enemy", "position", 60), P("Enemy", "position", 290)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}, {"p": 2, "op": "ge_x", "v": 90}, {"p": 2, "op": "le_x", "v": 410}])
task("saveload", "2d",
     "Make a save/load demo. Main scene root: Node named Main whose script has `var high_score: int = 0`, "
     "`func save_game() -> void` writing {\"high_score\": high_score} as JSON to user://save.json, and "
     "`func load_game() -> void` reading it back (keeping 0 if the file is missing or invalid).",
     frames=40, calls=[{"frame": 5, "node": ".", "method": "set", "args": ["high_score", 42]},
                       {"frame": 6, "node": ".", "method": "save_game", "args": []},
                       {"frame": 7, "node": ".", "method": "set", "args": ["high_score", 0]},
                       {"frame": 8, "node": ".", "method": "load_game", "args": []}],
     probes=[P(".", "high_score", 20)], expect=[{"p": 0, "op": "eq", "v": 42}])
task("menu", "2d",
     "Make a two-scene game shell. The main scene res://menu.tscn has a Control root named Menu with a Button named "
     "StartButton and a Button named QuitButton. Pressing StartButton changes the scene to res://game.tscn, whose root "
     "is a Node2D named Game showing a Label \"Playing\". QuitButton quits the game.",
     frames=60, calls=[{"frame": 10, "node": "StartButton", "method": "emit_signal", "args": ["pressed"]}],
     probes=[P(".", "name", 5), P(".", "name", 50)],
     expect=[{"p": 0, "op": "eq", "v": "&\"Menu\""}, {"p": 1, "op": "eq", "v": "&\"Game\""}])

# ---------------- 3D ----------------
task("fps_move", "3d",
     "Make a 3D first-person controller. Main scene root: Node3D named Main with a WorldEnvironment, a DirectionalLight3D, "
     "a StaticBody3D named Floor (40x40 BoxShape3D collision plus a MeshInstance3D), and a CharacterBody3D named Player "
     "(CapsuleShape3D) with a Camera3D child named Head at eye height. The player walks with gravity relative to where "
     "it faces (forward is -Z) and the mouse rotates Player (yaw) and Head (pitch). "
     + ACT + "move_forward (W), move_back (S), move_left (A), move_right (D), jump (Space).",
     frames=150, inputs=[{"frame": 40, "action": "move_forward", "pressed": True}],
     probes=[P("Player", "position", 35), P("Player", "position", 140), P("Head", "position", 5)],
     expect=[{"a": 0, "b": 1, "op": "dec", "axis": "z"}, {"p": 2, "op": "found"}])
task("spin_cube", "3d",
     "Make a 3D showcase scene. Main scene root: Node3D named Main with a MeshInstance3D named Cube (BoxMesh with a "
     "StandardMaterial3D) that spins around Y at 1 rad/s, a Camera3D named Camera orbiting the cube at radius 6 "
     "(one turn every 10 s) always looking at it, and an OmniLight3D.",
     frames=120, probes=[P("Cube", "rotation", 5), P("Cube", "rotation", 100), P("Camera", "position", 5), P("Camera", "position", 100)],
     expect=[{"a": 0, "b": 1, "op": "ne"}, {"a": 2, "b": 3, "op": "ne"}])
task("ball_drop", "3d",
     "Make a 3D physics demo. Main scene root: Node3D named Main. A RigidBody3D named Ball (SphereShape3D, SphereMesh) "
     "starts at y=5 above a StaticBody3D named Floor (large BoxShape3D at y=0) and falls and bounces (physics material "
     "bounce 0.5). Add a Camera3D and a DirectionalLight3D. Pressing the kick action applies an impulse along +X to the ball. "
     + ACT + "kick (K).",
     frames=150, inputs=[{"frame": 90, "action": "kick", "pressed": True}, {"frame": 92, "action": "kick", "pressed": False}],
     probes=[P("Ball", "position", 2), P("Ball", "position", 80), P("Ball", "position", 145)],
     expect=[{"a": 0, "b": 1, "op": "dec", "axis": "y"}, {"p": 1, "op": "ge_y", "v": 0.0}, {"a": 1, "b": 2, "op": "inc", "axis": "x"}])
task("coins3d", "3d",
     "Make a 3D coin-collection level. Main scene root: Node3D named Main whose script has `var coins_total: int` and "
     "`var coins_collected: int = 0`. Spawn 5 coins in code under a Node3D named Coins: each coin is an Area3D with a "
     "CylinderShape3D, a thin CylinderMesh, and spins around Y. Set coins_total to the number spawned. When a body in the "
     "group \"player\" enters a coin, it disappears and coins_collected increases. Include a CharacterBody3D Player in "
     "group \"player\", a floor, a camera and a light.",
     frames=60, probes=[P(".", "coins_total", 10), P("Coins", "get_child_count()", 10), P(".", "coins_collected", 10)],
     expect=[{"p": 0, "op": "eq", "v": 5}, {"p": 1, "op": "eq", "v": 5}, {"p": 2, "op": "eq", "v": 0}])
task("daynight", "3d",
     "Make a 3D day/night cycle. Main scene root: Node3D named Main whose script has `var time_of_day: float` in hours "
     "(0-24, starting at 6.0) advancing 1 hour per second. A DirectionalLight3D named Sun rotates around X with the time "
     "and dims at night; a WorldEnvironment with a ProceduralSkyMaterial sky; some ground and boxes to look at; a camera.",
     frames=150, probes=[P(".", "time_of_day", 5), P(".", "time_of_day", 140), P("Sun", "rotation", 5), P("Sun", "rotation", 140)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": None}, {"a": 2, "b": 3, "op": "ne"}])
task("spawner3d", "3d",
     "Make a 3D enemy spawner. Main scene root: Node3D named Main whose script has `var spawned: int = 0`. Every 0.5 s it "
     "spawns an enemy (a CharacterBody3D with a capsule mesh and collision, created in code or from res://enemy.tscn) at a "
     "random point on a circle of radius 10 under a Node3D named Enemies; enemies walk toward the origin. Cap at 20 "
     "enemies. Include a floor, camera and light.",
     frames=200, probes=[P(".", "spawned", 190), P("Enemies", "get_child_count()", 190)],
     expect=[{"p": 0, "op": "ge", "v": 5}, {"p": 1, "op": "ge", "v": 5}])
task("cam_follow", "3d",
     "Make a third-person 3D follow camera. Main scene root: Node3D named Main with a CharacterBody3D named Player "
     "(box mesh, collision, gravity) on a floor, and a Camera3D named Camera that smoothly follows the player from an "
     "offset of (0, 4, 8) and looks at it. " + ACT + "move_left (A), move_right (D), move_forward (W), move_back (S).",
     frames=150, inputs=[{"frame": 30, "action": "move_right", "pressed": True}],
     probes=[P("Player", "position", 25), P("Player", "position", 140), P("Camera", "position", 25), P("Camera", "position", 140)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}, {"a": 2, "b": 3, "op": "inc", "axis": "x"}])
task("grid3d", "3d",
     "Make a 3D procedural tile grid. Main scene root: Node3D named Main whose script has `var tile_count: int`. In "
     "_ready it builds a 10x10 grid of MeshInstance3D tiles (1x1 PlaneMesh or thin BoxMesh, 0.1 gap) under a Node3D named "
     "Grid, colouring tiles in a checkerboard with two StandardMaterial3D materials, and sets tile_count. Add a camera "
     "looking down at 45 degrees and a light.",
     frames=30, probes=[P(".", "tile_count", 10), P("Grid", "get_child_count()", 10)],
     expect=[{"p": 0, "op": "eq", "v": 100}, {"p": 1, "op": "eq", "v": 100}])
task("projectile3d", "3d",
     "Make a 3D turret. Main scene root: Node3D named Main whose script has `var shots_fired: int = 0`. A Node3D named "
     "Turret aims along -Z. The shoot action fires a projectile (Area3D with a small sphere mesh) from the turret that "
     "moves forward at 20 m/s and frees itself after 2 s; at most 4 shots per second; each shot increments shots_fired. "
     "Include a camera and light. " + ACT + "shoot (Space).",
     frames=120, inputs=[{"frame": 20, "action": "shoot", "pressed": True}, {"frame": 90, "action": "shoot", "pressed": False}],
     probes=[P(".", "shots_fired", 10), P(".", "shots_fired", 110)],
     expect=[{"p": 0, "op": "eq", "v": 0}, {"p": 1, "op": "ge", "v": 2}])
task("vehicle3d", "3d",
     "Make a simple 3D arcade car. Main scene root: Node3D named Main with a floor and a CharacterBody3D named Car (box "
     "body mesh, collision) with `var speed: float`. Accelerate/brake changes speed (max 20, friction slows it), steering "
     "rotates the car around Y only while moving, and the car moves along its local -Z. A Camera3D follows behind. "
     + ACT + "accelerate (W, Up), brake (S, Down), steer_left (A, Left), steer_right (D, Right).",
     frames=150, inputs=[{"frame": 20, "action": "accelerate", "pressed": True}],
     probes=[P("Car", "speed", 10), P("Car", "speed", 120), P("Car", "position", 15), P("Car", "position", 140)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": None}, {"a": 2, "b": 3, "op": "ne"}])
task("doors3d", "3d",
     "Make a 3D interactable door. Main scene root: Node3D named Main. A Node3D named Door (hinge) holds a door mesh and "
     "collision; it has `var is_open: bool = false` and `func toggle() -> void` that tweens its rotation.y between 0 and "
     "90 degrees over 0.5 s. Pressing the interact action toggles the door. Add floor, walls, camera and light. "
     + ACT + "interact (E).",
     frames=120, inputs=[{"frame": 20, "action": "interact", "pressed": True}, {"frame": 22, "action": "interact", "pressed": False}],
     probes=[P("Door", "is_open", 10), P("Door", "is_open", 100), P("Door", "rotation", 10), P("Door", "rotation", 100)],
     expect=[{"p": 0, "op": "eq", "v": False}, {"p": 1, "op": "eq", "v": True}, {"a": 2, "b": 3, "op": "ne"}])
task("waves3d", "3d",
     "Make a 3D wave survival manager. Main scene root: Node3D named Main whose script has `var wave: int = 0`, "
     "`var enemies_alive: int = 0`, `func start_next_wave() -> void` (wave += 1, spawns wave * 3 enemies under a Node3D "
     "named Enemies and sets enemies_alive), and starts wave 1 automatically after 1 second. Enemies are simple "
     "MeshInstance3D-based Node3D scenes created in code. Include floor, camera and light.",
     frames=120, probes=[P(".", "wave", 30), P(".", "wave", 110), P(".", "enemies_alive", 110), P("Enemies", "get_child_count()", 110)],
     expect=[{"p": 0, "op": "eq", "v": 0}, {"p": 1, "op": "eq", "v": 1}, {"p": 2, "op": "eq", "v": 3}, {"p": 3, "op": "eq", "v": 3}])

# ---------------- expansion (10-13): 18 more 2D + 18 more 3D, so one task is 1.7% instead of 4% ----------------
# Every node named in a contract is a direct child of the main scene root unless a path is given.
def G(prop, frame):
    return P(".", prop, frame)


# ---- 2D ----
task("tween_move", "2d",
     "Make a tween demo. Main scene root: Node2D named Main. A child Node2D named Box (with a ColorRect child so it is "
     "visible) starts at position (100, 200). Main's script has `func move_to(x: float, y: float) -> void` that tweens "
     "Box.position to (x, y) over 0.5 seconds, killing any tween still running.",
     frames=80, calls=[{"frame": 10, "node": ".", "method": "move_to", "args": [300, 200]}],
     probes=[P("Box", "position", 5), P("Box", "position", 14), P("Box", "position", 70)],
     expect=[{"p": 0, "op": "le_x", "v": 100.5}, {"p": 1, "op": "le_x", "v": 299}, {"p": 2, "op": "ge_x", "v": 299.5},
             {"p": 2, "op": "le_x", "v": 300.5}])
task("timer_spawn2d", "2d",
     "Make a timed spawner. Main scene root: Node2D named Main whose script has `var spawned: int = 0`. A child Timer "
     "named SpawnTimer (wait_time 0.25, autostart) adds a 16x16 ColorRect at a random position inside 640x360 under a "
     "child Node2D named Spawned on every timeout and increments spawned. Stop spawning after 20.",
     frames=120, probes=[G("spawned", 110), P("Spawned", "get_child_count()", 110)],
     expect=[{"p": 0, "op": "ge", "v": 5}, {"p": 0, "op": "le", "v": 20}, {"p": 1, "op": "ge", "v": 5}])
task("dialogue", "2d",
     "Make a dialogue box. Main scene root: Control named Main whose script has "
     "`var lines: Array[String] = [\"Hello, traveler.\", \"The bridge is out.\", \"Take the river path.\"]`, "
     "`var index: int = 0`, `var finished: bool = false` and `func advance() -> void`. A child Label named DialogueLabel "
     "shows lines[index] from the start. advance() moves to the next line; calling it on the last line sets finished "
     "to true and hides DialogueLabel. The ui_accept action also calls advance().",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "advance", "args": []},
                       {"frame": 11, "node": ".", "method": "advance", "args": []},
                       {"frame": 20, "node": ".", "method": "advance", "args": []}],
     probes=[P("DialogueLabel", "text", 5), P("DialogueLabel", "text", 15), G("finished", 30),
             P("DialogueLabel", "visible", 30)],
     expect=[{"p": 0, "op": "eq", "v": "\"Hello, traveler.\""}, {"p": 1, "op": "eq", "v": "\"Take the river path.\""},
             {"p": 2, "op": "eq", "v": True}, {"p": 3, "op": "eq", "v": False}])
task("stamina", "2d",
     "Make a stamina system. Main scene root: Node2D named Main. A child Node2D named Player has a script with "
     "`var stamina: float = 100.0`: while the sprint action is held stamina drains at 25 per second, otherwise it "
     "regenerates at 10 per second, always clamped to 0..100. A child ProgressBar named StaminaBar shows it. "
     + ACT + "sprint (Shift).",
     frames=150, inputs=[{"frame": 10, "action": "sprint", "pressed": True}, {"frame": 70, "action": "sprint", "pressed": False}],
     probes=[P("Player", "stamina", 5), P("Player", "stamina", 70), P("Player", "stamina", 140)],
     expect=[{"p": 0, "op": "ge", "v": 99.9}, {"p": 1, "op": "le", "v": 80}, {"p": 1, "op": "ge", "v": 70},
             {"a": 1, "b": 2, "op": "inc", "axis": None}])
task("turns", "2d",
     "Make a two-player turn manager. Main scene root: Node named Main whose script has `var turn: int = 1`, "
     "`var current_player: int = 0` (0 or 1), `signal turn_started(player: int)` and `func end_turn() -> void`, which "
     "switches current_player and increases turn each time play returns to player 0, then emits turn_started. "
     "A child Label named TurnLabel shows \"Turn <turn> - Player <current_player + 1>\".",
     frames=40, calls=[{"frame": 10 + i, "node": ".", "method": "end_turn", "args": []} for i in range(3)],
     probes=[G("turn", 30), G("current_player", 30), P("TurnLabel", "text", 30)],
     expect=[{"p": 0, "op": "eq", "v": 2}, {"p": 1, "op": "eq", "v": 1}, {"p": 2, "op": "eq", "v": "\"Turn 2 - Player 2\""}])
task("combo", "2d",
     "Make a combo scorer. Main scene root: Node named Main whose script has `var score: int = 0`, `var combo: int = 0`, "
     "`func hit() -> void` (combo += 1, then score += 10 * combo) and `func miss() -> void` (combo = 0). A child Label "
     "named ComboLabel shows \"x<combo>\" and is hidden while combo is 0.",
     frames=40, calls=[{"frame": 10 + i, "node": ".", "method": m, "args": []}
                       for i, m in enumerate(["hit", "hit", "hit", "miss", "hit"])],
     probes=[G("score", 30), G("combo", 30), P("ComboLabel", "text", 30)],
     expect=[{"p": 0, "op": "eq", "v": 70}, {"p": 1, "op": "eq", "v": 1}, {"p": 2, "op": "eq", "v": "\"x1\""}])
task("scroller", "2d",
     "Make an endless scrolling background. Main scene root: Node2D named Main. A child Node2D named Background holds two "
     "1280x720 ColorRects side by side and scrolls left at 100 px/s; when its x reaches -1280 it jumps back by +1280 so "
     "the loop is seamless.",
     frames=80, probes=[P("Background", "position", 5), P("Background", "position", 65)],
     expect=[{"a": 0, "b": 1, "op": "dec", "axis": "x"}, {"p": 1, "op": "ge_x", "v": -1280}])
task("chaser", "2d",
     "Make a chasing enemy. Main scene root: Node2D named Main. A child Node2D named Target sits at (500, 400). A child "
     "CharacterBody2D named Enemy starts at (100, 100) and moves straight toward Target at 150 px/s with move_and_slide, "
     "stopping when within 5 px.",
     frames=260, probes=[P("Enemy", "position", 5), P("Enemy", "position", 60),
                         P("Enemy", "position.distance_to(Vector2(500, 400))", 250)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}, {"a": 0, "b": 1, "op": "inc", "axis": "y"},
             {"p": 2, "op": "le", "v": 20}])
task("shop", "2d",
     "Make a shop. Main scene root: Control named Main whose script has `var gold: int = 50`, "
     "`var prices: Dictionary = {\"sword\": 30, \"shield\": 25, \"potion\": 5}`, `var owned: Array[String] = []` and "
     "`func buy(item: String) -> bool` that returns false (changing nothing) for unknown or unaffordable items, otherwise "
     "subtracts the price, appends the item and returns true. A child Label named GoldLabel shows \"Gold: <gold>\".",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "buy", "args": ["sword"]},
                       {"frame": 11, "node": ".", "method": "buy", "args": ["shield"]},
                       {"frame": 12, "node": ".", "method": "buy", "args": ["potion"]}],
     probes=[G("gold", 30), G("owned.size()", 30), P("GoldLabel", "text", 30)],
     expect=[{"p": 0, "op": "eq", "v": 15}, {"p": 1, "op": "eq", "v": 2}, {"p": 2, "op": "eq", "v": "\"Gold: 15\""}])
task("bullet_ring", "2d",
     "Make a bullet-hell emitter. Main scene root: Node2D named Main whose script has `var waves_fired: int = 0`. "
     "0.5 s after start and then every 1 s, it fires a ring of 12 bullets from (320, 180) under a child Node2D named "
     "Bullets; each bullet is an Area2D (small circle collision + visual) moving outward at 150 px/s that frees itself "
     "after 2 s. Each ring increments waves_fired.",
     frames=150, probes=[G("waves_fired", 20), G("waves_fired", 140), P("Bullets", "get_child_count()", 140)],
     expect=[{"p": 0, "op": "eq", "v": 0}, {"p": 1, "op": "ge", "v": 2}, {"p": 2, "op": "ge", "v": 12}])
task("pause", "2d",
     "Make a pause system. Main scene root: Node2D named Main (process_mode Always) that toggles get_tree().paused on "
     "the pause action and shows/hides a child CanvasLayer named PauseMenu (with a \"Paused\" Label), hidden at start. "
     "A child Node2D named Mover moves right at 100 px/s and stops while paused. " + ACT + "pause (P, Escape).",
     frames=140, inputs=[{"frame": 60, "action": "pause", "pressed": True}, {"frame": 62, "action": "pause", "pressed": False}],
     probes=[P("PauseMenu", "visible", 5), P("Mover", "position", 5), P("Mover", "position", 50), G("get_tree().paused", 100),
             P("PauseMenu", "visible", 100)],
     expect=[{"p": 0, "op": "eq", "v": False}, {"a": 1, "b": 2, "op": "inc", "axis": "x"}, {"p": 3, "op": "eq", "v": True},
             {"p": 4, "op": "eq", "v": True}])
task("camera2d", "2d",
     "Make a side-scrolling camera. Main scene root: Node2D named Main with a StaticBody2D floor, a CharacterBody2D named "
     "Player that walks with gravity, and a Camera2D named Camera that is a direct child of Main (not of the Player) and "
     "follows the player's position every frame with smoothing. " + ACT + "move_left (A), move_right (D).",
     frames=150, inputs=[{"frame": 30, "action": "move_right", "pressed": True}],
     probes=[P("Player", "position", 25), P("Player", "position", 140), P("Camera", "position", 25), P("Camera", "position", 140)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}, {"a": 2, "b": 3, "op": "inc", "axis": "x"}])
task("event_bus", "2d",
     "Make a global event bus. Register an autoload named Events (res://events.gd, extends Node) declaring "
     "`signal coin_collected(value: int)`. Main scene root: Node2D named Main whose script has `var total: int = 0` and adds "
     "each emitted value to total. A child Node2D named Coin has `func collect() -> void` that emits "
     "Events.coin_collected with 5.",
     frames=40, calls=[{"frame": 10, "node": "Coin", "method": "collect", "args": []},
                       {"frame": 11, "node": "Coin", "method": "collect", "args": []}],
     probes=[G("total", 30)], expect=[{"p": 0, "op": "eq", "v": 10}])
task("traffic_light", "2d",
     "Make a traffic light. Main scene root: Node2D named Main. A child Node2D named TrafficLight has "
     "`var state: String = \"GREEN\"` and cycles GREEN for 1.0 s, then YELLOW for 0.5 s, then RED for 1.0 s, then GREEN "
     "again, drawing a coloured circle for the current state.",
     frames=130, probes=[P("TrafficLight", "state", 30), P("TrafficLight", "state", 75), P("TrafficLight", "state", 120)],
     expect=[{"p": 0, "op": "eq", "v": "\"GREEN\""}, {"p": 1, "op": "eq", "v": "\"YELLOW\""}, {"p": 2, "op": "eq", "v": "\"RED\""}])
task("resource_item", "2d",
     "Make a custom Resource. res://item_data.gd declares `class_name ItemData extends Resource` with "
     "`@export var item_name: String` and `@export var damage: int`. Main scene root: Node named Main whose script has "
     "`var weapon: ItemData`, created in _ready with item_name \"Bronze Sword\" and damage 12, and "
     "`func upgrade() -> void` that adds 3 damage.",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "upgrade", "args": []},
                       {"frame": 11, "node": ".", "method": "upgrade", "args": []}],
     probes=[G("weapon.damage", 30), G("weapon.item_name", 30), G("weapon.get_script().resource_path", 30)],
     expect=[{"p": 0, "op": "eq", "v": 18}, {"p": 1, "op": "eq", "v": "\"Bronze Sword\""},
             {"p": 2, "op": "eq", "v": "\"res://item_data.gd\""}])
task("dice", "2d",
     "Make a dice roller. Main scene root: Control named Main whose script has `var rolls: Array[int] = []`, "
     "`func roll() -> int` (uniform 1..6, appended to rolls) and `func roll_many(n: int) -> void`. A child Label named "
     "LastRoll shows the latest roll and a child Button named RollButton rolls once.",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "roll_many", "args": [20]}],
     probes=[G("rolls.size()", 30), G("rolls.min()", 30), G("rolls.max()", 30)],
     expect=[{"p": 0, "op": "eq", "v": 20}, {"p": 1, "op": "ge", "v": 1}, {"p": 2, "op": "le", "v": 6}])
task("undo", "2d",
     "Make an undo stack. Main scene root: Node named Main whose script has `var value: int = 0`, "
     "`var history: Array[int] = []`, `func apply(delta: int) -> void` (push the current value onto history, then add "
     "delta) and `func undo() -> void` (restore the last pushed value; do nothing when history is empty).",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "apply", "args": [5]},
                       {"frame": 11, "node": ".", "method": "apply", "args": [3]},
                       {"frame": 12, "node": ".", "method": "undo", "args": []}],
     probes=[G("value", 30), G("history.size()", 30)],
     expect=[{"p": 0, "op": "eq", "v": 5}, {"p": 1, "op": "eq", "v": 1}])
task("volume_slider", "2d",
     "Make a settings screen. Main scene root: Control named Main whose script has `var volume: float = 80.0`. A child "
     "HSlider named VolumeSlider (0..100, starts at 80) updates volume through its value_changed signal, and a child "
     "Label named VolumeLabel shows \"Volume: <volume as integer>\".",
     frames=40, calls=[{"frame": 10, "node": "VolumeSlider", "method": "set_value", "args": [40]}],
     probes=[P("VolumeLabel", "text", 5), G("volume", 30), P("VolumeLabel", "text", 30)],
     expect=[{"p": 0, "op": "eq", "v": "\"Volume: 80\""}, {"p": 1, "op": "eq", "v": 40.0}, {"p": 2, "op": "eq", "v": "\"Volume: 40\""}])

# ---- 3D ----
task("elevator", "3d",
     "Make a 3D elevator. Main scene root: Node3D named Main with a floor, camera and light. A child AnimatableBody3D "
     "named Platform (box mesh + collision) starts at y=0 and moves up to y=5 over 2 s, then back down over 2 s, "
     "looping forever (use a looping Tween).",
     frames=130, probes=[P("Platform", "position", 3), P("Platform", "position", 60), P("Platform", "position", 125)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "y"}, {"p": 1, "op": "le_y", "v": 5.01}, {"a": 1, "b": 2, "op": "inc", "axis": "y"}])
task("raycast3d", "3d",
     "Make a 3D raycast probe. Main scene root: Node3D named Main whose script has `var hit_name: String = \"\"`. A child "
     "StaticBody3D named Target (box mesh + BoxShape3D) sits at the origin. A child RayCast3D named Ray at (0, 5, 0) "
     "points straight down 10 m; every physics frame Main sets hit_name to the name of the collider or \"\" when nothing "
     "is hit. Add a camera and light.",
     frames=40, probes=[G("hit_name", 30)], expect=[{"p": 0, "op": "eq", "v": "\"Target\""}])
task("pickup3d", "3d",
     "Make a 3D health pickup. Main scene root: Node3D named Main. A child CharacterBody3D named Player (capsule mesh + "
     "collision, in group \"player\") has `var health: int = 50` and moves along +X at 3 m/s by itself without gravity, "
     "starting at the origin. A child Area3D named Pickup (sphere shape + mesh) sits at (3, 0, 0); when a body in group "
     "\"player\" enters it, that body's health increases by 25 and the pickup frees itself. Add a camera and light.",
     frames=120, probes=[P("Player", "health", 5), P("Player", "health", 110), G("get_node_or_null(\"Pickup\") == null", 110)],
     expect=[{"p": 0, "op": "eq", "v": 50}, {"p": 1, "op": "eq", "v": 75}, {"p": 2, "op": "eq", "v": True}])
task("turret_aim", "3d",
     "Make a 3D aiming turret. Main scene root: Node3D named Main. A child Node3D named Target (small sphere mesh) moves "
     "along X as x = 5 * sin(time), z = -8. A child Node3D named Turret at the origin (box body + barrel along -Z) turns to "
     "face Target every frame with look_at. Add a camera and light.",
     frames=100, probes=[P("Turret", "rotation", 10), P("Turret", "rotation", 90), P("Target", "position", 90)],
     expect=[{"a": 0, "b": 1, "op": "ne"}, {"p": 2, "op": "le_z", "v": -7.9}])
task("terrain", "3d",
     "Make a procedural 3D terrain. Main scene root: Node3D named Main whose script has `var vertex_count: int`. In "
     "_ready it builds a 32x32-quad height-field mesh with SurfaceTool (heights from FastNoiseLite, normals generated) "
     "and assigns it to a child MeshInstance3D named Terrain; vertex_count is the number of vertices added. Add a camera "
     "and a DirectionalLight3D.",
     frames=30, probes=[G("vertex_count", 10), P("Terrain", "mesh != null", 10), P("Terrain", "mesh.get_surface_count()", 10)],
     expect=[{"p": 0, "op": "ge", "v": 1024}, {"p": 1, "op": "eq", "v": True}, {"p": 2, "op": "eq", "v": 1}])
task("forest", "3d",
     "Make a 3D forest with instancing. Main scene root: Node3D named Main with a ground plane, camera and light. A child "
     "MultiMeshInstance3D named Trees draws 200 instances of a CylinderMesh (or ConeMesh) placed at random positions "
     "inside a 50x50 area, built in code in _ready.",
     frames=30, probes=[P("Trees", "multimesh.instance_count", 10), P("Trees", "multimesh.mesh != null", 10)],
     expect=[{"p": 0, "op": "eq", "v": 200}, {"p": 1, "op": "eq", "v": True}])
task("path_cart", "3d",
     "Make a 3D rail cart. Main scene root: Node3D named Main. A child Path3D named Track gets a Curve3D built in code: a "
     "closed square loop with corners (0,0,0), (10,0,0), (10,0,10), (0,0,10). A PathFollow3D named Cart (child of Track, "
     "with a box mesh) advances its progress at 4 m/s and loops. Add a camera and light.",
     frames=100, probes=[P("Track/Cart", "progress", 5), P("Track/Cart", "progress", 90), P("Track", "curve.get_baked_length()", 5)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": None}, {"p": 2, "op": "ge", "v": 29.5}])
task("key_door", "3d",
     "Make a 3D key-and-door puzzle. Main scene root: Node3D named Main whose script has `var has_key: bool = false`, "
     "`var failed_attempts: int = 0` and `func pick_key() -> void`. A child Node3D named Door (box mesh) has "
     "`var opened: bool = false` and `func try_open() -> bool`: it asks Main whether the key was picked up; without it, "
     "failed_attempts increases and it returns false; with it, the door opens (rises 3 m) and returns true. Add floor, "
     "camera and light.",
     frames=60, calls=[{"frame": 10, "node": "Door", "method": "try_open", "args": []},
                       {"frame": 11, "node": ".", "method": "pick_key", "args": []},
                       {"frame": 12, "node": "Door", "method": "try_open", "args": []}],
     probes=[P("Door", "opened", 50), G("failed_attempts", 50), G("has_key", 50)],
     expect=[{"p": 0, "op": "eq", "v": True}, {"p": 1, "op": "eq", "v": 1}, {"p": 2, "op": "eq", "v": True}])
task("crate_push", "3d",
     "Make a 3D crate push. Main scene root: Node3D named Main with a StaticBody3D floor (large box at y=0), camera and "
     "light. A child RigidBody3D named Crate (1 m box) rests on the floor; while the push action is held a central force "
     "of 40 N along +X is applied to it. " + ACT + "push (F).",
     frames=150, inputs=[{"frame": 40, "action": "push", "pressed": True}],
     probes=[P("Crate", "position", 35), P("Crate", "position", 140)],
     expect=[{"a": 0, "b": 1, "op": "inc", "axis": "x"}, {"p": 1, "op": "ge_y", "v": 0.0}])
task("torch", "3d",
     "Make a flickering torch. Main scene root: Node3D named Main with a floor and camera. A child OmniLight3D named Torch "
     "changes light_energy every 0.1 s to a random value between 0.5 and 1.5, smoothly interpolating between values.",
     frames=100, probes=[P("Torch", "light_energy", 30), P("Torch", "light_energy", 60), P("Torch", "light_energy", 90)],
     expect=[{"a": 0, "b": 1, "op": "ne"}, {"p": 1, "op": "ge", "v": 0.5}, {"p": 1, "op": "le", "v": 1.5}])
task("grid_step3d", "3d",
     "Make 3D grid movement. Main scene root: Node3D named Main with a floor, camera and light. A child Node3D named Player "
     "(box mesh) has `var grid_pos: Vector2i = Vector2i.ZERO`; each press of a move action steps exactly one 1 m cell "
     "(x for left/right, z for up/down), tweening position over 0.2 s; presses during a step are ignored. "
     + ACT + "move_left (A), move_right (D), move_up (W), move_down (S).",
     frames=80, inputs=[{"frame": 10, "action": "move_right", "pressed": True}, {"frame": 12, "action": "move_right", "pressed": False}],
     probes=[P("Player", "grid_pos", 60), P("Player", "position", 60)],
     expect=[{"p": 0, "op": "eq", "v": "Vector2i(1, 0)"}, {"p": 1, "op": "ge_x", "v": 0.99}, {"p": 1, "op": "le_x", "v": 1.01}])
task("zoom3d", "3d",
     "Make a zoomable 3D camera. Main scene root: Node3D named Main with some boxes and a light. A child Camera3D named "
     "Camera starts with fov 75; while zoom_in is held fov decreases at 30 degrees per second, while zoom_out is held it "
     "increases at the same rate, clamped to 30..90. " + ACT + "zoom_in (Q), zoom_out (E).",
     frames=100, inputs=[{"frame": 10, "action": "zoom_in", "pressed": True}, {"frame": 70, "action": "zoom_in", "pressed": False}],
     probes=[P("Camera", "fov", 5), P("Camera", "fov", 80)],
     expect=[{"p": 0, "op": "ge", "v": 74.9}, {"p": 1, "op": "le", "v": 60}, {"p": 1, "op": "ge", "v": 30}])
task("falling_boxes", "3d",
     "Make a 3D falling-box spawner. Main scene root: Node3D named Main whose script has `var spawned: int = 0`, with a "
     "large StaticBody3D floor at y=0, camera and light. Every 0.3 s it spawns a RigidBody3D box (mesh + collision) at a "
     "random x/z within 4 m and y=10 under a child Node3D named Boxes; boxes that fall below y=-5 free themselves.",
     frames=150, probes=[G("spawned", 140), P("Boxes", "get_child_count()", 140)],
     expect=[{"p": 0, "op": "ge", "v": 6}, {"p": 1, "op": "ge", "v": 6}])
task("checkpoint", "3d",
     "Make a 3D checkpoint system. Main scene root: Node3D named Main whose script has "
     "`var checkpoints: Array[Vector3] = [Vector3(0, 0, 0), Vector3(10, 0, 0), Vector3(20, 0, 5)]`, "
     "`var current: int = 0`, `func reach_checkpoint(index: int) -> void` (only ever moves current forward) and "
     "`func respawn() -> void` that puts the child Node3D named Player (capsule mesh, no physics) at the current "
     "checkpoint. Add floor, camera and light.",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "reach_checkpoint", "args": [2]},
                       {"frame": 11, "node": ".", "method": "reach_checkpoint", "args": [1]},
                       {"frame": 12, "node": ".", "method": "respawn", "args": []}],
     probes=[G("current", 30), P("Player", "position", 30)],
     expect=[{"p": 0, "op": "eq", "v": 2}, {"p": 1, "op": "ge_x", "v": 19.99}, {"p": 1, "op": "ge_z", "v": 4.99},
             {"p": 1, "op": "le_z", "v": 5.01}])
task("label3d_score", "3d",
     "Make a 3D floating score. Main scene root: Node3D named Main whose script has `var score: int = 0` and "
     "`func add_score(points: int) -> void`. A child Label3D named ScoreLabel (billboard) floats at (0, 2, 0) showing "
     "\"Score: <score>\". Add a camera and light.",
     frames=40, calls=[{"frame": 10, "node": ".", "method": "add_score", "args": [15]}],
     probes=[P("ScoreLabel", "text", 5), P("ScoreLabel", "text", 30), P("ScoreLabel", "billboard", 30)],
     expect=[{"p": 0, "op": "eq", "v": "\"Score: 0\""}, {"p": 1, "op": "eq", "v": "\"Score: 15\""}, {"p": 2, "op": "ge", "v": 1}])
task("anim_bob", "3d",
     "Make a code-built animation. Main scene root: Node3D named Main with a camera and light. A child MeshInstance3D "
     "named Cube (BoxMesh) bobs up and down: in _ready, build an Animation named \"bob\" (1 s, looping, track on "
     "Cube's position:y going 0 -> 1 -> 0) in an AnimationLibrary on a child AnimationPlayer named Anim, and play it.",
     frames=60, probes=[P("Anim", "is_playing()", 10), P("Cube", "position", 2), P("Cube", "position", 30),
                        P("Anim", "current_animation", 10)],
     expect=[{"p": 0, "op": "eq", "v": True}, {"a": 1, "b": 2, "op": "inc", "axis": "y"}, {"p": 3, "op": "eq", "v": "&\"bob\""}])
task("solar", "3d",
     "Make a 3D solar system. Main scene root: Node3D named Main with a camera and an OmniLight3D. A child Node3D named Sun "
     "(sphere mesh) sits at the origin. A child Node3D named Planet orbits the origin in the XZ plane at radius 8, one "
     "orbit every 4 s, and a Node3D named Moon (child of Planet) orbits the planet at radius 2.",
     frames=100, probes=[P("Planet", "position", 10), P("Planet", "position", 70), P("Planet", "position.length()", 70),
                         P("Planet/Moon", "position.length()", 70)],
     expect=[{"a": 0, "b": 1, "op": "ne"}, {"p": 2, "op": "ge", "v": 7.9}, {"p": 2, "op": "le", "v": 8.1},
             {"p": 3, "op": "ge", "v": 1.9}, {"p": 3, "op": "le", "v": 2.1}])
task("explode", "3d",
     "Make a 3D explosion. Main scene root: Node3D named Main with a large StaticBody3D floor at y=0, camera and light, "
     "and `func explode() -> void`. Under a child Node3D named Crates, place 8 RigidBody3D crates named Crate0..Crate7 "
     "on a circle of radius 2 around the origin at y=0.5 (Crate0 at (2, 0.5, 0), going counter-clockwise). explode() "
     "applies an impulse of 8 to each crate pointing away from the origin and slightly up.",
     frames=120, calls=[{"frame": 30, "node": ".", "method": "explode", "args": []}],
     probes=[P("Crates", "get_child_count()", 20), P("Crates/Crate0", "position", 25), P("Crates/Crate0", "position", 90)],
     expect=[{"p": 0, "op": "eq", "v": 8}, {"a": 1, "b": 2, "op": "inc", "axis": "x"}])

assert len(T) == 60 and len({t["id"] for t in T}) == 60
Path(__file__).with_name("gd_projects.json").write_text(json.dumps(T, ensure_ascii=False, indent=1))
print(len(T), "tasks:", sum(t["kind"] == "2d" for t in T), "2D,", sum(t["kind"] == "3d" for t in T), "3D")
