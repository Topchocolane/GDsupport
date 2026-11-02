"""Project-level exam: run the agent on eval/gd_projects.json and grade each final project.
usage: python gd_exam.py <model path> [adapter|-] [tag] [max_turns]
Scores per task: runs (imports, loads, runs all frames, no errors) and behaves (runs + every expectation holds).
Writes eval/projects_<tag>.json (with transcripts) and prints a summary line starting with {"model"."""
import json, re, sys, time
from pathlib import Path
from mlx_lm import load
from gd_agent import run_agents

NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def value(s):
    """var_to_str text -> python value: numbers, bools, vectors (tuple); anything else stays a string."""
    if s is None or s == "null":
        return None
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+(\.\d+)?(e-?\d+)?", s):
        return float(s)
    m = re.fullmatch(r"Vector[234]i?\((.*)\)", s)
    if m:
        return tuple(float(x) for x in NUM.findall(m.group(1)))
    return s


def comp(v, axis):
    if axis is None:
        return v if isinstance(v, float) else None
    if not isinstance(v, tuple):
        return None
    i = "xyz".index(axis)
    return v[i] if i < len(v) else None


def expect_ok(e, probes):
    try:
        if "p" in e:
            pr = probes[e["p"]]
            if e["op"] == "found":
                return pr["found"]
            v = value(pr["value"])
            if e["op"] == "eq":
                want = e["v"]
                if isinstance(want, bool):
                    return v is want
                if isinstance(want, (int, float)):
                    return isinstance(v, float) and abs(v - want) < 1e-6
                return pr["value"] == want
            op, _, ax = e["op"].partition("_")
            x = comp(v, ax or None)
            return x is not None and (x >= e["v"] if op == "ge" else x <= e["v"])
        a, b = value(probes[e["a"]]["value"]), value(probes[e["b"]]["value"])
        if e["op"] == "ne":
            return probes[e["a"]]["found"] and a is not None and a != b
        xa, xb = comp(a, e.get("axis")), comp(b, e.get("axis"))
        if xa is None or xb is None:
            return False
        return xb > xa + 1e-3 if e["op"] == "inc" else xb < xa - 1e-3
    except (IndexError, KeyError, ValueError, TypeError):
        return False


def grade(task, res):
    f = res["final"]
    if not f:
        return {"runs": False, "behaves": False, "failed_expect": "no files"}
    runs = f["ok"]
    # the harness reports probes in the order they fire (by frame), not the order the task lists them;
    # align by (frame, node, prop) so expect indices mean the declared probes (missing ones count as not found)
    pool = list(f["probes"])
    probes = []
    for want in task["check"]["probes"]:
        hit = next((p for p in pool if (p["frame"], p["node"], p["prop"]) == (want["frame"], want["node"], want["prop"])),
                   None)
        if hit:
            pool.remove(hit)
        probes.append(hit or {"found": False, "value": None})
    fails = [i for i, e in enumerate(task["check"]["expect"]) if not expect_ok(e, probes)]
    return {"runs": runs, "behaves": runs and not fails, "failed_expect": fails}


def main():
    model_path = sys.argv[1]
    adapter = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    tag = sys.argv[3] if len(sys.argv) > 3 else (Path(adapter).name if adapter else Path(model_path).name)
    max_turns = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    tasks = json.loads((Path(__file__).parent / "eval/gd_projects.json").read_text())
    model, tok = load(model_path, adapter_path=adapter)
    t0 = time.time()
    # GD_BEST_OF=k: k independent attempts per task (run one after another, same memory as k=1), then pick_best()
    # chooses using only what the agent knows (its own test result, whether its project runs) -- never the grader
    import os
    from gd_agent import pick_best
    k = int(os.environ.get("GD_BEST_OF", "1"))
    # a later attempt is only made for tasks with no passing self-test yet (offline: same score, 1.44 attempts per task
    # instead of 2 for k=2)
    cand = [[] for _ in tasks]
    # stage backups (10-24): eval/ckpt/<tag>_r<round>.json holds agent state mid-round (resume after a power cut by
    # re-running the same command); eval/ckpt/<tag>_done<round>.json holds finished rounds
    ck = Path(__file__).parent / "eval/ckpt"
    ck.mkdir(exist_ok=True)
    for rnd in range(k):
        done_f = ck / f"{tag}_done{rnd}.json"
        if done_f.exists():
            cand = json.loads(done_f.read_text())
            print(f"round {rnd} restored from {done_f}", flush=True)
            continue
        todo = [i for i in range(len(tasks)) if not any(c.get("test_ok") for c in cand[i])]
        if not todo:
            break
        for i, r in zip(todo, run_agents(model, tok, [tasks[i] for i in todo], max_turns=max_turns, log=sys.stdout,
                                         ckpt=str(ck / f"{tag}_r{rnd}.json"))):
            cand[i].append(r)
        done_f.write_text(json.dumps(cand, ensure_ascii=False))
    results, picks = [], []
    for i in range(len(tasks)):
        cands = cand[i]
        j = pick_best(cands)
        results.append({**cands[j], "picked": j, "candidates": [
            {"test_ok": c.get("test_ok"), "runs": bool((c.get("final") or {}).get("ok")),
             "behaves": grade(tasks[i], c)["behaves"]} for c in cands]})
    rows = []
    for t, r in zip(tasks, results):
        g = grade(t, r)
        rows.append({**r, **g, "kind": t["kind"]})
        f = r["final"] or {}
        print(f"{t['id']:12s} {t['kind']} runs={g['runs']!s:5} behaves={g['behaves']!s:5} turns={r['turns']:2d} "
              f"runs_called={r['runs']} finished={r['finished']} files={len(r['files'])} "
              f"fail={g['failed_expect']} err={(f.get('errors') or [''])[0][:120]}", flush=True)
    n = len(rows)
    summ = {"model": tag, "n": n, "runs": sum(r["runs"] for r in rows), "behaves": sum(r["behaves"] for r in rows),
            "runs_2d": sum(r["runs"] for r in rows if r["kind"] == "2d"),
            "runs_3d": sum(r["runs"] for r in rows if r["kind"] == "3d"),
            "behaves_2d": sum(r["behaves"] for r in rows if r["kind"] == "2d"),
            "behaves_3d": sum(r["behaves"] for r in rows if r["kind"] == "3d"),
            "finished": sum(r["finished"] for r in rows), "refused": sum(r.get("refused", 0) for r in rows), "avg_turns": round(sum(r["turns"] for r in rows) / n, 1),
            "minutes": round((time.time() - t0) / 60, 1)}
    print(json.dumps(summ))
    (Path(__file__).parent / f"eval/projects_{tag}.json").write_text(
        json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1))
    for f in ck.iterdir():
        if re.fullmatch(re.escape(tag) + r"_(r|done)\d+\.json(\.tmp)?", f.name):
            f.unlink()


if __name__ == "__main__":
    main()
