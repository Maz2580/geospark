"""Benchmark 2 repeats of Qwen 3.5 4B and Phi-4-mini 3.8B (see repeats_2026-11/PLAN.md and README.md).

Three repeats, without and with tools, same sample, prompts, scoring and token limit as livebench.py; replies are
streamed (as in the November reruns). Every answer is saved under run1/, run2/, run3/; a run resumes if stopped.
Run in the GeoSpark venv with WORKSTATION_LLM_URL and WORKSTATION_LLM_API_KEY set, from this folder:
    python repeat_streaming.py
Only the two folder paths below differ from the copy that produced repeats_2026-11/.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx  # noqa: F401  (used through livebench's client)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import livebench  # noqa: E402

OUT = Path(__file__).resolve().parent / "repeats_2026-11"
MODELS = ("qwen3.5:4b", "phi4-mini:3.8b")
failures = 0


def stream_chat(client, base, model, messages, tools, prov):
    """livebench.chat with a streamed reply (same body otherwise); stops after 3 failures in a row."""
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
                    c = calls.setdefault(tc.get("index", len(calls)),
                                         {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
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


livebench.chat = stream_chat
for rep in (1, 2, 3):
    out = OUT / f"run{rep}"
    out.mkdir(parents=True, exist_ok=True)
    livebench.OUT, livebench.LEDGER = out, out / "ledger.json"
    for model in MODELS:
        for mode in ("bare", "tools"):
            print(f"== run{rep} {model} {mode} {time.strftime('%H:%M')}", flush=True)
            livebench.run(argparse.Namespace(provider="workstation", model=model, mode=mode, distance=20, per_predicate=3))
print("ALL DONE", time.strftime("%H:%M"), flush=True)
