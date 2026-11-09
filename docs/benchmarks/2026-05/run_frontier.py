"""
GeoSpark Frontier-Model Benchmark Runner.

Runs the same 5 benchmarks as run_multimodel.py but against frontier
commercial APIs (OpenAI / Anthropic / Google) via their native SDKs and
native tool-call schemas.

Output JSON has the same shape as multimodel_results.json so downstream
figure scripts work unchanged. A separate cost ledger (JSONL) tracks
per-call token usage and dollar cost.

Per-cell checkpoint files in CHECKPOINT_DIR allow resume after crash.

Usage:
    # Dry-run: 5 questions per benchmark, baseline only
    python run_frontier.py --providers openai --modes baseline --cap 5

    # Full run on all three providers, n=50 per bench, all 3 modes
    python run_frontier.py --providers openai,anthropic,gemini \
        --modes baseline,cot,augmented --cap 50

    # Resume an aborted run
    python run_frontier.py --resume
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]  # repository root (the scripts originally ran from a folder directly under it)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# Reuse scorer + CoT extraction + dataset paths from the open-model runner.
from run_multimodel import (  # noqa: E402
    COT_SYSTEM,
    DATASETS_DIR,
    _extract_cot_answer,
    score_answer,
)
from geospark.mcp_servers.launcher import MCPServerLauncher  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_FILE = HERE / "frontier_results.json"
COST_LEDGER = HERE / "frontier_cost_ledger.jsonl"
CHECKPOINT_DIR = HERE / "frontier_checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)

# Pricing per million tokens (USD). Override via env if rates change.
# Values reflect public pricing pages for the locked dated snapshots.
PRICING = {
    "gpt-5.4-2026-03-05":          (10.00, 30.00),  # placeholder; override via env
    "claude-sonnet-4-5-20250929":  ( 3.00, 15.00),  # Sonnet tier
    "gemini-2.5-pro":              ( 1.25,  5.00),  # under 200k token prompt
}
# Allow env override: GEOSPARK_PRICE_<MODEL_SAFE>=in,out (per M tokens)
for mid in list(PRICING):
    safe = mid.replace("-", "_").replace(".", "_").upper()
    raw = os.getenv(f"GEOSPARK_PRICE_{safe}")
    if raw:
        try:
            i, o = (float(x) for x in raw.split(","))
            PRICING[mid] = (i, o)
        except Exception:
            pass

# Provider -> default model id (locked dated snapshots for arXiv reproducibility)
DEFAULT_MODEL_FOR = {
    "openai":    "gpt-5.4-2026-03-05",
    "anthropic": "claude-sonnet-4-5-20250929",
    "gemini":    "gemini-2.5-pro",
}

# Same benchmark-type taxonomy as run_multimodel.py
TOOL_BENCHMARKS = {"geodistance"}
DIRECT_TOOL_BENCHMARKS = {"geotopo"}  # bypass LLM, hit engine directly
KNOWLEDGE_BENCHMARKS = {"geochanage", "geomultimodal", "georeason"}


# ---------------------------------------------------------------------------
# Cost ledger
# ---------------------------------------------------------------------------

@dataclass
class CostEvent:
    timestamp: str
    provider: str
    model: str
    benchmark: str
    mode: str
    in_tokens: int
    out_tokens: int
    usd: float

    def write(self) -> None:
        with COST_LEDGER.open("a") as fh:
            fh.write(json.dumps(self.__dict__) + "\n")


@dataclass
class CostTotals:
    by_provider: dict[str, float] = field(default_factory=dict)
    total_usd: float = 0.0
    total_calls: int = 0

    def add(self, evt: CostEvent) -> None:
        self.total_usd += evt.usd
        self.total_calls += 1
        self.by_provider[evt.provider] = self.by_provider.get(evt.provider, 0) + evt.usd


def calc_cost(model: str, in_t: int, out_t: int) -> float:
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return (in_t / 1_000_000) * pin + (out_t / 1_000_000) * pout


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------

class Provider(ABC):
    name: str = "base"

    def __init__(self, model_id: str):
        self.model_id = model_id

    @abstractmethod
    def chat(self, system: str, user: str, max_out: int = 800) -> tuple[str, int, int, list[dict]]:
        """Return (text, input_tokens, output_tokens, transcript)."""

    @abstractmethod
    def chat_with_tools(
        self, system: str, user: str, mcp_tools: list[dict], max_iters: int = 5
    ) -> tuple[str, list[str], int, int, list[dict]]:
        """Return (text, tools_used, input_tokens, output_tokens, transcript).

        ``transcript`` is a JSON-serialisable list of role/content dicts that
        records the full system/user/assistant/tool exchange for replay/audit.
        """


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model_id: str):
        super().__init__(model_id)
        from openai import OpenAI
        self._client = OpenAI()

    def chat(self, system, user, max_out=800):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        r = self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_completion_tokens=max_out,
        )
        text = (r.choices[0].message.content or "").strip()
        transcript = list(messages) + [{"role": "assistant", "content": text}]
        return text, r.usage.prompt_tokens, r.usage.completion_tokens, transcript

    def chat_with_tools(self, system, user, mcp_tools, max_iters=5):
        # OpenAI / Ollama tool schema is identical
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in mcp_tools
        ]
        launcher = MCPServerLauncher()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tools_used: list[str] = []
        in_t = out_t = 0
        for _ in range(max_iters):
            r = self._client.chat.completions.create(
                model=self.model_id, messages=messages, tools=oai_tools,
                max_completion_tokens=800,
            )
            in_t += r.usage.prompt_tokens
            out_t += r.usage.completion_tokens
            msg = r.choices[0].message
            if not msg.tool_calls:
                text = (msg.content or "").strip()
                messages.append({"role": "assistant", "content": text})
                return text, tools_used, in_t, out_t, messages
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_result = launcher.handle_tool_call(tc.function.name, args)
                tools_used.append(tc.function.name)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(tool_result)})
        return "", tools_used, in_t, out_t, messages


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model_id: str):
        super().__init__(model_id)
        import anthropic
        self._client = anthropic.Anthropic()

    def chat(self, system, user, max_out=800):
        messages = [{"role": "user", "content": user}]
        r = self._client.messages.create(
            model=self.model_id, max_tokens=max_out, system=system,
            messages=messages,
        )
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        transcript = ([{"role": "system", "content": system}]
                      + list(messages)
                      + [{"role": "assistant", "content": text}])
        return text, r.usage.input_tokens, r.usage.output_tokens, transcript

    def chat_with_tools(self, system, user, mcp_tools, max_iters=5):
        # Anthropic tool schema: {name, description, input_schema}
        ant_tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
            for t in mcp_tools
        ]
        launcher = MCPServerLauncher()
        messages = [{"role": "user", "content": user}]
        tools_used: list[str] = []
        in_t = out_t = 0
        for _ in range(max_iters):
            r = self._client.messages.create(
                model=self.model_id, max_tokens=800, system=system,
                messages=messages, tools=ant_tools,
            )
            in_t += r.usage.input_tokens
            out_t += r.usage.output_tokens
            tool_uses = [b for b in r.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in r.content if b.type == "text").strip()
                messages.append({"role": "assistant", "content": text})
                transcript = [{"role": "system", "content": system}] + list(messages)
                return text, tools_used, in_t, out_t, transcript
            messages.append({"role": "assistant", "content": [b.model_dump() for b in r.content]})
            tool_results = []
            for tu in tool_uses:
                tool_result = launcher.handle_tool_call(tu.name, dict(tu.input))
                tools_used.append(tu.name)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id,
                                     "content": json.dumps(tool_result)})
            messages.append({"role": "user", "content": tool_results})
        transcript = [{"role": "system", "content": system}] + list(messages)
        return "", tools_used, in_t, out_t, transcript


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model_id: str):
        super().__init__(model_id)
        from google import genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._genai = genai

    @staticmethod
    def _serialize_part(p) -> dict:
        """Best-effort plain-dict serialization of a Gemini Part."""
        out: dict = {}
        if getattr(p, "text", None):
            out["text"] = p.text
        fc = getattr(p, "function_call", None)
        if fc:
            out["function_call"] = {"name": fc.name, "args": dict(fc.args) if fc.args else {}}
        fr = getattr(p, "function_response", None)
        if fr:
            try:
                resp = dict(fr.response) if fr.response else {}
            except Exception:
                resp = {"_repr": str(fr.response)}
            out["function_response"] = {"name": fr.name, "response": resp}
        return out

    def _serialize_content(self, c) -> dict:
        return {"role": getattr(c, "role", "?"),
                "parts": [self._serialize_part(p) for p in (c.parts or [])]}

    def chat(self, system, user, max_out=800):
        from google.genai import types as gtypes
        r = self._client.models.generate_content(
            model=self.model_id,
            contents=user,
            config=gtypes.GenerateContentConfig(
                system_instruction=system, max_output_tokens=max_out, temperature=0,
            ),
        )
        text = (getattr(r, "text", None) or "").strip()
        u = getattr(r, "usage_metadata", None)
        in_t = (getattr(u, "prompt_token_count", 0) or 0) if u else 0
        out_t = (getattr(u, "candidates_token_count", 0) or 0) if u else 0
        transcript = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": text},
        ]
        return text, in_t, out_t, transcript

    def chat_with_tools(self, system, user, mcp_tools, max_iters=5):
        from google.genai import types as gtypes
        gemini_tools = gtypes.Tool(function_declarations=[
            gtypes.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters=t["inputSchema"],
            )
            for t in mcp_tools
        ])
        launcher = MCPServerLauncher()
        contents = [gtypes.Content(role="user", parts=[gtypes.Part(text=user)])]
        tools_used: list[str] = []
        in_t = out_t = 0
        for _ in range(max_iters):
            r = self._client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system, tools=[gemini_tools],
                    max_output_tokens=800, temperature=0,
                ),
            )
            u = getattr(r, "usage_metadata", None)
            in_t += (getattr(u, "prompt_token_count", 0) or 0) if u else 0
            out_t += (getattr(u, "candidates_token_count", 0) or 0) if u else 0
            cand = (r.candidates or [None])[0]
            parts = getattr(cand.content, "parts", []) if cand and cand.content else []
            fn_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not fn_calls:
                text = (getattr(r, "text", None) or "").strip()
                contents.append(cand.content)
                transcript = ([{"role": "system", "content": system}]
                              + [self._serialize_content(c) for c in contents])
                return text, tools_used, in_t, out_t, transcript
            contents.append(cand.content)
            response_parts = []
            for fc in fn_calls:
                args = dict(fc.args) if fc.args else {}
                tool_result = launcher.handle_tool_call(fc.name, args)
                tools_used.append(fc.name)
                response_parts.append(gtypes.Part.from_function_response(
                    name=fc.name, response={"result": tool_result},
                ))
            contents.append(gtypes.Content(role="user", parts=response_parts))
        transcript = ([{"role": "system", "content": system}]
                      + [self._serialize_content(c) for c in contents])
        return "", tools_used, in_t, out_t, transcript


PROVIDER_REGISTRY = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


# ---------------------------------------------------------------------------
# Question runner
# ---------------------------------------------------------------------------

BASELINE_SYSTEM = (
    "Answer spatial/geographic questions concisely. If given choices, respond "
    "with ONLY the correct choice, nothing else."
)
AUGMENTED_SYSTEM = (
    "You are a geospatial assistant with spatial computation tools. Use "
    "calculate_distance for distance questions (geocode first if needed). "
    "Use check_spatial_relationship for topology. If the question expects "
    "True/False, respond with ONLY True or False. If it expects a number, "
    "respond with ONLY the number."
)


def _ask_direct_tool(q: dict) -> dict:
    """Engine-only path for GeoTopo augmented (bypass LLM)."""
    from geospark.engine.spatial_reasoner import SpatialReasoner
    geom_a = q.get("geometry_a"); geom_b = q.get("geometry_b")
    cat = q.get("category", "")
    qid = q.get("id", "")
    prompt_full = (f"ENGINE_PATH (no LLM)\nquestion_id={qid}\ncategory={cat}\n"
                   f"geometry_a={json.dumps(geom_a)}\ngeometry_b={json.dumps(geom_b)}")
    base_transcript = [{"role": "engine_input", "content": prompt_full}]
    if not geom_a or not geom_b:
        return {"answer": "", "error": "missing geometries",
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": base_transcript}
    try:
        op = cat if cat in (
            "contains", "intersects", "within", "touches", "crosses", "overlaps", "disjoint"
        ) else "contains"
        r = SpatialReasoner.check_relationship(geom_a, geom_b, op)
        ans = str(r)
        transcript = base_transcript + [
            {"role": "engine_call", "name": "SpatialReasoner.check_relationship",
             "args": {"op": op}, "result": r},
            {"role": "engine_output", "content": ans},
        ]
        return {"answer": ans, "tools_used": ["check_spatial_relationship"],
                "prompt_full": prompt_full, "raw_response": ans,
                "transcript": transcript}
    except Exception as e:
        return {"answer": "", "error": str(e), "tools_used": [],
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": base_transcript}


def run_question(provider: Provider, q: dict, mode: str, bench: str,
                 mcp_tools: list[dict]) -> tuple[dict, int, int]:
    qtext = q.get("prompt_natural", "")
    choices = q.get("choices")
    prompt = qtext + (
        "\n\nAnswer with ONLY one of: " + ", ".join(str(c) for c in choices) if choices else ""
    )

    if mode == "augmented" and bench in DIRECT_TOOL_BENCHMARKS:
        out = _ask_direct_tool(q)
        return out, 0, 0  # engine path, no LLM tokens

    try:
        if mode == "baseline":
            text, in_t, out_t, transcript = provider.chat(BASELINE_SYSTEM, prompt)
            return ({"answer": text,
                     "prompt_full": f"SYSTEM:\n{BASELINE_SYSTEM}\n\nUSER:\n{prompt}",
                     "raw_response": text, "transcript": transcript},
                    in_t, out_t)
        elif mode == "cot":
            text, in_t, out_t, transcript = provider.chat(COT_SYSTEM, prompt)
            ans, method = _extract_cot_answer(text)
            return ({"answer": ans, "raw": text, "extraction": method,
                     "prompt_full": f"SYSTEM:\n{COT_SYSTEM}\n\nUSER:\n{prompt}",
                     "raw_response": text, "transcript": transcript},
                    in_t, out_t)
        elif mode == "augmented" and bench in TOOL_BENCHMARKS:
            text, used, in_t, out_t, transcript = provider.chat_with_tools(
                AUGMENTED_SYSTEM, prompt, mcp_tools)
            return ({"answer": text, "tools_used": used,
                     "prompt_full": f"SYSTEM:\n{AUGMENTED_SYSTEM}\n\nUSER:\n{prompt}",
                     "raw_response": text, "transcript": transcript},
                    in_t, out_t)
        elif mode == "augmented" and bench in KNOWLEDGE_BENCHMARKS:
            # Knowledge benchmarks: use AUGMENTED_SYSTEM but no tools (mirrors the
            # smart-prompt path in run_multimodel.py — augmentation = better prompt).
            text, in_t, out_t, transcript = provider.chat(AUGMENTED_SYSTEM, prompt)
            return ({"answer": text,
                     "prompt_full": f"SYSTEM:\n{AUGMENTED_SYSTEM}\n\nUSER:\n{prompt}",
                     "raw_response": text, "transcript": transcript},
                    in_t, out_t)
        else:
            text, in_t, out_t, transcript = provider.chat(BASELINE_SYSTEM, prompt)
            return ({"answer": text,
                     "prompt_full": f"SYSTEM:\n{BASELINE_SYSTEM}\n\nUSER:\n{prompt}",
                     "raw_response": text, "transcript": transcript},
                    in_t, out_t)
    except Exception as e:
        return {"answer": "", "error": str(e)[:300],
                "prompt_full": "", "raw_response": "", "transcript": []}, 0, 0


def run_cell(provider: Provider, bench: str, mode: str, questions: list[dict],
             cap: int | None, totals: CostTotals) -> dict:
    """Run one (provider, mode, benchmark) cell. Returns cell summary dict."""
    if cap:
        questions = questions[:cap]
    mcp_tools = MCPServerLauncher().get_all_tools() if mode == "augmented" else []
    details: list[dict] = []
    cell_in = cell_out = 0
    for i, q in enumerate(questions):
        t0 = time.time()
        resp, in_t, out_t = run_question(provider, q, mode, bench, mcp_tools)
        dt = time.time() - t0
        cell_in += in_t; cell_out += out_t
        cost_evt = CostEvent(
            timestamp=datetime.now().isoformat(), provider=provider.name,
            model=provider.model_id, benchmark=bench, mode=mode,
            in_tokens=in_t, out_tokens=out_t,
            usd=calc_cost(provider.model_id, in_t, out_t),
        )
        cost_evt.write()
        totals.add(cost_evt)
        expected = q.get("ground_truth", "")
        correct = score_answer(resp.get("answer"), expected, q.get("answer_type", "text"))
        details.append({
            "question": q.get("prompt_natural", "")[:200],
            "question_id": q.get("id"),
            "expected": str(expected),
            "answer": (resp.get("answer") or "")[:300],
            "correct": correct,
            "error": resp.get("error"),
            "category": q.get("category", "unknown"),
            "tools_used": resp.get("tools_used", []),
            "extraction": resp.get("extraction"),
            "latency_s": round(dt, 2),
            "in_tokens": in_t, "out_tokens": out_t,
            # Full provenance for replay/audit
            "prompt_full": resp.get("prompt_full", ""),
            "raw_response": resp.get("raw_response", ""),
            "transcript": resp.get("transcript", []),
        })
        if (i + 1) % 5 == 0 or i == len(questions) - 1:
            n_done = i + 1
            acc = sum(1 for d in details if d["correct"]) / n_done * 100
            print(f"      [{n_done}/{len(questions)}] acc={acc:.0f}%  "
                  f"cell_cost=${calc_cost(provider.model_id, cell_in, cell_out):.4f}  "
                  f"run_total=${totals.total_usd:.2f}", flush=True)
    correct = sum(1 for d in details if d["correct"])
    return {
        "evaluated": len(details),
        "correct": correct,
        "accuracy": round(100 * correct / max(len(details), 1), 1),
        "in_tokens": cell_in, "out_tokens": cell_out,
        "cost_usd": round(calc_cost(provider.model_id, cell_in, cell_out), 4),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Orchestration with checkpoint resume
# ---------------------------------------------------------------------------

def cell_path(provider: str, model: str, mode: str, bench: str) -> Path:
    safe = lambda s: re.sub(r"[^a-zA-Z0-9_.-]", "_", s)
    return CHECKPOINT_DIR / f"{safe(provider)}__{safe(model)}__{safe(mode)}__{safe(bench)}.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="openai",
                    help="comma-separated: openai,anthropic,gemini")
    ap.add_argument("--modes", default="baseline,cot,augmented")
    ap.add_argument("--cap", type=int, default=50,
                    help="max questions per benchmark (default 50)")
    ap.add_argument("--benches", default="geotopo,geodistance,geochange,georeason,geomultimodal",
                    help="comma-separated benchmark names")
    ap.add_argument("--budget", type=float, default=60.0,
                    help="abort once total spend exceeds this many USD")
    ap.add_argument("--resume", action="store_true",
                    help="skip cells with existing checkpoint files")
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    benches = [b.strip() for b in args.benches.split(",") if b.strip()]

    # Load .env
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # Load datasets
    datasets = {}
    for f in sorted(DATASETS_DIR.glob("*.json")):
        if f.stem in benches:
            datasets[f.stem] = json.load(open(f))["questions"]
            print(f"Loaded {f.stem}: {len(datasets[f.stem])} questions")
    print()

    totals = CostTotals()
    aborted = False

    # Initialize result skeleton
    out = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "providers": providers, "modes": modes, "benches": benches,
            "cap": args.cap, "budget_usd": args.budget,
            "model_ids": {p: DEFAULT_MODEL_FOR[p] for p in providers},
            "pricing_per_M": {DEFAULT_MODEL_FOR[p]: PRICING.get(DEFAULT_MODEL_FOR[p]) for p in providers},
        },
        "models": {},
    }

    for prov_name in providers:
        if aborted:
            break
        model_id = DEFAULT_MODEL_FOR[prov_name]
        provider = PROVIDER_REGISTRY[prov_name](model_id)
        print(f"\n{'='*70}\nPROVIDER {prov_name}  model={model_id}\n{'='*70}")
        out["models"].setdefault(model_id, {m: {} for m in modes})
        for mode in modes:
            for bench in benches:
                if bench not in datasets:
                    continue
                cp = cell_path(prov_name, model_id, mode, bench)
                if args.resume and cp.exists():
                    print(f"  RESUME  {mode:10s} {bench:14s} (loading {cp.name})")
                    cell = json.loads(cp.read_text())
                    out["models"][model_id][mode][bench] = cell
                    continue
                if totals.total_usd >= args.budget:
                    print(f"  ABORT — budget ${args.budget:.2f} exceeded "
                          f"(spent ${totals.total_usd:.2f})")
                    aborted = True
                    break
                print(f"  RUN  {mode:10s} {bench:14s}  "
                      f"({len(datasets[bench])} q, cap={args.cap})")
                cell = run_cell(provider, bench, mode, datasets[bench], args.cap, totals)
                cp.write_text(json.dumps(cell, indent=2))
                out["models"][model_id][mode][bench] = cell
            if aborted:
                break

    out["totals"] = {
        "by_provider": totals.by_provider,
        "total_usd": round(totals.total_usd, 4),
        "total_calls": totals.total_calls,
        "aborted_at_budget": aborted,
    }
    OUTPUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")
    print(f"Total spend: ${totals.total_usd:.2f}  Calls: {totals.total_calls}")


if __name__ == "__main__":
    main()
