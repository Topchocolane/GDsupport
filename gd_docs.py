"""Godot 4.6 API lookup for the agent: an index of the engine's own class reference (godot_docs/, extracted with
`Godot --headless --doctool`) plus a Godot 3 -> 4 rename table. lookup(query) answers in a few short lines:
  "CharacterBody3D"            class: parent chain, properties, methods (signatures), signals, constants
  "CharacterBody3D.move_and_slide" / "move_and_slide"   one member, with the classes that define it
  "KinematicBody"              Godot 3 name -> its Godot 4 replacement
usage: python gd_docs.py <query>   (builds godot_docs/index.json on first use)"""
import difflib, json, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "godot_docs"
INDEX = ROOT / "index.json"

# Godot 3 names the model keeps writing, and what Godot 4.6 calls them
RENAMES = {
    "Spatial": "Node3D", "KinematicBody": "CharacterBody3D", "KinematicBody2D": "CharacterBody2D",
    "RigidBody": "RigidBody3D", "StaticBody": "StaticBody3D", "Area": "Area3D", "CollisionShape": "CollisionShape3D",
    "MeshInstance": "MeshInstance3D", "Camera": "Camera3D", "Position2D": "Marker2D", "Position3D": "Marker3D",
    "Particles": "GPUParticles3D", "Particles2D": "GPUParticles2D", "CPUParticles": "CPUParticles3D",
    "Light": "Light3D", "DirectionalLight": "DirectionalLight3D", "OmniLight": "OmniLight3D",
    "SpotLight": "SpotLight3D", "RayCast": "RayCast3D", "Navigation2D": "NavigationRegion2D (+ NavigationAgent2D)",
    "Navigation": "NavigationRegion3D (+ NavigationAgent3D)", "VisibilityNotifier2D": "VisibleOnScreenNotifier2D",
    "VisibilityNotifier": "VisibleOnScreenNotifier3D", "YSort": "Node2D with y_sort_enabled = true",
    "Tween (node)": "create_tween() returns a Tween", "PoolStringArray": "PackedStringArray",
    "PoolVector2Array": "PackedVector2Array", "PoolIntArray": "PackedInt32Array", "PoolRealArray": "PackedFloat32Array",
    "File": "FileAccess (FileAccess.open(path, FileAccess.READ))", "Directory": "DirAccess",
    "ARVRCamera": "XRCamera3D", "SpatialMaterial": "StandardMaterial3D", "CubeMesh": "BoxMesh",
    "PhysicsBody": "PhysicsBody3D", "PlaneShape3D": "WorldBoundaryShape3D", "PlaneShape": "WorldBoundaryShape3D",
    "RayShape": "SeparationRayShape3D", "RigidBody3D.wake_up": "set sleeping = false", "ProximityGroup": "(removed)", "Listener": "AudioListener3D",
    "AudioStreamPlayer3D": "AudioStreamPlayer3D", "GIProbe": "VoxelGI", "BakedLightmap": "LightmapGI",
    "TextureRect.expand": "TextureRect.expand_mode", "OS.get_ticks_msec": "Time.get_ticks_msec()",
    "rand_range": "randf_range(from, to)", "yield": "await signal", "instance": "instantiate()",
    "move_and_slide(velocity)": "set velocity, then move_and_slide() with no arguments",
    "connect(signal, target, method)": "signal_name.connect(callable)  e.g. button.pressed.connect(_on_pressed)",
    "export": "@export var", "onready": "@onready var", "tool": "@tool",
}


def build():
    idx = {}
    for f in ROOT.rglob("*.xml"):
        try:
            c = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        if c.tag != "class":
            continue
        meths = []
        for m in c.iter("method"):
            ret = (m.find("return").get("type") if m.find("return") is not None else "void")
            ps = ", ".join(p.get("name") + ": " + p.get("type") + (" = " + p.get("default") if p.get("default") else "")
                           for p in sorted(m.findall("param"), key=lambda p: int(p.get("index"))))
            q = m.get("qualifiers") or ""
            meths.append(f"{m.get('name')}({ps}) -> {ret}" + (" [static]" if "static" in q else ""))
        idx[c.get("name")] = {
            "inherits": c.get("inherits") or "",
            "props": [f"{p.get('name')}: {p.get('type')}" + (f" = {p.get('default')}" if p.get("default") else "")
                      for p in c.iter("member")],
            "methods": meths,
            "signals": [s.get("name") + "(" + ", ".join(a.get("name") + ": " + a.get("type")
                        for a in s.findall("param")) + ")" for s in c.iter("signal")],
            "consts": [k.get("name") for k in c.iter("constant")],
        }
    INDEX.write_text(json.dumps(idx))
    return idx


_IDX = None


def index():
    global _IDX
    if _IDX is None:
        _IDX = json.loads(INDEX.read_text()) if INDEX.exists() else build()
    return _IDX


def chain(name):
    out, n = [], name
    while n and n in index() and len(out) < 12:
        out.append(n)
        n = index()[n]["inherits"]
    return out


def member(cls, name):
    """(kind, text) of a member defined on cls or an ancestor."""
    for c in chain(cls):
        d = index()[c]
        for m in d["methods"]:
            if m.split("(")[0] == name:
                return f"{c}.{m}"
        for p in d["props"]:
            if p.split(":")[0] == name:
                return f"{c}.{p} (property)"
        for s in d["signals"]:
            if s.split("(")[0] == name:
                return f"{c} signal {s}"
        if name in d["consts"]:
            return f"{c}.{name} (constant)"
    return None


def lookup(query, limit=40):
    q = query.strip().strip("`'\"").removesuffix("()")
    idx = index()
    lines = []
    for old, new in RENAMES.items():
        if q == old or q == old.split(" ")[0] or q == old.split("(")[0]:
            lines.append(f"Godot 3 name '{old}' does not exist in Godot 4.6; use: {new}")
    if "." in q:
        cls, _, name = q.partition(".")
        if cls in idx:
            hit = member(cls, name)
            if hit:
                return "\n".join(lines + [hit])
            near = difflib.get_close_matches(name, [m.split("(")[0] for c in chain(cls) for m in idx[c]["methods"]] +
                                             [p.split(":")[0] for c in chain(cls) for p in idx[c]["props"]] +
                                             [k for c in chain(cls) for k in idx[c]["consts"]], 5)
            return "\n".join(lines + [f"{cls} has no member '{name}'." + (f" Close: {', '.join(near)}" if near else "")])
        q = cls
    if q in idx:
        d = idx[q]
        own = lambda k: d[k]
        lines.append(f"class {q}  (inherits {' < '.join(chain(q)[1:]) or '-'})")
        if d["props"]:
            lines.append("properties: " + "; ".join(own("props")[:limit]))
        if d["methods"]:
            lines.append("methods: " + "; ".join(own("methods")[:limit]))
        if d["signals"]:
            lines.append("signals: " + "; ".join(own("signals")))
        if d["consts"]:
            lines.append("constants: " + ", ".join(d["consts"][:20]))
        lines.append("(inherited members: look up the parent class, or Class.member)")
        return "\n".join(lines)
    if lines:
        return "\n".join(lines)
    # a bare member name: which classes define it
    hits = [f"{c}.{m}" for c, d in idx.items() for m in d["methods"] if m.split("(")[0] == q][:8]
    hits += [f"{c}.{p} (property)" for c, d in idx.items() for p in d["props"] if p.split(":")[0] == q][:8]
    if hits:
        return "\n".join(hits[:12])
    near = difflib.get_close_matches(q, list(idx), 5)
    return f"'{q}' is not a Godot 4.6 class or member." + (f" Close class names: {', '.join(near)}" if near else "")


if __name__ == "__main__":
    print(lookup(" ".join(sys.argv[1:])))
