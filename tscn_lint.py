"""Unknown-property lint for .tscn / .tres text (GD_LINT=1).

Godot drops a property it does not know (or maps a few Godot 3 names) when it loads a scene, so a misspelt name (trails_enabled for
trail_enabled) runs with no error and the setting is just missing. This checks every `key = value` line of each
[node type=...], [sub_resource type=...] and [resource] section against the class's property names from the engine's
own ClassDB (tools/ref/class_props.json, dumped by tools/ref/class_props.gd), and names the closest real property.

Skipped on purpose: nodes without a type (instanced or inherited scenes), sections with a script, in the body or as a
header attribute (exported vars are not in ClassDB), a few _set()-only storage keys (_DYNAMIC), and slash paths (theme_override_*/..., shader_parameter/..., metadata/..., animation tracks).
"""
import difflib, json, os, re

_PROPS = None
_SECTION = re.compile(r"^\[(gd_scene|gd_resource|ext_resource|sub_resource|node|connection|editable|resource)\b(.*)\]\s*$")
_ATTR = re.compile(r'(\w+)="([^"]*)"')
_KEY = re.compile(r"^([A-Za-z_][\w]*)\s*=")
# stored through _set() and not listed on a fresh instance (checked against the GameDevBench ground-truth scenes)
_DYNAMIC = {"AnimationPlayer": re.compile(r"libraries$"), "AnimationTree": re.compile(r"libraries$"),
            "AnimationMixer": re.compile(r"libraries$"), "TileSet": re.compile(r"pattern_\d+$")}


def _props():
    global _PROPS
    if _PROPS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "ref", "class_props.json")
        _PROPS = {k: set(v) for k, v in json.load(open(path)).items()}
    return _PROPS


def lint_text(text, fname=""):
    """-> list of 'file: [node X] Class has no property 'p' (did you mean 'q'?)' strings."""
    props = _props()
    out, cls, label, keys, has_script = [], None, "", [], False

    def flush():
        if cls and cls in props and not has_script:
            for line_no, k in keys:
                if k not in props[cls] and not (cls in _DYNAMIC and _DYNAMIC[cls].match(k)):
                    near = difflib.get_close_matches(k, props[cls], n=1, cutoff=0.6)
                    out.append(f"{fname}:{line_no}: {label} {cls} has no property '{k}'" +
                               (f" (did you mean '{near[0]}'?)" if near else "") +
                               " -- not a Godot 4.6 property, so it has no effect (Godot drops it or reads it as an old alias)")

    for i, line in enumerate(text.splitlines(), 1):
        m = _SECTION.match(line.strip())
        if m:
            flush()
            kind, attrs = m.group(1), dict(_ATTR.findall(m.group(2)))
            cls, keys, has_script = None, [], "script" in attrs or "script=" in m.group(2)
            if kind == "node":
                cls, label = attrs.get("type"), f"[node {attrs.get('name', '?')}]"
            elif kind in ("sub_resource", "resource"):
                cls, label = attrs.get("type"), f"[{kind} {attrs.get('id', '')}]".replace(" ]", "]")
            if kind == "resource":
                head = re.search(r'\[gd_resource[^\]]*type="(\w+)"', text)
                cls = head.group(1) if head else None
            continue
        if cls is None:
            continue
        k = _KEY.match(line)
        if not k:
            continue
        if k.group(1) == "script":
            has_script = True
        keys.append((i, k.group(1)))
    flush()
    return out


def lint_files(files):
    """files: {rel_path: text} -> warnings for every .tscn/.tres."""
    out = []
    for name, text in sorted(files.items()):
        if name.endswith((".tscn", ".tres")) and isinstance(text, str):
            out += lint_text(text, name)
    return out


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        for w in lint_text(open(p).read(), p):
            print(w)
