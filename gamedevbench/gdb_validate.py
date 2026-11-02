"""GameDevBench (waynchi/gamedevbench, ICML 2026) validation with our Godot (4.6.3; the official runs use 4.4.1).
Follows the upstream validate_task: copy the project, add scripts/test.gd + scenes/test.tscn from the task source,
`--import --quit`, then run res://scenes/test.tscn and look for VALIDATION_PASSED / VALIDATION_FAILED.
  controls : positive control = every ground truth must pass; negative control = every starting point must fail
             (the verify-the-verifier rule: a task whose controls fail under 4.6.3 is excluded from our score)
usage: .venv/bin/python gamedevbench/gdb_validate.py controls [out.json]"""
import json, os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gd_run import GODOT

ROOT = Path(os.environ.get("GDB_ROOT", Path(__file__).resolve().parent / "data"))  # GameDevBench checkout (tasks/, tasks_gt/)
PASS, FAIL = re.compile(r"VALIDATION_PASSED"), re.compile(r"VALIDATION_FAILED(?::\s*(.+))?")


def task_config(task):
    return json.loads((ROOT / "tasks" / task / "task_config.json").read_text())


def _godot(args, cwd, timeout):
    try:
        p = subprocess.run([GODOT, "--headless", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode(errors="replace") + "\nTIMEOUT"


def validate(project_dir, task, timeout=90):
    """project_dir: the solved project (any files); test files always come from the task source."""
    src = ROOT / "tasks" / task
    work = Path(tempfile.mkdtemp(prefix="gdb_", dir="/private/tmp"))
    try:
        shutil.copytree(project_dir, work, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".godot", "*.md", "task_config.json"))
        for rel in ("scripts/test.gd", "scripts/test.gd.uid", "scenes/test.tscn"):
            if (src / rel).exists():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / rel, work / rel)
        _godot(["--import", "--quit", "--path", str(work)], work, timeout)
        out = _godot(["--path", str(work), "res://scenes/test.tscn"], work, timeout)
        for line in out.splitlines():
            if PASS.search(line):
                return {"ok": True, "msg": line.strip()[:200]}
            m = FAIL.search(line)
            if m:
                return {"ok": False, "msg": (m.group(1) or "failed")[:200]}
        tail = [l for l in out.splitlines() if "ERROR" in l or "TIMEOUT" in l][:3]
        return {"ok": False, "msg": "no marker: " + " | ".join(tail)[:200]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def controls():
    tasks = sorted(p.name for p in (ROOT / "tasks").iterdir() if (p / "project.godot").exists())

    def one(t):
        cfg = task_config(t)
        return {"task": t, "display": bool(cfg.get("requires_display")),
                "gt": validate(ROOT / "tasks_gt" / t, t), "start": validate(ROOT / "tasks" / t, t)}

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, tasks))
    usable = [r for r in res if r["gt"]["ok"] and not r["start"]["ok"]]
    summ = {"tasks": len(res), "display": sum(r["display"] for r in res),
            "gt_pass": sum(r["gt"]["ok"] for r in res), "start_fail": sum(not r["start"]["ok"] for r in res),
            "usable": len(usable), "usable_headless": sum(not r["display"] for r in usable)}
    print(json.dumps(summ))
    return res, summ


if __name__ == "__main__":
    if sys.argv[1:2] == ["controls"]:
        res, summ = controls()
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(json.dumps({"summary": summ, "rows": res}, indent=1))
