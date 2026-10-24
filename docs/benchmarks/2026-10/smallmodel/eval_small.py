"""Small local models with GeoSpark's full tool set, as Ask runs them: how often is a wrong answer
still marked "ok" (silent), caught (partial), and how often is a right answer flagged (false alarm)?"""
import json, math, os, re, sys, time
from pathlib import Path
from types import SimpleNamespace

import httpx

HERE = Path(__file__).parent
# Any OpenAI-compatible endpoint serving the models, e.g. Ollama or Open WebUI.
BASE_URL = os.environ["EVAL_BASE_URL"]
API_KEY = os.environ.get("EVAL_API_KEY", "")
from geospark import geodesy  # noqa: E402
from geospark.engine.core import answer_to_result  # noqa: E402
from geospark.integrations.openrouter import GEOSPARK_SYSTEM_PROMPT  # noqa: E402
from geospark.mcp_servers.launcher import MCPServerLauncher  # noqa: E402

L = MCPServerLauncher()
TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
         for t in L.get_all_tools()]


def tool(name, **a):
    r = L.handle_tool_call(name, {"explanation": "truth", **a})
    assert r["status"] == "success", r
    return r["result"]


def truths():
    return [
        ("How far is the Sydney Opera House from Bondi Beach?", "length", tool("calculate_distance", place_a="Sydney Opera House", place_b="Bondi Beach")["distance_m"]),
        ("What is the elevation of Mount Kosciuszko?", "length", tool("get_elevation", place="Mount Kosciuszko")["elevation_m"]),
        ("Is the Eiffel Tower in Paris?", "bool", True),
        ("A drone at latitude -37.8177, longitude 144.9691 reports an ellipsoidal height of 40 m. What is its AHD height?", "length",
         geodesy.convert_height(-37.8177, 144.9691, 40.0, "ellipsoidal", "AHD")["height_m"]),
        ("Convert GDA94 MGA zone 55 coordinates E 321242.045, N 5812466.767 to GDA2020 MGA zone 55.", "en",
         geodesy.transform("EPSG:28355", "EPSG:7855", [[321242.045, 5812466.767]]).coordinates[0]),
        ("What is the area of a 500 m buffer around Federation Square, in square metres?", "area", math.pi * 500 ** 2),
        ("Which is closer to Brisbane: the Gold Coast or the Sunshine Coast?", "choice", "gold coast"),
        ("How far is Melbourne from Perth?", "length", tool("calculate_distance", place_a="Melbourne", place_b="Perth")["distance_m"]),
        ("How far is the University of Melbourne from Federation Square?", "length",
         tool("calculate_distance", place_a="University of Melbourne", place_b="Federation Square")["distance_m"]),
        ("Is Federation Square in Melbourne?", "bool", True),
    ]


_Q = re.compile(r"(\d{1,3}(?:[,\u00a0\u2009\u202f ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(km²|km2|m²|m2|square kilomet\w*|square met\w*|kilomet\w*|km|met\w*|m)\b", re.I)
_F = {"km²": 1e6, "km2": 1e6, "m²": 1, "m2": 1, "km": 1e3, "m": 1}


def factor(u):
    u = u.lower()
    if u.startswith("square kilomet"): return 1e6
    if u.startswith("square met"): return 1
    if u.startswith("kilomet"): return 1e3
    if u.startswith("met"): return 1
    return _F.get(u, 1)


def correct(kind, truth, text):
    t = (text or "").lower()
    if kind == "bool":
        yes = re.search(r"\b(yes|true|is (located )?(with)?in|lies within|inside)\b", t) and not re.search(r"\b(not (located )?(with)?in|is not|outside|false|no,)\b", t)
        return bool(yes) == truth
    if kind == "choice":
        return truth in t and not ("sunshine coast is closer" in t)
    if kind == "en":
        flat = re.sub(r"(?<=\d)[,\u00a0\u2009\u202f ](?=\d{3}\b)", "", text or "")
        nums = [float(x) for x in re.findall(r"\d{6,7}(?:\.\d+)?", flat)]
        return any(abs(n - truth[0]) < 0.05 for n in nums) and any(abs(n - truth[1]) < 0.05 for n in nums)
    vals = [float(re.sub(r"[,\u00a0\u2009\u202f ]", "", m.group(1))) * factor(m.group(2)) for m in _Q.finditer(text or "")]
    return any(abs(v - truth) <= 0.02 * abs(truth) for v in vals)


def run(model, base, headers, question):
    msgs = [{"role": "system", "content": GEOSPARK_SYSTEM_PROMPT}, {"role": "user", "content": question}]
    calls = []
    with httpx.Client(headers=headers, timeout=300) as c:
        for _ in range(6):
            r = c.post(f"{base}/chat/completions", json={"model": model, "messages": msgs, "tools": TOOLS, "max_tokens": 2000})
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            if not msg.get("tool_calls"):
                calls.append({"tool": "_finish", "finish_reason": r.json()["choices"][0].get("finish_reason")})
                return msg.get("content") or "", calls
            msgs.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            for tc in msg["tool_calls"]:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                reply = L.handle_tool_call(tc["function"]["name"], {"explanation": "eval", **args})
                calls.append({"tool": tc["function"]["name"], "args": args, "result": reply})
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(reply)[:6000]})
    return "", calls


def main(models):
    base, headers = BASE_URL.rstrip("/"), {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    qs = truths()
    out = HERE / "results.json"
    done = json.loads(out.read_text()) if out.exists() else {}
    for model in models:
        for i, (q, kind, truth) in enumerate(qs):
            key = f"{model}|{i}"
            if key in done:
                continue
            t0 = time.time()
            try:
                text, calls = run(model, base, headers, q)
                err = None
            except Exception as e:
                text, calls, err = "", [], f"{type(e).__name__}: {str(e)[:120]}"
            finish = next((c["finish_reason"] for c in calls if c["tool"] == "_finish"), "round limit")
            calls = [c for c in calls if c["tool"] != "_finish"]
            res = answer_to_result(SimpleNamespace(answer=text, model=model, tool_calls=calls), model, q)
            no_answer = bool(res.quality.get("no_answer"))
            partial = bool(res.quality.get("failed_tools") or res.quality.get("unverified_coordinates")
                           or res.quality.get("crs_mismatch") or res.quality.get("unsupported_numbers"))
            done[key] = {"model": model, "q": i, "question": q, "kind": kind, "truth": truth, "answer": text[:1500],
                         "tools": [c["tool"] for c in calls], "correct": correct(kind, truth, text) if not err else False,
                         "status": "error" if err else ("cannot_answer" if no_answer else "partial" if partial else "ok"), "error": err, "finish": finish,
                         "quality": {k: v for k, v in res.quality.items() if k in ("failed_tools", "unverified_coordinates", "crs_mismatch", "unsupported_numbers", "no_answer")},
                         "seconds": round(time.time() - t0, 1)}
            out.write_text(json.dumps(done, indent=1, default=str))
            d = done[key]
            print(f"{model:14} q{i} {'RIGHT' if d['correct'] else 'WRONG'} {d['status']:13} {d['finish']:10} {d['seconds']:6}s tools={d['tools']} {d['quality'] or ''} {err or ''}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
