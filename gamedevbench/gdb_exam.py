"""Our harness on GameDevBench (external check). Unlike our exam, each task starts from an existing project.
Workspace = the task dir filtered like upstream (no test*, task_config.json, *.md, hidden dirs). Text files go to the
agent as files; everything else (sprites, .import, .uid) is a base dir copied under them on every run.
Text-only model, so the upstream "you are a visual agent" line is dropped; Godot is 4.6.3, not the official 4.4.1.
Only tasks whose controls pass under 4.6.3 are used (gamedevbench/gdb_controls.json: ground truth passes, start fails).
usage: python gamedevbench/gdb_exam.py <model> <tag> [max_turns] [n_tasks] [--display] [--tasks=<file of task ids>]
Stage backups: re-running the same command resumes (eval/ckpt/gdb_<tag>_r0.json)."""
import json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gdb_validate import ROOT, task_config, validate

TEXT = {".gd", ".tscn", ".tres", ".godot", ".cfg", ".gdshader", ".json", ".txt", ".csv", ".gdshaderinc"}
WORK = Path(__file__).resolve().parent / "gdb_work"
MAX_TEXT = 60000  # skip a text file this large from the agent's view (kept in base so the project still runs)


def skip(rel):
    parts = rel.parts
    name = parts[-1].lower()
    return (any(p.startswith(".") for p in parts) or name.startswith("test") or name == "task_config.json"
            or name.endswith((".md", ".log")))


def workspace(task):
    """-> (text files dict, base dir path, list of asset paths shown to the model)"""
    src = ROOT / "tasks" / task
    base = WORK / task / "base"
    if base.exists():
        shutil.rmtree(base)
    files, assets = {}, []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if skip(rel):
            continue
        if p.suffix in TEXT and p.stat().st_size <= MAX_TEXT:
            try:
                files[str(rel)] = p.read_text()
                continue
            except UnicodeDecodeError:
                pass
        dst = base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        if p.suffix not in (".import", ".uid"):
            assets.append(str(rel))
    base.mkdir(parents=True, exist_ok=True)
    return files, str(base), assets


def prompt(task, files, assets):
    cfg = task_config(task)
    listing = "\n".join(f"  {k}" for k in sorted(files))
    extra = ("\nOther project files (binary assets, not readable as text, already in place):\n" +
             "\n".join(f"  {a}" for a in assets[:60]) + ("\n  ..." if len(assets) > 60 else "")) if assets else ""
    return (f"This Godot 4 project already exists. Its text files are loaded; use read_file to read them and "
            f"write_file to change them.\nText files:\n{listing}{extra}\n\nTask: {cfg['instruction']}\n"
            f"You must complete the full task without any further assistance.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    model_path, tag = args[0], args[1]
    max_turns = int(args[2]) if len(args) > 2 else 20
    n = int(args[3]) if len(args) > 3 else 0
    ctrl = json.loads((Path(__file__).resolve().parent / "gdb_controls.json").read_text())["rows"]
    tasks = [r["task"] for r in ctrl if r["gt"]["ok"] and not r["start"]["ok"]
             and ("--display" in sys.argv or not r["display"])]
    sel = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tasks=")), None)
    if sel:  # --tasks=<file with one task id per line>: run a subset (e.g. the GD_REF probe)
        want = set(Path(sel).read_text().split())
        tasks = [t for t in tasks if t in want]
    if n:
        tasks = tasks[:n]
    specs = []
    for t in tasks:
        files, base, assets = workspace(t)
        specs.append({"id": t, "prompt": prompt(t, files, assets), "files": files, "base": base, "check": {}})
    from mlx_lm import load
    from gd_agent import run_agents
    model, tok = load(model_path)
    t0 = time.time()
    ck = Path(__file__).resolve().parent / "ckpt"
    ck.mkdir(exist_ok=True)
    res = run_agents(model, tok, specs, max_turns=max_turns, log=sys.stdout, ckpt=str(ck / f"gdb_{tag}_r0.json"))
    rows = []
    for s, r in zip(specs, res):
        out = WORK / s["id"] / f"solved_{tag}"  # per tag, so a later run never overwrites earlier artifacts
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(s["base"], out)
        for rel, text in r["files"].items():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(text)
        v = validate(out, s["id"])
        rows.append({**{k: r[k] for k in ("task", "turns", "runs", "finished", "tests", "test_ok")}, "pass": v["ok"],
                     "msg": v["msg"], "changed": sorted(k for k in r["files"] if r["files"][k] != s["files"].get(k)),
                     "transcript": r["transcript"]})
        print(f"{s['id']} pass={v['ok']!s:5} turns={r['turns']:2d} {v['msg'][:100]}", flush=True)
    summ = {"model": tag, "n": len(rows), "pass": sum(r["pass"] for r in rows),
            "godot": "4.6.3", "minutes": round((time.time() - t0) / 60, 1)}
    print(json.dumps(summ))
    (Path(__file__).resolve().parent / f"gdb_{tag}.json").write_text(json.dumps({"summary": summ, "rows": rows},
                                                                                ensure_ascii=False, indent=1))
    (ck / f"gdb_{tag}_r0.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
