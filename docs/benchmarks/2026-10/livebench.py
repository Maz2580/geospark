"""Small, fair re-check of GeoSpark Bench on current models: bare vs with GeoSpark tools.

Usage (from the geospark repo, in its venv):
  python livebench.py list-workstation
  python livebench.py run --provider openrouter --model anthropic/claude-opus-5.5 --mode bare
  python livebench.py run --provider workstation --model gpt-oss:20b --mode tools --distance 80

Keys come from the environment or <repo>/.env.bench (gitignored): ANTHROPIC_API_KEY, OPENAI_API_KEY,
OPENROUTER_API_KEY, WORKSTATION_LLM_URL and WORKSTATION_LLM_API_KEY (any OpenAI-compatible server).
Scoring matches the README: distance correct within 10% of the pyproj geodesic; topology exact.
Results (resumable, one JSON per model x mode) go to ./results/.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[3]  # the geospark repository
sys.path.insert(0, str(REPO))
from geospark.bench.scorer import parse_boolean, parse_numeric  # noqa: E402
from geospark.mcp_servers.launcher import MCPServerLauncher  # noqa: E402

ENV = {k: v for k, v in dotenv_values(REPO / ".env.bench").items() if v} if (REPO / ".env.bench").exists() else {}


def server_key(name: str) -> str:
    """An API key from the environment or .env.bench (never printed or saved)."""
    return ENV.get(name) or os.environ.get(name, "")


# $ per million tokens (input, output), from the providers' list prices on 2026-10-24
PRICES = {"claude-opus-5-5": (4.0, 20.0), "gpt-6.1-sol": (2.0, 10.0)}
OUT = Path(__file__).parent / "results"
BUDGET_USD = float(os.getenv("LIVEBENCH_BUDGET_USD", "8"))  # all OpenRouter spend, across runs
LEDGER = OUT / "ledger.json"

SYSTEM_BARE = "Answer the question. End your reply with the final answer only: a number in metres, or True/False."
SYSTEM_TOOLS = ("You can call GeoSpark tools that compute geodesic distances and spatial relationships exactly. "
                "Use them when helpful. End your reply with the final answer only: a number in metres, or True/False.")


def provider(name: str) -> tuple[str, dict]:
    if name == "anthropic":
        return "https://api.anthropic.com/v1", {"x-api-key": server_key("ANTHROPIC_API_KEY"),
                                                "anthropic-version": "2023-06-01"}
    if name == "openai":
        return "https://api.openai.com/v1", {"Authorization": f"Bearer {server_key('OPENAI_API_KEY')}"}
    if name == "openrouter":
        return "https://openrouter.ai/api/v1", {"Authorization": f"Bearer {ENV['OPENROUTER_API_KEY']}",
                                                 "HTTP-Referer": "https://github.com/Maz2580/geospark",
                                                 "X-Title": "GeoSpark live check"}
    if name == "workstation":
        url = server_key("WORKSTATION_LLM_URL")
        return url.rstrip("/"), {"Authorization": f"Bearer {server_key('WORKSTATION_LLM_API_KEY')}",
                                 "User-Agent": "GeoSpark-bench/1.0"}  # Cloudflare rejects SDK user agents
    raise SystemExit(f"unknown provider {name}")


def questions(n_distance: int, per_predicate: int) -> list[dict]:
    rng = random.Random(7)
    ds = json.load(open(REPO / "geospark/bench/datasets/geodistance.json"))
    ds = ds if isinstance(ds, list) else ds["questions"]
    dist = sorted([q for q in ds if q["category"] == "distance_absolute"], key=lambda q: q["id"])
    picked = rng.sample(dist, min(n_distance, len(dist)))
    tp = json.load(open(REPO / "geospark/bench/datasets/geotopo.json"))
    tp = tp if isinstance(tp, list) else tp["questions"]
    for cat in sorted({q["category"] for q in tp}):
        pool = sorted([q for q in tp if q["category"] == cat], key=lambda q: q["id"])
        picked += rng.sample(pool, min(per_predicate, len(pool)))
    return picked


def tool_defs() -> list[dict]:
    wanted = set(os.getenv("LIVEBENCH_TOOLS", "calculate_distance,check_spatial_relationship").split(","))
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["inputSchema"]}}
            for t in MCPServerLauncher().get_all_tools() if t["name"] in wanted]


def chat_anthropic(client: httpx.Client, base: str, model: str, system: str, messages: list, tools: list | None) -> dict:
    body: dict = {"model": model, "system": system, "messages": messages, "max_tokens": int(os.getenv("LIVEBENCH_MAX_TOKENS", "2000"))}
    if tools:
        body["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                          "input_schema": t["function"]["parameters"]} for t in tools]
    for attempt in range(3):
        r = client.post(f"{base}/messages", json=body)
        if r.status_code in (429, 500, 529) and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def token_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (tokens_in * pin + tokens_out * pout) / 1e6


def ask_anthropic(client, base, model, q, mode, launcher) -> dict:
    tools = tool_defs() if mode == "tools" else None
    system = SYSTEM_TOOLS if tools else SYSTEM_BARE
    messages: list = [{"role": "user", "content": q["prompt_structured"]}]
    cost, calls, tool_calls = 0.0, 0, []
    for _ in range(6):
        data = chat_anthropic(client, base, model, system, messages, tools)
        calls += 1
        u = data.get("usage") or {}
        cost += token_cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0))
        uses = [b for b in data["content"] if b["type"] == "tool_use"]
        if not uses:
            return {"text": "".join(b.get("text", "") for b in data["content"] if b["type"] == "text"),
                    "cost": cost, "calls": calls, "tool_calls": tool_calls}
        messages.append({"role": "assistant", "content": data["content"]})
        results = []
        for b in uses:
            reply = launcher.handle_tool_call(b["name"], {"explanation": "bench", **(b.get("input") or {})})
            tool_calls.append(b["name"])
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(reply)[:4000]})
        messages.append({"role": "user", "content": results})
    return {"text": "", "cost": cost, "calls": calls, "tool_calls": tool_calls, "note": "no final answer in 6 turns"}


def ask_openai_responses(client, base, model, q, launcher) -> dict:
    """OpenAI with tools: the Responses API (chat completions refuses tools with reasoning on GPT-6.1)."""
    tools = [{"type": "function", "name": t["function"]["name"], "description": t["function"]["description"],
              "parameters": t["function"]["parameters"]} for t in tool_defs()]
    items: list = [{"role": "user", "content": q["prompt_structured"]}]
    cost, calls, tool_calls = 0.0, 0, []
    for _ in range(6):
        body = {"model": model, "instructions": SYSTEM_TOOLS, "input": items, "tools": tools,
                "reasoning": {"effort": "low"}, "max_output_tokens": 2000, "store": False,
                "include": ["reasoning.encrypted_content"]}
        r = client.post(f"{base}/responses", json=body)
        r.raise_for_status()
        data = r.json()
        calls += 1
        u = data.get("usage") or {}
        cost += token_cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0))
        out = data.get("output") or []
        fcalls = [o for o in out if o.get("type") == "function_call"]
        if not fcalls:
            text = "".join(c.get("text", "") for o in out if o.get("type") == "message" for c in o.get("content", []))
            return {"text": text, "cost": cost, "calls": calls, "tool_calls": tool_calls}
        items += out
        for fc in fcalls:
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            reply = launcher.handle_tool_call(fc["name"], {"explanation": "bench", **args})
            tool_calls.append(fc["name"])
            items.append({"type": "function_call_output", "call_id": fc["call_id"], "output": json.dumps(reply)[:4000]})
    return {"text": "", "cost": cost, "calls": calls, "tool_calls": tool_calls, "note": "no final answer in 6 turns"}


def chat(client: httpx.Client, base: str, model: str, messages: list, tools: list | None, prov: str) -> dict:
    body: dict = {"model": model, "messages": messages, "max_tokens": int(os.getenv("LIVEBENCH_MAX_TOKENS", "2000"))}
    if prov == "openai":
        body = {"model": model, "messages": messages, "max_completion_tokens": int(os.getenv("LIVEBENCH_MAX_TOKENS", "2000")), "reasoning_effort": "low"}
    if tools:
        body["tools"] = tools
    if prov == "openrouter":
        body["usage"] = {"include": True}
        body["reasoning"] = {"effort": "low"}  # same setting for every frontier model; keeps cost down
    for attempt in range(3):
        r = client.post(f"{base}/chat/completions", json=body)
        if r.status_code in (429, 502, 503, 504) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def spent() -> float:
    return json.loads(LEDGER.read_text()).get("usd", 0.0) if LEDGER.exists() else 0.0


def add_spend(usd: float) -> None:
    LEDGER.write_text(json.dumps({"usd": round(spent() + usd, 6)}))


def ask(client, base, model, q, mode, prov, launcher) -> dict:
    tools = tool_defs() if mode == "tools" else None
    messages = [{"role": "system", "content": SYSTEM_TOOLS if tools else SYSTEM_BARE},
                {"role": "user", "content": q["prompt_structured"]}]
    cost, calls, tool_calls = 0.0, 0, []
    for _ in range(6):
        data = chat(client, base, model, messages, tools, prov)
        calls += 1
        u = data.get("usage") or {}
        cost += float(u.get("cost") or 0) if prov == "openrouter" else token_cost(
            model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        msg = data["choices"][0]["message"]
        if not msg.get("tool_calls"):
            return {"text": msg.get("content") or "", "cost": cost, "calls": calls, "tool_calls": tool_calls}
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        for tc in msg["tool_calls"]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            reply = launcher.handle_tool_call(name, {"explanation": "bench", **args})
            tool_calls.append(name)
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(reply)[:4000]})
    return {"text": "", "cost": cost, "calls": calls, "tool_calls": tool_calls, "note": "no final answer in 6 turns"}


def score(q: dict, text: str) -> bool:
    text = text.replace("*", "").replace("`", "").replace("\\boxed", "")  # **True**, `123`, \boxed{1}
    if q["answer_type"] == "numeric":
        v = parse_numeric(text.strip().splitlines()[-1] if text.strip() else "") or parse_numeric(text)
        return v is not None and abs(v - q["ground_truth"]) <= 0.10 * abs(q["ground_truth"])
    v = parse_boolean(text.strip().splitlines()[-1] if text.strip() else "")
    if v is None:
        v = parse_boolean(text)
    return v is not None and v == q["ground_truth"]


def run(args) -> None:
    OUT.mkdir(exist_ok=True)
    base, headers = provider(args.provider)
    path = OUT / f"{args.model.replace('/', '_').replace(':', '-')}__{args.mode}.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    launcher = MCPServerLauncher()
    with httpx.Client(headers=headers, timeout=300) as client:
        for q in questions(args.distance, args.per_predicate):
            if q["id"] in done:
                continue
            if args.provider != "workstation" and spent() >= BUDGET_USD:
                print(f"Budget of ${BUDGET_USD} reached; stopping.")
                break
            t0 = time.time()
            try:
                if args.provider == "openai" and args.mode == "tools":
                    a = ask_openai_responses(client, base, args.model, q, launcher)
                elif args.provider == "anthropic":
                    a = ask_anthropic(client, base, args.model, q, args.mode, launcher)
                else:
                    a = ask(client, base, args.model, q, args.mode, args.provider, launcher)
            except Exception as e:
                a = {"text": "", "cost": 0.0, "calls": 0, "tool_calls": [], "error": f"{type(e).__name__}: {str(e)[:200]}"}
            a.update(category=q["category"], correct=score(q, a["text"]), seconds=round(time.time() - t0, 1),
                     ground_truth=q["ground_truth"])
            if args.provider != "workstation":
                add_spend(a["cost"])
            done[q["id"]] = a
            path.write_text(json.dumps(done, indent=1))
            print(f"{q['id']:16} {q['category']:20} {'OK ' if a['correct'] else 'X  '} {a['seconds']:6}s ${a['cost']:.4f} {a.get('error','')}", flush=True)
    summarize(path)


def summarize(path: Path) -> None:
    done = json.loads(path.read_text())
    dist = [v for v in done.values() if v["category"] == "distance_absolute"]
    topo = [v for v in done.values() if v["category"] != "distance_absolute"]
    pct = lambda xs: f"{100 * sum(x['correct'] for x in xs) / len(xs):.1f}% ({sum(x['correct'] for x in xs)}/{len(xs)})" if xs else "-"
    errors = sum(1 for v in done.values() if v.get("error"))
    print(f"\n{path.name}: distance {pct(dist)} | topology {pct(topo)} | errors {errors} | "
          f"cost ${sum(v['cost'] for v in done.values()):.3f} | total OpenRouter spend ${spent():.3f}")


def list_workstation() -> None:
    base, headers = provider("workstation")
    r = httpx.get(f"{base}/models", headers=headers, timeout=60)
    r.raise_for_status()
    for m in r.json().get("data", []):
        print(m.get("id"))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-workstation")
    r = sub.add_parser("run")
    r.add_argument("--provider", required=True, choices=["anthropic", "openai", "openrouter", "workstation"])
    r.add_argument("--model", required=True)
    r.add_argument("--mode", required=True, choices=["bare", "tools"])
    r.add_argument("--distance", type=int, default=20)
    r.add_argument("--per-predicate", type=int, default=3)
    rs = sub.add_parser("rescore")
    rs.add_argument("file")
    s = sub.add_parser("summary")
    s.add_argument("file")
    a = p.parse_args()
    if a.cmd == "list-workstation":
        list_workstation()
    elif a.cmd == "run":
        run(a)
    elif a.cmd == "rescore":  # re-apply the scorer to saved answers (no API calls)
        f = Path(a.file)
        done = json.loads(f.read_text())
        byid = {q["id"]: q for q in questions(80, 100)}
        for k, v in done.items():
            v["correct"] = score(byid[k], v["text"])
        f.write_text(json.dumps(done, indent=1))
        summarize(f)
    else:
        summarize(Path(a.file))
