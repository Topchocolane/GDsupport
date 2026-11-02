"""Fixtures for gd_run.py: each case has a known expected outcome. Run: .venv/bin/python tests/test_gd_run.py"""
import sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1]))
from gd_run import run_project, run_many

PG = '''config_version=5
[application]
config/name="t"
run/main_scene="res://main.tscn"
'''
def scene(script, root_type):
    return f'''[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://{script}" id="1"]
[node name="Main" type="{root_type}"]
script = ExtResource("1")
'''
MOVE = '''extends CharacterBody2D
func _physics_process(_d: float) -> void:
	velocity = Vector2(Input.get_axis("ui_left", "ui_right") * 200.0, 0.0)
	move_and_slide()
'''
BAD_RUNTIME = '''extends Node2D
func _ready() -> void:
	$Missing.visible = false
'''
SPIN3D = '''extends Node3D
var mesh: MeshInstance3D
func _ready() -> void:
	var cam := Camera3D.new()
	cam.position = Vector3(0, 0, 5)
	add_child(cam)
	mesh = MeshInstance3D.new()
	mesh.mesh = BoxMesh.new()
	add_child(mesh)
func _process(delta: float) -> void:
	mesh.rotate_y(delta)
'''
PARSE = '''extends Node
func _ready() -> void
	print("x")
'''
LOOP = '''extends Node
func _ready() -> void:
	while true:
		pass
'''
cases = [
  ("2d move", dict(files={"project.godot": PG, "main.tscn": scene("p.gd", "CharacterBody2D"), "p.gd": MOVE}, frames=60,
                   inputs=[{"frame": 10, "action": "ui_right", "pressed": True}],
                   probes=[{"frame": 5, "node": ".", "prop": "position"}, {"frame": 50, "node": ".", "prop": "position"}]), True),
  ("runtime err", dict(files={"project.godot": PG, "main.tscn": scene("b.gd", "Node2D"), "b.gd": BAD_RUNTIME}, frames=30), False),
  ("3d spin", dict(files={"project.godot": PG, "main.tscn": scene("s.gd", "Node3D"), "s.gd": SPIN3D}, frames=60), True),
  ("parse err", dict(files={"project.godot": PG, "main.tscn": scene("e.gd", "Node"), "e.gd": PARSE}, frames=30), False),
  ("inf loop", dict(files={"project.godot": PG, "main.tscn": scene("l.gd", "Node"), "l.gd": LOOP}, frames=30, timeout=25), False),
  ("no main", dict(files={"project.godot": 'config_version=5\n', "a.gd": "extends Node\n"}), False),
]
t0 = time.time()
res = run_many([c[1] for c in cases])
bad = 0
for (name, _, want), r in zip(cases, res):
    flag = "PASS" if r["ok"] == want else "FAIL"
    bad += flag == "FAIL"
    print(f"{flag} {name:12s} ok={r['ok']} stage={r['stage']} frames={r['frames']} timeout={r['timed_out']} "
          f"errors={[e[:110] for e in r['errors'][:2]]} probes={[p['value'] for p in r['probes']]}")
print(f"{len(cases) - bad}/{len(cases)} as expected, {time.time() - t0:.1f}s")
sys.exit(bad)
