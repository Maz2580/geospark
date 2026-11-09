"""Rerun Benchmark 2 models that failed in October 2026 because of proxy timeouts (HTTP 524).

Same questions (seed 7), prompts, scoring and token limit as livebench.py in this folder;
the only change is that replies are streamed, which keeps the connection open through the proxy.
Stops after 3 consecutive request failures. Run in the GeoSpark venv:
  WORKSTATION_LLM_URL=... WORKSTATION_LLM_API_KEY=... python rerun_streaming.py reruns_2026-11
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import livebench

failures = 0


def stream_chat(client, base, model, messages, tools, prov):
    """livebench.chat, streamed: returns the same response shape."""
    global failures
    body = {"model": model, "messages": messages, "stream": True,
            "max_tokens": int(os.getenv("LIVEBENCH_MAX_TOKENS", "2000"))}
    if tools:
        body["tools"] = tools
    text, calls, finish = "", {}, None
    try:
        with client.stream("POST", f"{base}/chat/completions", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                choices = json.loads(line[5:]).get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                finish = choices[0].get("finish_reason") or finish
                text += delta.get("content") or ""
                for tc in delta.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", len(calls)), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    c["id"] = tc.get("id") or c["id"]
                    fn = tc.get("function") or {}
                    c["function"]["name"] += fn.get("name") or ""
                    c["function"]["arguments"] += fn.get("arguments") or ""
    except Exception:
        failures += 1
        print(f"request failed ({failures} in a row)", flush=True)
        if failures >= 3:
            print("ABORT: 3 consecutive failures", flush=True)
            os._exit(3)
        raise
    failures = 0
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {}}


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
livebench.OUT, livebench.LEDGER = out, out / "ledger.json"
livebench.chat = stream_chat
for model, mode in (("qwen3.5:9b", "bare"), ("gemma4:12b", "bare"), ("gemma4:12b", "tools")):
    print(f"== {model} {mode} {time.strftime('%H:%M')}", flush=True)
    livebench.run(argparse.Namespace(provider="workstation", model=model, mode=mode, distance=20, per_predicate=3))
print("ALL DONE", time.strftime("%H:%M"), flush=True)
