"""Run a whole Godot 4.6 project headless and report what happened: the runtime check for project-level work.

run_project(files, frames=180, inputs=(), probes=(), timeout=120) -> dict
  files   {res-relative path: text}  must include project.godot with run/main_scene (2D or 3D)
  inputs  [{"frame": 30, "action": "ui_right", "pressed": True}]   or "key": "SPACE" instead of "action"
  probes  [{"frame": 60, "node": "Player", "prop": "position"}]    node path relative to the current scene
  calls   [{"frame": 20, "node": "Button", "method": "emit_signal", "args": ["pressed"]}]
Returns {ok, stage, errors, warnings, frames, exit_code, timed_out, probes, scene, nodes}
  ok = imported, main scene loaded, ran all frames, no errors.  stage = where it stopped:
  "files" | "import" | "load" | "run" | "done".

The project runs inside sandbox-exec (no network; writes only to its temp copy and Godot's caches),
because model-written projects are untrusted code. A hidden autoload (__harness) drives frames,
inputs and probes; it is added to a copy of project.godot, never to the files the model wrote."""
import json, os, re, shutil, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
GODOT = os.environ.get("GODOT", str(HOME / "apps/Godot.app/Contents/MacOS/Godot"))  # Godot 4.6.3 binary

HARNESS = r'''extends Node
# Injected by gd_run.py. Drives the run, then quits. Output lines start with "HARNESS ".
var _cfg := {}
var _frame := 0

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var f := FileAccess.open("res://__harness.json", FileAccess.READ)
	_cfg = JSON.parse_string(f.get_as_text())
	print("HARNESS START")

func _physics_process(_delta: float) -> void:
	_frame += 1
	for ev in _cfg.get("inputs", []):
		if int(ev["frame"]) == _frame:
			_send(ev)
	for c in _cfg.get("calls", []):
		if int(c["frame"]) == _frame:
			_call(c)
	for pr in _cfg.get("probes", []):
		if int(pr["frame"]) == _frame:
			_probe(pr)
	if _frame == 1:
		var cs := get_tree().current_scene
		print("HARNESS SCENE ", cs.name if cs else "<none>")
	if _frame >= int(_cfg.get("frames", 180)):
		if _cfg.get("tree", false) and get_tree().current_scene:
			var arr: Array = []
			_tree(get_tree().current_scene, get_tree().current_scene, 0, arr)
			print("HARNESS TREE ", JSON.stringify(arr))
		print("HARNESS NODES ", _count(get_tree().root))
		print("HARNESS DONE ", _frame)
		get_tree().quit()

func _send(ev: Dictionary) -> void:
	var pressed: bool = ev.get("pressed", true)
	if ev.has("action"):
		if not InputMap.has_action(ev["action"]):
			print("HARNESS NOACTION ", ev["action"])
			return
		# like a real keyboard: send the action's first bound key (games often read event.physical_keycode);
		# an InputEventAction only when no key is bound
		var a: InputEvent = null
		for e in InputMap.action_get_events(ev["action"]):
			if e is InputEventKey:
				a = e.duplicate()
				break
		if a == null:
			a = InputEventAction.new()
			a.action = ev["action"]
		a.pressed = pressed
		Input.parse_input_event(a)
		if pressed:
			Input.action_press(ev["action"])
		else:
			Input.action_release(ev["action"])
	elif ev.has("key"):
		var k := InputEventKey.new()
		k.keycode = OS.find_keycode_from_string(ev["key"])
		k.physical_keycode = k.keycode
		k.pressed = pressed
		Input.parse_input_event(k)

func _find(cs: Node, path: String) -> Node:
	# paths are relative to the main scene root; also accept the root's own name as a prefix ("Main", "Main/Player")
	if cs == null:
		return null
	if path == String(cs.name):
		return cs
	if path.begins_with(String(cs.name) + "/"):
		path = path.substr(String(cs.name).length() + 1)
	return cs.get_node_or_null(NodePath(path))

func _call(c: Dictionary) -> void:
	var cs := get_tree().current_scene
	var n: Node = _find(cs, c["node"])
	if n == null or not n.has_method(c["method"]):
		print("HARNESS CALLFAIL ", c["node"], ".", c["method"])
		return
	n.callv(c["method"], c.get("args", []))

func _probe(pr: Dictionary) -> void:
	var cs := get_tree().current_scene
	var n: Node = _find(cs, pr["node"])
	var v = null
	if n != null:
		# an Expression, so probes can read properties, indexes and method results: position, snake[0], get_child_count()
		var ex := Expression.new()
		if ex.parse(pr["prop"]) == OK:
			v = ex.execute([], n, false)
			if ex.has_execute_failed():
				v = null
	print("HARNESS PROBE ", JSON.stringify({"frame": _frame, "node": pr["node"], "prop": pr["prop"],
		"found": n != null, "value": var_to_str(v)}))

func _tree(n: Node, cs: Node, depth: int, out: Array) -> void:
	# end-of-run snapshot for the agent: paths, types, positions and script variables (capped)
	if out.size() >= 40:
		return
	var e := {"path": str(cs.get_path_to(n)), "type": n.get_class(), "children": n.get_child_count()}
	if n is Node2D or n is Node3D or n is Control:
		e["pos"] = var_to_str(n.get("position"))
	var s: Script = n.get_script()
	if s:
		e["script"] = s.resource_path
		var vars := {}
		for p in s.get_script_property_list():
			if int(p["usage"]) & PROPERTY_USAGE_SCRIPT_VARIABLE:
				var v = n.get(p["name"])
				if v is Node:
					vars[p["name"]] = "<%s %s>" % [v.get_class(), cs.get_path_to(v)]
				elif v is Object:
					vars[p["name"]] = "<%s>" % v.get_class() if v else "<freed>"
				else:
					vars[p["name"]] = var_to_str(v).left(60)
		e["vars"] = vars
	out.append(e)
	if depth < 4:
		var k := 0
		for ch in n.get_children():
			k += 1
			if k > 6:
				break
			_tree(ch, cs, depth + 1, out)

func _count(n: Node) -> int:
	var c := 1
	for ch in n.get_children():
		c += _count(ch)
	return c
'''

# headless-only noise that says nothing about the project
BENIGN = re.compile(r"(__harness|ALSA|PulseAudio|audio driver|No audio|Vulkan|OpenGL|dummy|"
                    r"Couldn't load project settings|editor_layout|ObjectDB instances leaked|resources still in use)", re.I)


def _profile(work):
    return f'''(version 1)
(allow default)
(deny network*)
(deny file-write* (subpath "{HOME}"))
(allow file-write* (subpath "{work}") (subpath "{HOME}/Library/Application Support/Godot")
       (subpath "{HOME}/Library/Caches/Godot") (subpath "/private/tmp") (subpath "/private/var/folders"))
'''


def _godot(args, proj, timeout):
    return subprocess.run(["sandbox-exec", "-p", _profile(proj), GODOT, "--headless", "--path", str(proj)] + args,
                          capture_output=True, text=True, timeout=timeout)


def _messages(text):
    """Godot's stderr -> (errors, warnings); an 'at:' line is folded into the message above it."""
    errors, warnings, last = [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("at:") and last is not None:
            last[-1] += "  " + line[:200]
            continue
        if BENIGN.search(line):
            last = None
            continue
        if line.startswith(("SCRIPT ERROR", "ERROR:", "USER ERROR", "Parse Error")) or " ERROR:" in line[:20]:
            errors.append(line[:400])
            last = errors
        elif line.startswith(("WARNING:", "USER WARNING", "SCRIPT WARNING")):
            warnings.append(line[:400])
            last = warnings
        else:
            last = None
    return errors, warnings


TEST_BASE = r'''extends Node
# Injected by gd_run.py for test runs: base class of the agent's own test script (res://__agent_test.gd).
# The test overrides run(); helpers wait physics frames, press actions, read nodes and record checks.
# Output lines start with "TEST ".
var scene: Node
var _passed := 0
var _failed := 0

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	await get_tree().process_frame
	await get_tree().process_frame
	scene = get_tree().current_scene
	if scene == null:
		print("TEST NOSCENE")
		get_tree().quit()
		return
	await run()
	print("TEST DONE ", JSON.stringify({"passed": _passed, "failed": _failed}))
	get_tree().quit()

func run() -> void:
	pass

func frames(n: int) -> void:
	for i in n:
		await get_tree().physics_frame

func press(action: String) -> void:
	_action(action, true)

func release(action: String) -> void:
	_action(action, false)

func tap(action: String) -> void:
	_action(action, true)
	await frames(2)
	_action(action, false)

func _action(action: String, pressed: bool) -> void:
	if not InputMap.has_action(action):
		check(false, "input action \"%s\" exists" % action)
		return
	var e: InputEvent = null
	for k in InputMap.action_get_events(action):
		if k is InputEventKey:
			e = k.duplicate()
			break
	if e == null:
		e = InputEventAction.new()
		e.action = action
	e.pressed = pressed
	Input.parse_input_event(e)
	if pressed:
		Input.action_press(action)
	else:
		Input.action_release(action)

func node(path: String) -> Node:
	# accept the root's own name ("Main", "Main/Player", "/root/Main/Player") as well as paths relative to it
	var p := path.trim_prefix("/root/").trim_prefix("/")
	if p == "" or p == "." or p == String(scene.name):
		return scene
	if p.begins_with(String(scene.name) + "/"):
		p = p.substr(String(scene.name).length() + 1)
	var n := scene.get_node_or_null(p)
	if n == null:
		n = scene.find_child(p.get_file(), true, false)
	if n == null:
		var names := []
		for c in scene.get_children():
			names.append(String(c.name))
		check(false, "node \"%s\" exists (the main scene root is `scene`, named %s; its children: %s)" % [path, scene.name, ", ".join(names)])
	return n

func check(cond: bool, label: String) -> void:
	if cond:
		_passed += 1
	else:
		_failed += 1
	print("TEST CHECK ", JSON.stringify({"ok": cond, "label": label}))

func check_eq(actual, expected, label: String) -> void:
	var ok: bool = typeof(actual) == typeof(expected) and actual == expected
	if not ok and (typeof(actual) in [TYPE_INT, TYPE_FLOAT]) and (typeof(expected) in [TYPE_INT, TYPE_FLOAT]):
		ok = is_equal_approx(float(actual), float(expected))
	if ok:
		_passed += 1
	else:
		_failed += 1
	print("TEST CHECK ", JSON.stringify({"ok": ok, "label": label, "actual": var_to_str(actual).left(80),
		"expected": var_to_str(expected).left(80)}))
'''


def _with_harness(project_text, test=False):
    entry = '__harness="*res://__harness.gd"' + ('\n__agent_test="*res://__agent_test.gd"' if test else "")
    if "[autoload]" in project_text:
        return project_text.replace("[autoload]", "[autoload]\n\n" + entry, 1)
    return project_text.rstrip() + "\n\n[autoload]\n\n" + entry + "\n"


def run_project(files, frames=180, inputs=(), probes=(), calls=(), timeout=120, tree=False, test_code=None, base=None):
    """test_code: the agent's own test script (extends "res://__test_base.gd", overrides run()); when given, the run
    ends when the test finishes (frames is then only a backstop) and out["test"] holds its checks."""
    out = {"ok": False, "stage": "files", "errors": [], "warnings": [], "frames": 0, "exit_code": None,
           "timed_out": False, "probes": [], "scene": None, "nodes": None}
    pg = files.get("project.godot")
    if not pg:
        out["errors"] = ["project.godot is missing"]
        return out
    if not re.search(r'run/main_scene\s*=\s*"[^"]+"', pg):
        out["errors"] = ['project.godot has no run/main_scene (set it under [application])']
        return out
    work = Path(tempfile.mkdtemp(prefix="gdr_", dir="/private/tmp"))
    proj = work / "p"
    try:
        if base:  # an existing project's non-text files (sprites, .import, .uid): copied first, text files go on top
            shutil.copytree(base, proj, dirs_exist_ok=True)
        for rel, text in files.items():
            rel = rel.removeprefix("res://").lstrip("/")
            if ".." in Path(rel).parts:
                out["errors"] = [f"refusing path outside the project: {rel}"]
                return out
            dst = proj / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text)
        (proj / "project.godot").write_text(_with_harness(pg, test=test_code is not None))
        (proj / "__harness.gd").write_text(HARNESS)
        if test_code is not None:
            out["test"] = {"done": False, "checks": [], "passed": 0, "failed": 0}
            (proj / "__test_base.gd").write_text(TEST_BASE)
            (proj / "__agent_test.gd").write_text(test_code)
        (proj / "__harness.json").write_text(json.dumps({"frames": frames, "inputs": list(inputs),
                                                        "probes": list(probes),
                                                        "calls": list(calls), "tree": tree}))
        out["stage"] = "import"
        try:
            imp = _godot(["--import"], proj, timeout)
        except subprocess.TimeoutExpired:
            out.update(timed_out=True, errors=["import timed out"])
            return out
        e, w = _messages(imp.stderr + "\n" + imp.stdout)
        out["errors"] += e
        out["warnings"] += w
        out["stage"] = "load"
        try:
            # quit-after is a backstop in case the harness never gets to quit (e.g. the main scene failed)
            # headless idle frames run far faster than the 60 Hz physics frames the harness counts, so this backstop
            # must be generous; real hangs are caught by the wall-clock timeout instead
            p = _godot(["--quit-after", str(frames * 200 + 2000)], proj, timeout)
        except subprocess.TimeoutExpired as ex:
            out["timed_out"] = True
            stderr = ex.stderr.decode() if isinstance(ex.stderr, bytes) else (ex.stderr or "")
            e, w = _messages(stderr)
            out["errors"] += e + [f"run timed out after {timeout}s (infinite loop or blocking call?)"]
            return out
        out["exit_code"] = p.returncode
        e, w = _messages(p.stderr)
        out["errors"] += e
        out["warnings"] += w
        for line in p.stdout.splitlines():
            if line.startswith("HARNESS SCENE "):
                out["scene"] = line[14:].strip()
                out["stage"] = "run"
            elif line.startswith("HARNESS PROBE "):
                out["probes"].append(json.loads(line[14:]))
            elif line.startswith("HARNESS TREE "):
                out["tree"] = json.loads(line[13:])
            elif line.startswith("HARNESS NODES "):
                out["nodes"] = int(line[14:])
            elif line.startswith("HARNESS CALLFAIL "):
                out["calls_failed"] = out.get("calls_failed", []) + [line[17:].strip()]
            elif line.startswith("HARNESS NOACTION "):
                out["warnings"].append(f"input action not defined in InputMap: {line[17:].strip()}")
            elif line.startswith("TEST CHECK ") and "test" in out:
                out["test"]["checks"].append(json.loads(line[11:]))
            elif line.startswith("TEST DONE ") and "test" in out:
                out["test"].update(json.loads(line[10:]), done=True)
                out["stage"] = "done"
            elif line.startswith("TEST NOSCENE") and "test" in out:
                out["errors"].append("test: the main scene did not load")
            elif line.startswith("HARNESS DONE "):
                out["frames"] = int(line[13:])
                out["stage"] = "done"
        if out["scene"] in (None, "<none>") and not out["errors"]:
            out["errors"].append("main scene did not load")
        if out["exit_code"] not in (0, None) and not out["errors"]:
            out["errors"].append(f"Godot exited with code {out['exit_code']} (crash?)")
        out["ok"] = out["stage"] == "done" and not out["errors"]
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_many(jobs, workers=6):
    """jobs: list of kwargs dicts for run_project. Runs in parallel (each job is its own Godot process)."""
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda j: run_project(**j), jobs))


if __name__ == "__main__":
    import sys
    # python gd_run.py <project dir> [frames]  -> JSON report (handy for manual checks)
    root = Path(sys.argv[1])
    fs = {str(p.relative_to(root)): p.read_text() for p in root.rglob("*")
          if p.is_file() and ".godot" not in p.parts and p.suffix in (".gd", ".tscn", ".tres", ".godot", ".cfg", ".gdshader")}
    print(json.dumps(run_project(fs, frames=int(sys.argv[2]) if len(sys.argv) > 2 else 180), ensure_ascii=False, indent=1))
