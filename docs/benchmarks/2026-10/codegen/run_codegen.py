"""Ask a model to write each script, run it in a throwaway venv as a user would, and score the result."""
import json, math, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.argv, _a = [sys.argv[0]], sys.argv
import livebench as lb
sys.argv = _a
from pyproj import Geod

HERE = Path(__file__).parent
VENV_PY = HERE / "venv/bin/python"
TASKS = json.loads((HERE / "tasks/tasks.json").read_text())
G = Geod(ellps="WGS84")
SUFFIX = ("Python 3.13 with geopandas, shapely, pyproj and pandas is installed. Reply with one complete script in a "
          "single ```python code block. The script runs in the folder that holds the input file(s); its last printed "
          "line must be only the answer: a number{extra}.")

def ask(prov, model, prompt):
    base, headers = lb.provider(prov)
    with httpx.Client(headers=headers, timeout=600) as c:
        if prov == "anthropic":
            d = c.post(f"{base}/messages", json={"model": model, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}).json()
            u = d.get("usage", {}); text = "".join(b.get("text", "") for b in d.get("content", []) if b["type"] == "text")
            return text, lb.token_cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0))
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        body.update({"max_completion_tokens": 8000, "reasoning_effort": "low"} if prov == "openai" else {"max_tokens": 8000})
        d = c.post(f"{base}/chat/completions", json=body).json()
        if "choices" not in d:
            return f"API error: {str(d)[:200]}", 0.0
        u = d.get("usage", {})
        return d["choices"][0]["message"]["content"] or "", lb.token_cost(model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))

def run_script(code, task_dir):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"; shutil.copytree(task_dir, work)
        (work / "script.py").write_text(code)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(Path(tmp) / "home"), "LANG": "en_US.UTF-8"}  # no keys; fresh home
        try:
            p = subprocess.run([str(VENV_PY), "-I", "script.py"], cwd=work, env=env, capture_output=True, text=True, timeout=120)
            return p.stdout, p.stderr[-600:], p.returncode
        except subprocess.TimeoutExpired:
            return "", "timeout", -1

def score(t, stdout):
    lines = [l for l in stdout.strip().splitlines() if l.strip()]
    if not lines: return None, False
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", lines[-1].replace(",", " "))]
    if t["key"] == "latlon":
        if len(nums) < 2: return None, False
        lat, lon = nums[0], nums[1]
        if abs(lat) > 90: lat, lon = lon, lat
        err = G.inv(t["answer"]["lon"], t["answer"]["lat"], lon, lat)[2]
        return err, err <= t["tol"]
    if not nums: return None, False
    v = nums[0]
    if t["key"] == "count": return abs(v - t["answer"]), v == t["answer"]
    if t["key"] == "height_m": return abs(v - t["answer"]), abs(v - t["answer"]) <= t["tol"]
    rel = abs(v - t["answer"]) / abs(t["answer"])
    return rel, rel <= t["tol"]

def main(prov, model):
    out = HERE / f"results_{model.replace(':', '-').replace('/', '_')}.json"
    done = json.loads(out.read_text()) if out.exists() else {}
    for t in TASKS:
        if t["id"] in done: continue
        extra = " (latitude, longitude)" if t["key"] == "latlon" else ""
        text, cost = ask(prov, model, t["prompt"] + "\n\n" + SUFFIX.format(extra=extra))
        lb.add_spend(cost)
        m = re.search(r"```python\n(.*?)```", text, re.S)
        code = m.group(1) if m else ""
        stdout, stderr, rc = run_script(code, HERE / "tasks" / t["id"]) if code else ("", "no code", -1)
        err, ok = score(t, stdout)
        done[t["id"]] = {"ok": ok, "error": err, "stdout_last": (stdout.strip().splitlines() or [""])[-1][:120],
                         "stderr": stderr, "rc": rc, "code": code, "cost": cost}
        out.write_text(json.dumps(done, indent=1))
        print(f"{model:16} {t['id']:18} {'OK ' if ok else 'X  '} err={err} last={done[t['id']]['stdout_last']!r} rc={rc}", flush=True)
    print("spent so far:", round(lb.spent(), 3))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
