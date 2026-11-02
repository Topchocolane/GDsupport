"""Agent loop for whole-project Godot 4.6 work: the model gets file tools plus a headless run tool and iterates
until it calls finish (or runs out of turns). Uses Qwen3-Coder's native <tool_call> format, so the same
transcripts train a model that works under any OpenAI-style tool-calling client.

run_agents(model, tok, tasks, max_turns=16) -> list of {task, files, turns, transcript, finished, final}
  tasks: [{"id", "prompt", "check": {frames, inputs, probes}}]; final = gd_run report on the end state.
Batches all live agents per step with batch_generate."""
import json, os, re, time
from mlx_lm import batch_generate
from mlx_lm.sample_utils import make_logits_processors, make_sampler
from gd_run import run_project

SYSTEM = """You are an autonomous Godot 4.6 game developer. You build complete, runnable projects alone.
Work in the project with the tools: write every file the project needs (project.godot with run/main_scene,
.tscn scenes in Godot 4 text format, .gd scripts, input actions in project.godot when you need custom ones),
then call run_project to start the game headless and read its errors. Fix every error and run again.
Prefer creating nodes in scenes or in code over external assets; there are no image or sound files.
When the project runs cleanly and does what was asked, call finish with a short summary."""

TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List all files in the project.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read one project file.",
                                      "parameters": {"type": "object", "properties": {
                                          "path": {"type": "string", "description": "Path relative to res://"}},
                                          "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
                                      "description": "Create or overwrite one project file with the full content.",
                                      "parameters": {"type": "object", "properties": {
                                          "path": {"type": "string", "description": "Path relative to res://, e.g. scenes/main.tscn"},
                                          "content": {"type": "string", "description": "Complete file content"}},
                                          "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_project",
                                      "description": "Run the project headless from its main scene for some frames and "
                                                     "report load/runtime errors and warnings.",
                                      "parameters": {"type": "object", "properties": {
                                          "frames": {"type": "integer", "description": "Physics frames to run (default 180)"}}}}},
    {"type": "function", "function": {"name": "finish", "description": "Declare the project done.",
                                      "parameters": {"type": "object", "properties": {
                                          "summary": {"type": "string", "description": "What was built"}},
                                          "required": ["summary"]}}},
]

# test tool: the agent writes its own GDScript test of the request and runs it against the project; with the test
# gate, finish needs a passing test of the current files (grounded feedback instead of self-judgement)
TEST_TOOL = os.environ.get("GD_TEST_TOOL", "1") == "1"
TEST_GATE = TEST_TOOL and os.environ.get("GD_TEST_GATE", "1") != "0"
# strict: a passing test only counts if it exercises behaviour (input, waited frames or a method call) with 3+ checks;
# without it the model passes the gate with trivial "node X is a Node2D" tests (self-collusion, seen in RFT4 10-15)
TEST_STRICT = TEST_TOOL and os.environ.get("GD_TEST_STRICT", "0") == "1"


def weak_test(code):
    checks = len(re.findall(r"\bcheck(?:_eq)?\(", code))
    acts = re.search(r"\b(?:press|tap|release)\(|await frames\(|\bscene\.\w+\(", code)
    if checks < 3:
        return f"it has {checks} checks; check every requirement (3 or more checks)"
    if not acts:
        return "it only checks the starting state; drive the game (press/tap an action, await frames, or call a " \
               "method on scene) and check what changed"
    return None
TEST_SYSTEM = """

Verify behaviour with test_project. Its script runs inside the game after the main scene loads. The names below
(Lamp, brightness, toggle, dim) only illustrate the form: use the node, variable, function and action names of YOUR
project, as written in your own files.
extends "res://__test_base.gd"
func run() -> void:
	var lamp := node("Lamp")             # path relative to the main scene root; scene = the root itself
	check_eq(lamp.brightness, 0, "lamp starts off")
	press("toggle")                      # also release(action) and await tap(action)
	await frames(30)                     # physics frames, 60 per second
	check(lamp.brightness > 0, "toggle turns the lamp on")
	scene.dim(5)                         # call methods directly
	check_eq(lamp.brightness, 5, "dim sets brightness")
Always define func run() -> void: with the checks inside it. After the project runs cleanly, write one test that
checks every requirement of the request: node names and types, variable and function names, input actions, and each
behaviour (state after calls or inputs), plus at least one stress check (repeated input, limits). Fix the project
until the test passes, then finish."""
TEST_TOOL_DEF = {"type": "function", "function": {
    "name": "test_project",
    "description": "Run the project with your GDScript test (extends \"res://__test_base.gd\", overrides run()) and "
                   "report each check, plus any runtime errors.",
    "parameters": {"type": "object", "properties": {
        "script": {"type": "string", "description": "Complete test script"},
        "frames": {"type": "integer", "description": "Physics-frame limit for the whole test (default 600)"}},
        "required": ["script"]}}}
if TEST_TOOL:
    SYSTEM += TEST_SYSTEM
    TOOLS = TOOLS[:-1] + [TEST_TOOL_DEF] + TOOLS[-1:]

# docs tool: exact Godot 4.6 signatures from the engine's own class reference + Godot 3 -> 4 renames (gd_docs.py),
# so the model can check a class or method instead of guessing (Spatial, KinematicBody, invented methods)
DOCS_TOOL = os.environ.get("GD_DOCS_TOOL", "0") == "1"
DOCS_SYSTEM = """

Check Godot 4.6 API names with lookup_api before using a class, method or property you are not sure of:
lookup_api("CharacterBody3D") lists its properties, methods and signals; lookup_api("Timer.start") gives one
signature; Godot 3 names (Spatial, KinematicBody, ...) return their Godot 4 replacement. If a run reports an unknown
identifier, look it up instead of guessing again."""
DOCS_TOOL_DEF = {"type": "function", "function": {
    "name": "lookup_api",
    "description": "Look up a Godot 4.6 class, Class.member or member name: exact signatures, properties, signals.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "e.g. CharacterBody2D, Label.text, move_and_slide, Spatial"}},
        "required": ["query"]}}}
if DOCS_TOOL:
    SYSTEM += DOCS_SYSTEM
    TOOLS = TOOLS[:-1] + [DOCS_TOOL_DEF] + TOOLS[-1:]

# property cheat sheets (GD_REF=ui,particles; 10-30): .tscn values the engine itself writes, generated by
# tools/ref/*.gd (anchor/grow presets, particle enums + a sample scene), for the knowledge gaps in eval/failure_map.py
REF = [r for r in os.environ.get("GD_REF", "ui,particles").split(",") if r]
REF_INTRO = {"ui": "Control layout presets, exactly as the editor writes them in a .tscn node "
                   "(grow_* = 1 is the default and is omitted):",
             "particles": "Particles: enum values that .tscn files store as ints, then a scene Godot saved itself:"}
# .tscn/.tres unknown-property lint (GD_LINT=1; 10-30): Godot drops a misspelt property without an error
# (trails_enabled for trail_enabled), so each run report also lists names that are not in the class (tscn_lint.py).
# Controls: 0 hits on the GameDevBench ground truth apart from 25 real Godot 3 leftovers; on s1 it fires on 100 of
# 296 failed tasks and 0 of 33 passed ones.
LINT = os.environ.get("GD_LINT", "1") == "1"
if LINT:
    from tscn_lint import lint_files

def _ref_text(r):
    return (f"Reference: {REF_INTRO[r]}\n" +
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools/ref", f"{r}.txt")).read().strip())


# GD_REF puts the sheets in every task's system prompt. That cost our 60-task exam 45 -> 31 on the same seed (10-31):
# most tasks have no UI or particles and the long block only slowed them down (finished 32 -> 19). GD_REF_AUTO=1 instead
# appends a sheet to the task message only when the task text names its area.
REF_AUTO = os.environ.get("GD_REF_AUTO", "1") == "1"
REF_TRIGGER = {"ui": re.compile(r"\b(anchors?|anchor_\w+|[Pp]resets?|(?:Top|Bottom|Left|Right|VCenter|HCenter) Wide|"
                                r"Full Rect|size_flags\w*|\w+Container|HUD|grow_(?:horizontal|vertical))\b"),
               "particles": re.compile(r"particle|emitter|emission", re.I)}
if not REF_AUTO:
    for _r in REF:
        SYSTEM += "\n\n" + _ref_text(_r)


def task_refs(prompt):
    """Sheets to append to this task's first message under GD_REF_AUTO."""
    return [r for r in REF if REF_AUTO and REF_TRIGGER[r].search(prompt)]


def test_report(r, files=None, limit=20):
    t = r.get("test") or {}
    lines = []
    if r["stage"] in ("files", "import", "load") or (r["errors"] and not t.get("checks")):
        lines.append(report(r, files=files))
    if t:
        if not t.get("done"):
            lines.append(f"TEST DID NOT FINISH (frame limit reached or the test crashed).")
        lines.append(f"TEST RESULT: {t.get('passed', 0)} passed, {t.get('failed', 0)} failed")
        for c in t.get("checks", [])[:limit]:
            row = ("PASS " if c["ok"] else "FAIL ") + c["label"]
            if not c["ok"] and "actual" in c:
                row += f" (actual {c['actual']}, expected {c['expected']})"
            lines.append(row)
        if r["errors"] and t.get("checks"):
            errs = (shown_errors(r["errors"]) if "knock" in H2 else r["errors"])[:8]
            lines += ["ERROR " + e + (quote(e, files) if files else "") for e in errs]
            if HINTS and "tquote" in H2:
                lines += ["    " + h for h in dict.fromkeys(hint(e, files) for e in errs) if h][:3]
    return "\n".join(lines)


CALL = re.compile(r"<tool_call>\s*<function=([\w.-]+)>(.*?)</function>\s*</tool_call>", re.S)
PARAM = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)\n?</parameter>", re.S)
MAX_FILE = 60_000
# Qwen3-Coder's recommended decoding; greedy decoding loops on long .tscn files ("filter_filter_filter...")
SAMPLER = make_sampler(temp=0.7, top_p=0.8, top_k=20)
PROCESSORS = make_logits_processors(repetition_penalty=1.05)
# finish guard: finish is refused while the current files fail to run (part of the agent harness, ships with it)
GUARD = os.environ.get("GD_FINISH_GUARD", "1") != "0"
# end-of-run scene snapshot in clean run reports (node paths/types/positions/script vars), so the agent can compare
# what it built with what was asked; off by default until tested
SHOW_TREE = os.environ.get("GD_SHOW_TREE", "0") == "1"
# self-check gate: the first finish on a clean project is refused once with the request restated and an end-of-run
# scene snapshot, asking the agent to verify names, variables, actions and behaviour before finishing again
SELF_CHECK = os.environ.get("GD_SELF_CHECK", "0") == "1"
SELF_CHECK_MSG = """NOT FINISHED YET: the project runs, but check it against the request before finishing.
The request was:
{prompt}

{snapshot}
Go through the request one requirement at a time: every node name and type, where it sits in the tree, every
variable and function name, every input action, and every behaviour (does it move, change, count, react as asked?).
If something is missing or wrong, fix it and run_project again. If everything matches, call finish again."""


def parse_calls(text):
    return [(name, {k: v for k, v in PARAM.findall(body)}) for name, body in CALL.findall(text or "")]


LOC = re.compile(r"res://([^\s:\]\)]+):(\d+)")


def quote(e, files):
    """Godot errors name file:line; show that line like an editor would, plus a hint for the common .tscn mistake."""
    m = LOC.search(e)
    if not m or m.group(1) not in files:
        return ""
    lines = files[m.group(1)].split("\n")
    n = int(m.group(2))
    if not 1 <= n <= len(lines):
        return ""
    out = f"\n    > {m.group(1)}:{n}: {lines[n - 1].strip()[:200]}"
    line = lines[n - 1].strip()
    inline = re.match(r"(\w+)\s*=\s*([A-Z]\w+)\s*(?:\.new\(\)|\{|\()", line)
    if "tscn" in H2 and m.group(1).endswith(".tscn") and inline and inline.group(2) in _classes() and \
            inline.group(2) not in ("Vector2", "Vector3", "Color", "Transform2D", "Transform3D", "Rect2", "Basis"):
        # a resource written inline (BoxShape3D.new(), SphereMesh { ... }): show the exact two-part rewrite
        prop, cls = inline.groups()
        args = re.findall(r"(\w+)\s*[=:]\s*([A-Z]\w*\([^()]*\)|[-\d.]+|true|false)", line[inline.end():])
        out += (f"\n    hint: a .tscn cannot build a {cls} inline. Add this section above the first [node]:\n"
                f"[sub_resource type=\"{cls}\" id=\"{cls}_1\"]\n" + "".join(f"{k} = {v}\n" for k, v in args) +
                f"    and in the node write: {prop} = SubResource(\"{cls}_1\")")
    elif m.group(1).endswith(".tscn") and re.search(r"\.new\(|\b(pre)?load\(", line):
        out += ("\n    hint: .tscn property values must be literals; declare resources as [sub_resource] / "
                "[ext_resource] sections and reference them with SubResource(\"id\") / ExtResource(\"id\")")
    elif "tscn" in H2 and m.group(1).endswith(".tscn") and "Transform3D(" in line and "Vector3(" in line:
        out += ("\n    hint: in a .tscn, Transform3D takes 12 plain numbers (basis x, y, z then origin), no Vector3 "
                "inside: transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0) puts the node at (0, 2, 0).")
    elif "tscn" in H2 and m.group(1).endswith(".tscn") and "Transform2D(" in line and "Vector2(" in line:
        out += ("\n    hint: in a .tscn, Transform2D takes 6 plain numbers; usually just write position = Vector2(x, y).")
    return out


def _classes():
    from gd_docs import index
    return index()


# knock-on errors that only repeat an earlier, more specific one; hidden when that one is present
KNOCK_ON = [(re.compile(r"autoload, script 'res://__agent_test\.gd'"), re.compile(r"__agent_test\.gd")),
            (re.compile(r'Failed to load script "res://[^"]+" with error "Parse error"'), re.compile(r"Parse Error: (?!Parse error)")),
            (re.compile(r"Failed loading (resource|scene): res://\S+\.tscn"), re.compile(r"\.tscn|int_resources|ext_resources"))]


def shown_errors(errors):
    out = []
    for e in errors:
        knock = next((cause for pat, cause in KNOCK_ON if pat.search(e)), None)
        if knock and any(knock.search(o) and not any(p.search(o) for p, _ in KNOCK_ON) for o in errors):
            continue
        out.append(e)
    return out or errors


TEST_HELPERS = ("scene (the main scene root); await frames(n); press(action); release(action); await tap(action); "
                "node(path) -> Node; check(cond: bool, label: String); check_eq(actual, expected, label: String)")


def _extends(e, files):
    m = LOC.search(e)
    src = (files or {}).get(m.group(1), "") if m else ""
    x = re.search(r"^extends\s+(\w+)", src, re.M)
    return x.group(1) if x else None


# error hints (GD_HINTS=1): grounded notes for the failures Qwen3.6 hit most (10-17): project.godot [input] syntax,
# text written into binary .res/.mesh files, and unknown identifiers / methods (answered from the engine's own docs)
HINTS = os.environ.get("GD_HINTS", "1") == "1"
# GD_H2=comma list: the 10-20 hint changes one by one, for A/B (all off = the hints that scored 46.8 over 5 runs)
#   tassign  test scripts: `var x :=` -> `var x =`        tquote  quote test-script lines; hint runtime test errors
#   knock    hide knock-on errors when the cause shows     tscn    exact rewrite for inline .tscn resources/Transform3D
#   infer    show the fixed line for type-inference errors resid   name the missing/misplaced SubResource id
#   thelp    list test helpers / check_eq signature        ident   close names from the script's `extends` class
H2 = set(filter(None, os.environ.get("GD_H2", "").split(",")))
# red first (10-23, from pstack's tdd rule "the test must fail before the fix"): a passing self-test is re-run on a stub
# copy of the project whose scripts keep only extends/var/const/signal lines; if it passes there too it checks no game
# logic, so it does not count (finish gate and best-of-k both rely on test_ok)
REDFIRST = os.environ.get("GD_REDFIRST", "0") == "1"
_KEEP = re.compile(r"^(@tool|extends |class_name |signal |const |(@export\S*\s+)*var |@onready var )")


def stub_files(files):
    return {k: ("\n".join(re.sub(r":\s*$", "", l) for l in v.splitlines() if _KEEP.match(l)) + "\n"
                if k.endswith(".gd") else v) for k, v in files.items()}

INPUT_EXAMPLE = ('move_left={\n"deadzone": 0.5,\n"events": [Object(InputEventKey,"resource_local_to_scene":false,'
                 '"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,'
                 '"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":65,'
                 '"key_label":0,"unicode":97,"location":0,"echo":false,"script":null)]\n}')


def hint(e, files=None):
    if "thelp" in H2 and "__agent_test.gd" in e:
        m = re.search(r'Function "(\w+)\(\)" not found in base self', e)
        if m:
            return (f"hint: {m.group(1)}() does not exist in the test base. The only helpers are: {TEST_HELPERS}. "
                    "To hold a key: press(\"jump\"); await frames(30); release(\"jump\").")
        if re.search(r'"check_eq\(\)"|"check\(\)"', e) or 'as "String"' in e:
            return ("hint: check_eq(actual, expected, label: String) takes exactly 3 arguments and the label must be a "
                    "String; there is no tolerance argument. For an approximate check use "
                    "check(absf(a - b) < 0.5, \"label\"); to put a number in a label use str(x) or \"%.2f\" % x.")
    m = "infer" in H2 and (re.search(r'Cannot infer the type of "(\w+)" (variable|constant)', e) or \
        re.search(r"The variable type is being inferred from a Variant value", e))
    if m:
        name = m.group(1) if m.lastindex else "x"
        loc = LOC.search(e)
        src = (files or {}).get(loc.group(1), "").split("\n") if loc else []
        line = src[int(loc.group(2)) - 1].strip() if loc and 0 < int(loc.group(2)) <= len(src) else ""
        if ":=" in line:
            return (f"hint: the value's type is unknown when the script is parsed (it comes from get_node, a Dictionary, "
                    f"an Array or an untyped function), so ':=' cannot be used. Change the line to:\n    "
                    + line.replace(":=", "=", 1))
        return (f"hint: ':=' needs a value whose type is known at parse time. Use plain '=' "
                f"(var {name} = ...) or write the type (var {name}: float = ...).")
    if "project.godot" in e and ("Expected" in e or "Unexpected" in e or "corrupted" in e) or '"events"' in e:
        return ("hint: project.godot could not be parsed. Each input action under [input] must look exactly like this "
                "(physical_keycode 65 = A, 68 = D, 87 = W, 83 = S, 32 = Space, 4194320 = Up, 4194322 = Down, "
                "4194319 = Left, 4194321 = Right):\n" + INPUT_EXAMPLE +
                "\n    or leave [input] out and add the actions in code: InputMap.add_action(\"move_left\"); "
                "var ev := InputEventKey.new(); ev.physical_keycode = KEY_A; InputMap.action_add_event(\"move_left\", ev)")
    if "Unrecognized binary resource file" in e:
        return ("hint: .res, .mesh and .scn files are binary; you cannot write them as text. Use a text resource "
                "(.tres starting with [gd_resource type=\"BoxMesh\" format=3]), a [sub_resource] inside the .tscn, "
                "or create it in code (var m := BoxMesh.new()).")
    if "resid" in H2 and ("int_resources.has(id)" in e or "ext_resources.has(id)" in e) and files:
        for path, src in files.items():
            if not path.endswith((".tscn", ".tres")):
                continue
            for n, ln in enumerate(src.split("\n"), 1):
                u = re.search(r'(Sub|Ext)Resource\("([^"]+)"\)', ln)
                if not u:
                    continue
                d = re.search(r'^\[(sub|ext)_resource[^\]]*\bid="%s"' % re.escape(u.group(2)), src, re.M)
                if not d:
                    ids = re.findall(r'^\[(?:sub|ext)_resource[^\]]*\bid="([^"]+)"', src, re.M)
                    return (f"hint: {path}:{n} uses {u.group(1)}Resource(\"{u.group(2)}\") but no section declares "
                            f"id=\"{u.group(2)}\" (ids declared: {', '.join(ids) or 'none'}). Add "
                            f"[{u.group(1).lower()}_resource type=\"...\" id=\"{u.group(2)}\"] above the first [node], "
                            f"or use one of the declared ids.")
                if src[:d.start()].count("\n") + 1 > n:
                    return (f"hint: {path}:{n} uses {u.group(1)}Resource(\"{u.group(2)}\") before its section on line "
                            f"{src[:d.start()].count(chr(10)) + 1}; move that section above the first [node].")
    if "int_resources.has(id)" in e or "ext_resources.has(id)" in e:
        return ("hint: a .tscn/.tres refers to SubResource(\"id\") or ExtResource(\"id\") that is not defined ABOVE it. "
                "Put every [ext_resource] and [sub_resource] section before the [node] (or [resource]) that uses it, and "
                "make each id string match exactly.")
    if "Unexpected end of file" in e and ".tres" in e:
        return ("hint: a .tres must have a header and a [resource] section, e.g.\n[gd_resource type=\"StandardMaterial3D\" "
                "format=3]\n\n[resource]\nalbedo_color = Color(0.2, 0.6, 0.2, 1)")
    from gd_docs import lookup
    m = re.search(r'Identifier "(\w+)" not declared|Could not find type "(\w+)"', e)
    if m:
        ans = lookup(m.group(1) or m.group(2))
        if "Godot 3 name" in ans or ("not a Godot 4.6" in ans and "ident" not in H2):
            return "hint (Godot 4.6 docs): " + ans.split("\n")[0]
        if "not a Godot 4.6" in ans:
            base = _extends(e, files)
            near = lookup(f"{base}.{m.group(1)}").split("Close: ")[-1] if base and m.group(1) and \
                "Close: " in lookup(f"{base}.{m.group(1)}") else ""
            return (f"hint: '{m.group(1) or m.group(2)}' is neither a Godot 4.6 name nor declared in this script. "
                    + (f"Built-in members of {base} with a close name: {near}. " if near else "") +
                    "If it is your own value, declare it first (var name := ... at the top of the script).")
    m = re.search(r"Nonexistent function '(\w+)' in base '(\w+)", e) or \
        re.search(r'Function "(\w+)\(\)" not found in base (?!self)(\w+)', e)
    if m:
        return "hint (Godot 4.6 docs): " + lookup(f"{m.group(2)}.{m.group(1)}").split("\n")[-1]
    m = re.search(r"Invalid (?:access|assignment) of property or key '(\w+)'.*?base object of type '(\w+)'", e)
    if m:
        from gd_docs import index
        if m.group(2) in index() and m.group(2) not in ("Node", "Node2D", "Node3D", "CharacterBody2D",
                                                         "CharacterBody3D", "Control", "RigidBody2D", "RigidBody3D"):
            # a built-in class (mesh, shape, environment...): say what it really has
            return "hint (Godot 4.6 docs): " + lookup(f"{m.group(2)}.{m.group(1)}").split("\n")[-1]
        return (f"hint: {m.group(2)} has no property '{m.group(1)}' (built-in nodes only have their own properties; "
                f"declare it with var in the script attached to that node, and make sure the node has that script).")
    m = re.search(r"Script inherits from native type '(\w+)', so it can't be assigned to an object of type '(\w+)'", e)
    if m:
        return (f"hint: the script says `extends {m.group(1)}` but the node it is attached to in the .tscn has "
                f"type=\"{m.group(2)}\". Make them match: change that [node] to type=\"{m.group(1)}\", or change the "
                f"script to `extends {m.group(2)}`.")
    m = re.search(r'Cannot find member "(\w+)" in base "(\w+)"', e)
    if m:
        return "hint (Godot 4.6 docs): " + lookup(f"{m.group(2)}.{m.group(1)}").split("\n")[-1]
    m = re.search(r'Function "(\w+)\(\)" not found in base self', e)
    if m:
        ans = lookup(m.group(1))
        return "hint (Godot 4.6 docs): " + (ans if "not a Godot 4.6" in ans else
                                             f"{m.group(1)}() is not a global function; it belongs to: " +
                                             "; ".join(ans.split("\n")[:4]))
    m = re.search(r'Cannot infer the type of "(\w+)" variable', e)
    if m:
        return (f"hint: ':=' needs a value whose type is known at parse time. Declare the type explicitly "
                f"(var {m.group(1)}: Vector3 = ...) or use plain '=' (var {m.group(1)} = ...).")
    return ""


def report(r, limit=12, files=None):
    """gd_run report -> the text the model sees."""
    if r["ok"]:
        head = f"OK: ran {r['frames']} frames, main scene '{r['scene']}', {r['nodes']} nodes, no errors."
    else:
        where = {"files": "before starting", "import": "while importing", "load": "while loading the main scene",
                 "run": "while running", "done": "while running"}[r["stage"]]
        head = f"FAILED {where}" + (" (timed out)" if r["timed_out"] else "") + f": {len(r['errors'])} error(s)."
    errs = shown_errors(r["errors"]) if "knock" in H2 else r["errors"]
    lines = [head] + [f"ERROR {e}" + (quote(e, files) if files else "") for e in errs[:limit]]
    if HINTS:
        seen = []
        for e in errs[:limit]:
            h = hint(e, files)
            if h and h not in seen:
                seen.append(h)
        lines += ["    " + h for h in seen[:3]]
    if len(errs) > limit:
        lines.append(f"... {len(errs) - limit} more errors")
    lines += [f"WARNING {w}" for w in r["warnings"][:5]]
    if LINT and files:
        # the model stops at "OK", so the head line itself says the run is not clean yet
        lint = lint_files(files)
        if lint:
            lines[0] += (f" But {len(lint)} property name(s) in your scene/resource files are not real Godot 4.6 "
                         f"properties and do nothing; rename or remove them:")
        lines += [f"WARNING {w}" for w in lint[:8]] + ([f"... {len(lint) - 8} more"] if len(lint) > 8 else [])
    if r.get("tree"):
        lines.append(f"Scene at frame {r['frames']} (check names, positions and values against the request):")
        for e in r["tree"]:
            depth = 0 if e["path"] == "." else e["path"].count("/") + 1
            row = f"{'  ' * depth}{e['path'].split('/')[-1]} ({e['type']})"
            if e.get("script"):
                row += f" {e['script'].removeprefix('res://')}"
            if e.get("pos"):
                row += f" position={e['pos']}"
            if e.get("vars"):
                row += " " + ", ".join(f"{k}={v}".replace("\n", " ") for k, v in list(e["vars"].items())[:8])
            if e["children"] > 6:
                row += f" [{e['children']} children, first 6 shown]"
            lines.append(row)
    return "\n".join(lines)


class Agent:
    def __init__(self, task):
        refs = task_refs(task["prompt"])
        first = task["prompt"] + "".join("\n\n" + _ref_text(r) for r in refs)
        self.task, self.files, self.msgs = task, dict(task.get("files") or {}), [{"role": "user", "content": first}]
        self.base = task.get("base")  # existing-project tasks (GameDevBench): dir of non-text assets under the files
        self.turns, self.finished, self.runs, self.done = 0, False, 0, False
        self.last_ok, self.refused, self.self_checked = None, 0, False
        self.tests, self.test_ok, self.test_scripts = 0, None, []  # test_ok: last test of the current files passed  # last_ok: result of the last run of the current files (None = stale)

    def tool(self, name, a):
        if name == "list_files":
            return "\n".join(f"{p} ({len(c)} bytes)" for p, c in sorted(self.files.items())) or "(no files yet)"
        if name == "read_file":
            p = a.get("path", "").removeprefix("res://").strip()
            return self.files.get(p, f"ERROR no such file: {p}")
        if name == "write_file":
            p, c = a.get("path", "").removeprefix("res://").strip(), a.get("content", "")
            if not p or ".." in p.split("/") or p.startswith("__harness"):
                return f"ERROR invalid path: {p!r}"
            if len(c) > MAX_FILE:
                return f"ERROR file too large ({len(c)} chars, limit {MAX_FILE})"
            if HINTS and re.search(r"\.(res|mesh|scn|material|anim)$", p):
                return (f"ERROR {p} not written: .res/.mesh/.scn/.material/.anim are binary formats and cannot be "
                        f"written as text. Save it as a text resource ({p.rsplit('.', 1)[0]}.tres starting with "
                        f"[gd_resource type=\"BoxMesh\" format=3] then a [resource] section), put it in the .tscn as a "
                        f"[sub_resource], or create it in code (BoxMesh.new()). Update every path that refers to it.")
            self.files[p] = c if c.endswith("\n") else c + "\n"
            self.last_ok = None
            self.test_ok = None
            return f"wrote {p} ({len(c)} chars)"
        if name == "run_project":
            self.runs += 1
            try:
                frames = max(10, min(600, int(a.get("frames") or 180)))
            except ValueError:
                frames = 180
            r = run_project(self.files, base=self.base, frames=frames, tree=SHOW_TREE)
            self.last_ok = r["ok"]
            return report(r, files=self.files)
        if name == "lookup_api" and DOCS_TOOL:
            from gd_docs import lookup
            self.lookups = getattr(self, "lookups", 0) + 1
            return lookup(str(a.get("query", "")))[:2500]
        if name == "test_project" and TEST_TOOL:
            code = a.get("script", "")
            # forgive a wrong or missing extends line (the model often invents one); a test still needs func run()
            lines = code.strip("\n").split("\n")
            if lines and lines[0].startswith("extends"):
                lines = lines[1:]
            code = 'extends "res://__test_base.gd"\n' + "\n".join(lines) + "\n"
            if "tassign" in H2:
                # test values mostly come from node()/get() (untyped), where ':=' fails to parse
                code = re.sub(r"^(\s*(?:var|const)\s+\w+\s*):=", r"\1=", code, flags=re.M)
            if "func run(" not in code:
                return 'ERROR the test script must define func run() -> void: with its checks (it extends "res://__test_base.gd")'
            try:
                frames = max(30, min(1200, int(a.get("frames") or 600)))
            except ValueError:
                frames = 600
            self.tests += 1
            self.test_scripts.append(code)
            r = run_project(self.files, base=self.base, frames=frames, test_code=code)
            t = r.get("test") or {}
            self.test_ok = bool(r["ok"] and t.get("done") and t.get("failed", 1) == 0 and t.get("passed", 0) > 0)
            out = test_report(r, files={**self.files, "__agent_test.gd": code} if "tquote" in H2 else self.files)
            if REDFIRST and self.test_ok:
                rs = run_project(stub_files(self.files), frames=frames, test_code=code, base=self.base)
                ts = rs.get("test") or {}
                if ts.get("done") and ts.get("failed", 1) == 0 and ts.get("passed", 0) > 0:
                    self.test_ok = False
                    self.weak_red = getattr(self, "weak_red", 0) + 1
                    out += ("\nWEAK TEST: this test also passes on a copy of the project with all script logic removed "
                            "(only extends/var/const/signal lines kept), so it does not check that the game works. "
                            "Make it drive the game (press the actions, wait frames, call the methods the request "
                            "describes) and check the values that should change.")
            why = weak_test(code) if TEST_STRICT else None
            if self.test_ok and why:
                self.test_ok = False
                out += "\nWEAK TEST: this test does not count as a passing test because " + why + "."
            return out
        if name == "finish":
            if GUARD:
                if not self.files:
                    self.refused += 1
                    return "NOT FINISHED: the project has no files yet. Write the project, run it, then finish."
                if self.last_ok is None:  # files changed since the last run: check them now
                    r = run_project(self.files, base=self.base)
                    self.runs += 1
                    self.last_ok = r["ok"]
                    if not r["ok"]:
                        self.refused += 1
                        return "NOT FINISHED: the project does not run yet.\n" + report(r, files=self.files) + \
                            "\nFix these errors, run_project again, and call finish only when it runs cleanly."
                elif not self.last_ok:
                    self.refused += 1
                    return "NOT FINISHED: the last run_project failed. Fix the errors it reported, " \
                           "run_project again, and call finish only when it runs cleanly."
            if TEST_GATE and not self.test_ok:
                self.refused += 1
                return ("NOT FINISHED: no passing test of the current files. Write a test_project script that checks "
                        "every requirement of the request, fix the project until it passes, then finish.")
            if SELF_CHECK and not self.self_checked:
                self.self_checked = True
                r = run_project(self.files, base=self.base, tree=True)
                snap = report(r, files=self.files)
                return SELF_CHECK_MSG.format(prompt=self.task["prompt"], snapshot=snap)
            self.finished = True
            return "finished"
        return f"ERROR unknown tool {name}"

    def step(self, text):
        self.turns += 1
        self.msgs.append({"role": "assistant", "content": text})
        calls = parse_calls(text)
        if not calls:
            # a plain answer ends the episode, like a chat client would
            self.done = True
            return
        outs = [self.tool(n, a) for n, a in calls]
        for o in outs:
            self.msgs.append({"role": "tool", "content": o})
        if self.finished:
            self.done = True


# GD_SEED=n: common random numbers for A/B tests. Each agent's sampling noise depends only on (seed, task, turn, token
# index), not on which other agents share its batch, so two harness versions see the same noise until their
# transcripts differ, and a per-task difference can be credited to the change instead of to sampling luck
SEED = os.environ.get("GD_SEED")


def _row_sampler(name):
    import zlib
    import mlx.core as mx
    base, step = zlib.crc32(name.encode()), [0]

    def sample(logprobs):
        mx.random.seed((base + 7919 * step[0]) % (2 ** 32))
        step[0] += 1
        return SAMPLER(logprobs)
    return sample


def seeded_generate(model, tok, prompts, max_tokens, names):
    from mlx_lm.generate import BatchGenerator
    gen = BatchGenerator(model, stop_tokens=[[t] for t in tok.eos_token_ids], logits_processors=PROCESSORS)
    uids = gen.insert(prompts, [max_tokens] * len(prompts), samplers=[_row_sampler(n) for n in names])
    out = {u: [] for u in uids}
    while responses := gen.next_generated():
        for r in responses:
            if r.finish_reason != "stop":
                out[r.uid].append(r.token)
    gen.close()
    return [tok.decode(out[u]) for u in uids]


def _save_ckpt(path, agents):
    """Stage backup: every agent's full state after each sub-batch, written atomically (a power cut mid-write keeps
    the previous checkpoint)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump([a.__dict__ for a in agents], f, ensure_ascii=False)
    os.replace(tmp, path)


def run_agents(model, tok, tasks, max_turns=16, max_tokens=4096, max_ctx=28000, batch=8, log=None, ckpt=None):
    """ckpt: path of a stage-backup file; when it exists and matches these tasks the run resumes from it."""
    agents = [Agent(t) for t in tasks]
    if ckpt and os.path.exists(ckpt):
        saved = json.load(open(ckpt))
        if [d["task"]["id"] for d in saved] == [t["id"] for t in tasks]:
            for a, d in zip(agents, saved):
                a.__dict__.update(d)
            if log:
                print(f"resumed from {ckpt}: {sum(a.done for a in agents)}/{len(agents)} done, "
                      f"turns {sum(a.turns for a in agents)}", file=log, flush=True)
    t0 = last_ck = time.time()
    while True:
        live = [a for a in agents if not a.done and a.turns < max_turns]
        if not live:
            break
        prompts = []
        for a in live:
            ids = tok.apply_chat_template([{"role": "system", "content": SYSTEM}] + a.msgs, tools=TOOLS,
                                          add_generation_prompt=True, enable_thinking=False)
            if len(ids) > max_ctx:
                a.done = True
                a.msgs.append({"role": "tool", "content": "(context limit reached)"})
                continue
            prompts.append((a, ids))
        if not prompts:
            break
        # sub-batches keep the KV cache bounded (24 agents x 28k tokens would not fit next to the model)
        for i in range(0, len(prompts), batch):
            chunk = prompts[i:i + batch]
            if SEED is None:
                texts = batch_generate(model, tok, [p for _, p in chunk], max_tokens=max_tokens, sampler=SAMPLER,
                                       logits_processors=PROCESSORS).texts
            else:
                texts = seeded_generate(model, tok, [p for _, p in chunk], max_tokens,
                                        [f"{SEED}:{a.task['id']}:{a.turns}" for a, _ in chunk])
            for (a, _), text in zip(chunk, texts):
                a.step(text)
            if ckpt and time.time() - last_ck > 120:  # at most every 2 min: 300+ transcripts make a big file
                _save_ckpt(ckpt, agents)
                last_ck = time.time()
        if ckpt:
            _save_ckpt(ckpt, agents)
            last_ck = time.time()
        if log:
            print(f"step: {len(prompts)} live, {sum(a.done for a in agents)}/{len(agents)} done, "
                  f"{time.time() - t0:.0f}s", file=log, flush=True)
    out = []
    for a in agents:
        chk = a.task.get("check", {})
        final = run_project(a.files, frames=chk.get("frames", 180), inputs=chk.get("inputs", ()),
                            probes=chk.get("probes", ()), calls=chk.get("calls", ()),
                            base=getattr(a, "base", None)) if a.files else None
        out.append({"task": a.task["id"], "files": a.files, "turns": a.turns, "runs": a.runs,
                    "finished": a.finished, "refused": a.refused, "self_checked": a.self_checked, "tests": a.tests, "lookups": getattr(a, "lookups", 0), "weak_red": getattr(a, "weak_red", 0),
                    "test_ok": a.test_ok, "test_scripts": a.test_scripts, "final": final, "transcript": a.msgs})
    return out


def last_test_ratio(r):
    """Share of checks that passed in the attempt's last test run that reported any (-1 when it never got one)."""
    import re
    ratio = -1.0
    for m in r.get("transcript") or []:
        if m.get("role") == "tool":
            mm = re.search(r"TEST RESULT: (\d+) passed, (\d+) failed", str(m.get("content")))
            if mm and int(mm[1]) + int(mm[2]):
                ratio = int(mm[1]) / (int(mm[1]) + int(mm[2]))
    return ratio


def pick_best(cands):
    """Best-of-k without the grader: prefer an attempt whose own test passed (Qwen3.6 self-tests were right 85 of 99
    times when they passed); otherwise the one whose final project runs clean, ties broken by the larger share of
    passing checks in its last test (offline on four runs: 49.42 -> 49.75 of 60). Returns the chosen index."""
    for i, r in enumerate(cands):
        if r.get("test_ok"):
            return i
    return max(range(len(cands)), key=lambda i: (bool((cands[i].get("final") or {}).get("ok")), last_test_ratio(cands[i])))
