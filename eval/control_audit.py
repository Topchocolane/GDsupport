"""Audit the 60-task exam's checks with positive and negative controls (no model, Godot only).
  pass_count : how many saved final projects (all eval/projects_qwen36_*.json) passed the task. 0 = suspect check.
  positive   : re-run one saved passing project; it must pass again (else the check is flaky).
  stub       : the same project with every .gd reduced to its extends/var/const/signal lines (no logic);
               it must fail (else the check does not need any game logic).
  no_input   : the passing project run without the check's inputs (tasks that have inputs); it must fail
               (else the check does not test the input response).
usage: .venv/bin/python eval/control_audit.py [out.json]"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gd_run import run_project
from gd_exam import grade

ROOT = Path(__file__).resolve().parent
KEEP = re.compile(r"^(@tool|extends |class_name |signal |const |(@export\S*\s+)*var |@onready var )")


def stub(src):
    lines = [l for l in src.splitlines() if KEEP.match(l)]
    # an @onready var that reads a node is still logic-free; drop setters/getters written on the same line
    return "\n".join(re.sub(r":\s*$", "", l) for l in lines) + "\n"


def check(task, files, inputs=True):
    c = task["check"]
    r = run_project(files, frames=c["frames"], inputs=c["inputs"] if inputs else [], probes=c["probes"],
                    calls=c.get("calls", []))
    return grade(task, {"final": r})["behaves"], r["ok"]


def audit(task, passing):
    t = task["id"]
    out = {"task": t, "pass_count": len(passing)}
    if not passing:
        return out
    files = passing[-1]
    out["positive"] = check(task, files)[0]
    sfiles = {k: (stub(v) if k.endswith(".gd") else v) for k, v in files.items()}
    out["stub"], out["stub_runs"] = check(task, sfiles)
    if task["check"]["inputs"]:
        out["no_input"] = check(task, files, inputs=False)[0]
    return out


def main():
    tasks = json.loads((ROOT / "gd_projects.json").read_text())
    passing = {t["id"]: [] for t in tasks}
    for p in sorted(ROOT.glob("projects_qwen36_*.json"), key=lambda p: p.stat().st_mtime):
        for r in json.loads(p.read_text())["rows"]:
            if r.get("behaves") and r.get("files") and r["task"] in passing:
                passing[r["task"]].append(r["files"])
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda t: audit(t, passing[t["id"]]), tasks))
    for r in res:
        flags = []
        if r["pass_count"] == 0:
            flags.append("NEVER-PASSED")
        if r.get("positive") is False:
            flags.append("FLAKY")
        if r.get("stub"):
            flags.append("STUB-PASSES")
        if r.get("no_input"):
            flags.append("NO-INPUT-PASSES")
        r["flags"] = flags
        print(f"{r['task']:14s} n={r['pass_count']:3d} pos={r.get('positive')!s:5} stub={r.get('stub')!s:5}"
              f"(runs={r.get('stub_runs')!s:5}) noin={r.get('no_input', '-')!s:5} {' '.join(flags)}")
    print(json.dumps({"tasks": len(res), "flagged": sum(bool(r["flags"]) for r in res),
                      **{f: sum(f in r["flags"] for r in res) for f in
                         ("NEVER-PASSED", "FLAKY", "STUB-PASSES", "NO-INPUT-PASSES")}}))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
