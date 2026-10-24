"""Run the datum/height question set on a model (no tools) and score the error in metres.

  python datum_run.py run --provider anthropic --model claude-opus-5-5 [--set datum_questions.json]
  python datum_run.py report
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import httpx
from pyproj import Geod

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.argv, _argv = [sys.argv[0]], sys.argv  # livebench parses nothing at import, but keep argv clean
import livebench as lb  # noqa: E402

sys.argv = _argv
OUT = HERE / "results"
GEOD = Geod(ellps="GRS80")
SYSTEM = "Answer the question as an expert geodesist would. Show brief working, then the final JSON line."


def last_json(text: str) -> dict | None:
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text.replace("*", "")))):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def error_m(q: dict, got: dict | None) -> tuple[float | None, bool | None]:
    """(error in metres, correct for choice/zone questions)."""
    if not got:
        return None, False
    a = q["answer"]
    try:
        if q["kind"] == "en":
            return math.hypot(float(got["E"]) - a["E"], float(got["N"]) - a["N"]), None
        if q["kind"] in ("height", "height_ell"):
            key = next(iter(a))  # "AHD", "ellipsoidal" or "H"
            return abs(float(got[key]) - a[key]), None
        if q["kind"] == "latlon":
            return GEOD.inv(a["lon"], a["lat"], float(got["lon"]), float(got["lat"]))[2], None
        if q["kind"] == "zone_en":
            ok = int(got["zone"]) == a["zone"]
            return (math.hypot(float(got["E"]) - a["E"], float(got["N"]) - a["N"]) if ok else None), ok
        if q["kind"] == "choice":
            return None, str(got.get("cause", "")).strip().lower()[:1] == a["cause"]
    except (KeyError, TypeError, ValueError):
        return None, False
    return None, False


def grade(q: dict, err: float | None, ok: bool | None) -> str:
    if q["kind"] == "choice":
        return "correct" if ok else "wrong"
    if err is None:
        return "wrong" if ok is not False else "wrong zone / no answer"
    survey = 0.15 if q["kind"].startswith("height") else 0.05
    return "survey-grade" if err <= survey else "mapping-grade" if err <= 0.5 else "wrong"


def ask(client, prov, base, model, prompt) -> tuple[str, float]:
    if prov == "anthropic":
        data = lb.chat_anthropic(client, base, model, SYSTEM, [{"role": "user", "content": prompt}], None)
        u = data.get("usage") or {}
        return ("".join(b.get("text", "") for b in data["content"] if b["type"] == "text"),
                lb.token_cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0)))
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    data = lb.chat(client, base, model, msgs, None, prov)
    u = data.get("usage") or {}
    cost = lb.token_cost(model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)) if prov != "workstation" else 0.0
    return data["choices"][0]["message"].get("content") or "", cost


def ask_with_tools(client, prov, base, model, prompt) -> tuple[str, float, list[str]]:
    """The same question with GeoSpark's geodesy tools attached (transform_coordinates, convert_height)."""
    from geospark.mcp_servers.launcher import MCPServerLauncher

    lb.SYSTEM_TOOLS = (SYSTEM + " You can call GeoSpark tools that apply the official transformations and "
                       "geoid models; use them when helpful.")
    q = {"prompt_structured": prompt}
    launcher = MCPServerLauncher()
    if prov == "anthropic":
        a = lb.ask_anthropic(client, base, model, q, "tools", launcher)
    elif prov == "openai":
        a = lb.ask_openai_responses(client, base, model, q, launcher)
    else:
        a = lb.ask(client, base, model, q, "tools", prov, launcher)
    return a["text"], a["cost"], a["tool_calls"]


def run(args) -> None:
    OUT.mkdir(exist_ok=True)
    qs = json.loads((HERE / args.set).read_text())
    suffix = "__tools" if args.tools else ""
    path = OUT / f"{Path(args.set).stem}__{args.model.replace('/', '_').replace(':', '-')}{suffix}.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    base, headers = lb.provider(args.provider)
    with httpx.Client(headers=headers, timeout=300) as client:
        for q in qs:
            if q["id"] in done:
                continue
            if args.provider != "workstation" and lb.spent() >= lb.BUDGET_USD:
                print("Budget reached; stopping.")
                break
            t0 = time.time()
            try:
                calls: list[str] = []
                if args.tools:
                    text, cost, calls = ask_with_tools(client, args.provider, base, args.model, q["prompt"])
                else:
                    text, cost = ask(client, args.provider, base, args.model, q["prompt"])
                err_txt = None
            except Exception as e:
                text, cost, calls, err_txt = "", 0.0, [], f"{type(e).__name__}: {str(e)[:150]}"
            if args.provider != "workstation":
                lb.add_spend(cost)
            got = last_json(text)
            err, ok = error_m(q, got)
            done[q["id"]] = {"group": q["group"], "text": text, "parsed": got, "error_m": err, "ok": ok,
                             "grade": grade(q, err, ok), "cost": cost, "tool_calls": calls, "seconds": round(time.time() - t0, 1),
                             "api_error": err_txt}
            path.write_text(json.dumps(done, indent=1, ensure_ascii=False))
            shown = f"{err:.3f} m" if err is not None else ("ok" if ok else "-")
            print(f"{q['id']:10} {done[q['id']]['grade']:22} {shown:>14}  ${cost:.4f} {err_txt or ''}", flush=True)
    print(f"spent so far (all API runs): ${lb.spent():.3f}")


def report() -> None:
    for f in sorted(OUT.glob("*.json")):
        d = json.loads(f.read_text())
        print(f"\n== {f.stem}  (${sum(v['cost'] for v in d.values()):.3f})")
        groups: dict[str, list] = {}
        for qid, v in d.items():
            groups.setdefault(v["group"], []).append((qid, v))
        for g, items in groups.items():
            parts = []
            for qid, v in items:
                e = v["error_m"]
                parts.append(f"{qid[-2:]}:{v['grade'][:6]}" + (f"({e:.2f}m)" if e is not None else ""))
            print(f"  {g:40} " + "  ".join(parts))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--provider", required=True, choices=["anthropic", "openai", "workstation"])
    r.add_argument("--model", required=True)
    r.add_argument("--set", default="datum_questions.json")
    r.add_argument("--tools", action="store_true", help="attach GeoSpark's geodesy tools")
    sub.add_parser("report")
    a = p.parse_args()
    run(a) if a.cmd == "run" else report()
