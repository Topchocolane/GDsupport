"""Corrected column for the 60-task exam: re-run the saved final project of three tasks whose legacy check is wrong,
with a check that follows the request text. The legacy check (eval/gd_projects.json) stays unchanged for comparability.
  shooter2d, projectile3d: the request asks for a fire-rate cap, not auto-fire while held -> two separate presses.
  fps_move: Head is a child of Player as the request says, so probe Player/Head (legacy probes "Head" at the root);
            also require the player to stay on the floor (y > -2), which the request implies.
  crate_push: 40 N on a default 1 kg crate drives it ~45 m in the legacy 100 push frames, off any floor the request
            allows ("large box"), so legacy y>=0 at frame 140 fails every correct project; probe at frame 70 instead.
            Found 10-23 by eval/control_audit.py (0 passes in 32 runs).
usage: .venv/bin/python eval/regrade_corrected.py eval/projects_<tag>.json [...]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gd_run import run_project

TAP2 = [{"frame": 20, "action": "shoot", "pressed": True}, {"frame": 25, "action": "shoot", "pressed": False},
        {"frame": 60, "action": "shoot", "pressed": True}, {"frame": 65, "action": "shoot", "pressed": False}]


def vec(v, i):
    try:
        return float(v.strip("Vector3() ").split(",")[i])
    except (AttributeError, ValueError, IndexError):
        return None


def shots(files):
    r = run_project(files, frames=120, inputs=TAP2, probes=[{"frame": 10, "node": ".", "prop": "shots_fired"},
                                                            {"frame": 110, "node": ".", "prop": "shots_fired"}])
    v = [p.get("value") for p in sorted(r["probes"], key=lambda p: p["frame"])]
    return bool(r["ok"] and len(v) == 2 and v[0] == "0" and str(v[1]).isdigit() and int(v[1]) >= 2)


def fps(files):
    r = run_project(files, frames=150, inputs=[{"frame": 40, "action": "move_forward", "pressed": True}],
                    probes=[{"frame": 35, "node": "Player", "prop": "position"},
                            {"frame": 140, "node": "Player", "prop": "position"},
                            {"frame": 5, "node": "Player/Head", "prop": "position"}])
    p = {x["frame"]: x for x in r["probes"]}
    a, b = p.get(35, {}).get("value"), p.get(140, {}).get("value")
    za, zb, yb = vec(a, 2), vec(b, 2), vec(b, 1)
    return bool(r["ok"] and p.get(5, {}).get("found") and None not in (za, zb, yb) and zb < za and yb > -2)


def crate(files):
    r = run_project(files, frames=80, inputs=[{"frame": 40, "action": "push", "pressed": True}],
                    probes=[{"frame": 35, "node": "Crate", "prop": "position"},
                            {"frame": 70, "node": "Crate", "prop": "position"}])
    p = {x["frame"]: x for x in r["probes"]}
    a, b = p.get(35, {}).get("value"), p.get(70, {}).get("value")
    xa, xb, yb = vec(a, 0), vec(b, 0), vec(b, 1)
    return bool(r["ok"] and None not in (xa, xb, yb) and xb > xa + 1e-3 and yb >= 0)


FIX = {"shooter2d": shots, "projectile3d": shots, "fps_move": fps, "crate_push": crate}


def main():
    for path in sys.argv[1:]:
        d = json.loads(Path(path).read_text())
        rows = d["rows"]
        legacy = sum(r["behaves"] for r in rows)
        changed = {}
        for r in rows:
            if r["task"] in FIX:
                new = FIX[r["task"]](r["files"]) if r.get("files") else False
                if new != bool(r["behaves"]):
                    changed[r["task"]] = new
        corrected = legacy + sum(1 if v else -1 for v in changed.values())
        print(json.dumps({"run": d["summary"]["model"], "legacy": legacy, "corrected": corrected, "changed": changed}))


if __name__ == "__main__":
    main()
