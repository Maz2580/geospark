"""
GeoSpark Multi-Model Benchmark — Academic Paper Edition

Runs all 5 benchmarks across 5 models:
- Baseline (no tools): all 5 models
- Augmented (+ GeoSpark): 3 models with tool calling support

Outputs: multimodel_results.json
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

OLLAMA_URL = "http://localhost:11434"
ROOT = Path(__file__).resolve().parents[3]  # repository root (the scripts originally ran from a folder directly under it)
DATASETS_DIR = ROOT / "geospark" / "bench" / "datasets"
OUTPUT_FILE = Path(__file__).parent / "multimodel_results.json"

# Models to test
BASELINE_MODELS = [
    "qwen2.5:7b",
    "llama3.1:8b",
    "gemma2:9b",
    "mistral:7b",
    "phi3.5:3.8b",
]

# Only models that support Ollama tool calling
AUGMENTED_MODELS = [
    "qwen2.5:7b",
    "llama3.1:8b",
    "mistral:7b",
]

# Benchmarks where tools help vs knowledge-based
TOOL_BENCHMARKS = {"geodistance"}
DIRECT_TOOL_BENCHMARKS = {"geotopo"}
KNOWLEDGE_BENCHMARKS = {"geochanage", "geomultimodal", "georeason"}

SMART_PROMPTS = {
    "geochanage": "You are a remote sensing expert. Answer questions about land use and land cover change based on your knowledge of real-world events. Be concise. If the question expects True/False, answer with ONLY True or False.",
    "geomultimodal": "You are a remote sensing analyst. Rules: NDVI >= 0.3 means vegetation IS healthy (True). NDVI < 0.3 means vegetation is NOT healthy (False). Cloud cover does NOT affect the vegetation health answer. For tree line questions: elevation above 2500m OR temperature below 0C means above the tree line (True). Answer with ONLY True or False.",
    "georeason": "You are a spatial reasoning expert. For distance chain problems: if A is Xm from B, and B is Ym from C in the SAME direction, then A is (X+Y)m from C. If OPPOSITE direction, A is |X-Y|m from C. Answer with ONLY the number.",
}

CURRENT_MODEL = "qwen2.5:7b"


def ollama_chat(messages, tools=None):
    """Call Ollama chat API."""
    payload = {"model": CURRENT_MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def ask_baseline(question, choices=None):
    """Ask LLM directly, no tools.

    Returns a dict with full provenance for replay/audit:
      answer: parsed final answer (string)
      prompt_full: complete system+user prompt
      raw_response: untruncated model reply
      transcript: list of message dicts as sent / received
      error: optional error string
    """
    prompt = question
    if choices:
        prompt += "\n\nAnswer with ONLY one of: " + ", ".join(str(c) for c in choices)
    system_prompt = "Answer spatial/geographic questions concisely. If given choices, respond with ONLY the correct choice, nothing else."
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    prompt_full = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{prompt}"
    result = ollama_chat(messages)
    if "error" in result:
        return {"answer": "", "error": result["error"],
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": list(messages)}
    raw = result.get("message", {}).get("content", "").strip()
    transcript = list(messages) + [{"role": "assistant", "content": raw}]
    return {"answer": raw, "prompt_full": prompt_full,
            "raw_response": raw, "transcript": transcript}


COT_SYSTEM = (
    "You are a careful spatial-reasoning assistant. Think through the problem "
    "step by step, showing your reasoning briefly (no more than 6 steps). "
    "Then give your final answer on a new line in the EXACT format:\n"
    "FINAL ANSWER: <answer>\n"
    "The <answer> must match the requested format: True/False, a single number "
    "(no units, no commas), or one of the listed choices verbatim."
)


def _extract_cot_answer(raw_text: str) -> tuple[str, str]:
    """Extract the FINAL ANSWER line; fall back to last non-empty line.

    Returns (answer, extraction_method).
    """
    if not raw_text:
        return "", "empty"
    m = re.search(r"FINAL\s*ANSWER\s*:\s*(.+?)(?:\n|$)", raw_text, re.IGNORECASE)
    if m:
        return m.group(1).strip(" .*`\"'"), "tagged"
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if lines:
        return lines[-1].strip(" .*`\"'"), "last_line"
    return raw_text.strip(), "raw"


def ask_cot(question, choices=None):
    """Ask LLM with explicit Chain-of-Thought prompting (no tools).

    Used to isolate the contribution of structured prompting from the
    contribution of tool augmentation, per the §5 reviewer ask.
    """
    prompt = question
    if choices:
        prompt += "\n\nAnswer with ONLY one of: " + ", ".join(str(c) for c in choices)
    messages = [
        {"role": "system", "content": COT_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    prompt_full = f"SYSTEM:\n{COT_SYSTEM}\n\nUSER:\n{prompt}"
    result = ollama_chat(messages)
    if "error" in result:
        return {"answer": "", "error": result["error"], "raw": "",
                "extraction": "error", "prompt_full": prompt_full,
                "raw_response": "", "transcript": list(messages)}
    raw = result.get("message", {}).get("content", "").strip()
    answer, method = _extract_cot_answer(raw)
    transcript = list(messages) + [{"role": "assistant", "content": raw}]
    return {"answer": answer, "raw": raw, "extraction": method,
            "prompt_full": prompt_full, "raw_response": raw,
            "transcript": transcript}


def ask_baseline_smart(question, choices=None, bench_name=""):
    """Ask LLM with a domain-specific prompt (no tools)."""
    prompt = question
    if choices:
        prompt += "\n\nAnswer with ONLY one of: " + ", ".join(str(c) for c in choices)
    system = SMART_PROMPTS.get(bench_name, "Answer concisely.")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    prompt_full = f"SYSTEM:\n{system}\n\nUSER:\n{prompt}"
    result = ollama_chat(messages)
    if "error" in result:
        return {"answer": "", "error": result["error"],
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": list(messages)}
    raw = result.get("message", {}).get("content", "").strip()
    transcript = list(messages) + [{"role": "assistant", "content": raw}]
    return {"answer": raw, "prompt_full": prompt_full,
            "raw_response": raw, "transcript": transcript}


def ask_augmented(question, choices=None):
    """Ask LLM with GeoSpark tools via Ollama tool calling."""
    sys.path.insert(0, str(ROOT))
    from geospark.mcp_servers.launcher import MCPServerLauncher

    launcher = MCPServerLauncher()
    prompt = question
    if choices:
        prompt += "\n\nAnswer with ONLY one of: " + ", ".join(str(c) for c in choices)

    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        for t in launcher.get_all_tools()
    ]

    sys_prompt = "You are a geospatial assistant with spatial computation tools. Use calculate_distance for distance questions (geocode first if needed). Use check_spatial_relationship for topology. If the question expects True/False, respond with ONLY True or False. If it expects a number, respond with ONLY the number."
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]
    prompt_full = f"SYSTEM:\n{sys_prompt}\n\nUSER:\n{prompt}"

    tools_used = []
    for _ in range(5):
        result = ollama_chat(messages, tools=tools)
        if "error" in result:
            return {"answer": "", "error": result["error"], "tools_used": tools_used,
                    "prompt_full": prompt_full, "raw_response": "",
                    "transcript": list(messages)}

        msg = result.get("message", {})
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            raw = msg.get("content", "").strip()
            transcript = list(messages) + [{"role": "assistant", "content": raw}]
            return {"answer": raw, "tools_used": tools_used,
                    "prompt_full": prompt_full, "raw_response": raw,
                    "transcript": transcript}

        messages.append(msg)
        for tc in tool_calls:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            fn_args = fn.get("arguments", {})
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}
            tool_result = launcher.handle_tool_call(fn_name, fn_args)
            tools_used.append(fn_name)
            messages.append({"role": "tool", "content": json.dumps(tool_result)})

    result = ollama_chat(messages)
    if "error" in result:
        return {"answer": "", "error": result["error"], "tools_used": tools_used,
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": list(messages)}
    raw = result.get("message", {}).get("content", "").strip()
    transcript = list(messages) + [{"role": "assistant", "content": raw}]
    return {"answer": raw, "tools_used": tools_used,
            "prompt_full": prompt_full, "raw_response": raw,
            "transcript": transcript}


def ask_direct_tool(question_data):
    """Use GeoSpark tools directly with geometries from the benchmark question.

    No LLM is called in this path; the engine receives geometries directly.
    Provenance fields (prompt_full, raw_response, transcript) describe the
    engine call rather than a chat exchange.
    """
    sys.path.insert(0, str(ROOT))
    from geospark.engine.spatial_reasoner import SpatialReasoner

    geom_a = question_data.get("geometry_a")
    geom_b = question_data.get("geometry_b")
    category = question_data.get("category", "")
    qid = question_data.get("id", "")

    prompt_full = (f"ENGINE_PATH (no LLM)\nquestion_id={qid}\ncategory={category}\n"
                   f"geometry_a={json.dumps(geom_a)}\ngeometry_b={json.dumps(geom_b)}")
    base_transcript = [{"role": "engine_input", "content": prompt_full}]

    if not geom_a or not geom_b:
        return {"answer": "", "error": "missing geometries",
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": base_transcript}

    try:
        op = category if category in (
            "contains", "intersects", "within", "touches", "crosses", "overlaps", "disjoint"
        ) else "contains"
        result = SpatialReasoner.check_relationship(geom_a, geom_b, op)
        ans = str(result)
        transcript = base_transcript + [
            {"role": "engine_call", "name": "SpatialReasoner.check_relationship",
             "args": {"op": op}, "result": result},
            {"role": "engine_output", "content": ans},
        ]
        return {"answer": ans, "tools_used": ["check_spatial_relationship"],
                "prompt_full": prompt_full, "raw_response": ans,
                "transcript": transcript}
    except Exception as e:
        return {"answer": "", "error": str(e), "tools_used": [],
                "prompt_full": prompt_full, "raw_response": "",
                "transcript": base_transcript}


def score_answer(predicted, expected, answer_type="text"):
    """Score a predicted answer against expected.

    Note: must not short-circuit on ``not expected`` because Python booleans
    ``False`` and the integer ``0`` are valid ground-truth values. Doing so
    silently auto-fails every negative-class boolean question and every
    zero-distance numeric question.
    """
    if predicted is None or expected is None:
        return False
    if isinstance(predicted, str) and predicted.strip() == "":
        return False
    pred = str(predicted).strip().lower()
    exp = str(expected).strip().lower()

    if exp in ("true", "false", "yes", "no"):
        truthy = {"true", "yes"}
        falsy = {"false", "no"}
        exp_bool = exp in truthy
        for word in pred.replace(",", " ").replace(".", " ").split():
            if word in truthy or word in falsy:
                return (word in truthy) == exp_bool
        if any(t in pred for t in truthy):
            return exp_bool
        if any(f in pred for f in falsy):
            return not exp_bool
        return False

    try:
        exp_num = float(exp)
        pred_match = re.search(r"[-+]?\d[\d,]*\.?\d*", pred.replace(",", ""))
        if pred_match:
            pred_num = float(pred_match.group().replace(",", ""))
            if exp_num == 0:
                return abs(pred_num) < 1
            return abs(pred_num - exp_num) / abs(exp_num) < 0.1
    except (ValueError, TypeError):
        pass

    return exp in pred or pred in exp


def run_single_benchmark(bench_name, questions, model, mode, max_q=None):
    """Run one benchmark for one model in one mode."""
    global CURRENT_MODEL
    CURRENT_MODEL = model

    if max_q:
        questions = questions[:max_q]

    results = []
    use_tools = bench_name in TOOL_BENCHMARKS and mode == "augmented"
    use_direct = bench_name in DIRECT_TOOL_BENCHMARKS and mode == "augmented"
    is_knowledge = bench_name in KNOWLEDGE_BENCHMARKS

    for i, q in enumerate(questions):
        qtext = q.get("prompt_natural", "")
        expected = q.get("ground_truth", "")
        answer_type = q.get("answer_type", "text")
        choices = q.get("choices")
        category = q.get("category", "unknown")

        if not qtext:
            continue

        if mode == "cot":
            response = ask_cot(qtext, choices)
        elif use_direct:
            response = ask_direct_tool(q)
        elif use_tools:
            response = ask_augmented(qtext, choices)
        elif is_knowledge and mode == "augmented":
            response = ask_baseline_smart(qtext, choices, bench_name)
        else:
            response = ask_baseline(qtext, choices)

        correct = score_answer(response.get("answer"), expected, answer_type)

        results.append({
            "question": qtext[:200],
            "question_id": q.get("id"),
            "expected": str(expected),
            "answer": response.get("answer", "")[:200],
            "correct": correct,
            "error": response.get("error"),
            "category": category,
            "tools_used": response.get("tools_used", []),
            # Full provenance for replay/audit
            "prompt_full": response.get("prompt_full", ""),
            "raw_response": response.get("raw_response", ""),
            "transcript": response.get("transcript", []),
        })

        if (i + 1) % 10 == 0 or i == len(questions) - 1:
            acc = sum(1 for r in results if r["correct"]) / len(results) * 100
            print(f"    [{i+1}/{len(questions)}] {acc:.0f}% so far", flush=True)

    return results


def main():
    max_per_bench = None
    if len(sys.argv) > 1:
        try:
            max_per_bench = int(sys.argv[1])
            print(f"Running {max_per_bench} questions per benchmark per model", flush=True)
        except ValueError:
            pass

    all_results = {
        "timestamp": datetime.now().isoformat(),
        "models": {},
    }

    # Load all datasets
    datasets = {}
    for f in sorted(DATASETS_DIR.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
        datasets[f.stem] = data.get("questions", [])
        print(f"Loaded {f.stem}: {len(datasets[f.stem])} questions", flush=True)

    start = time.time()

    # Run baseline for ALL models
    for model in BASELINE_MODELS:
        print(f"\n{'='*60}", flush=True)
        print(f"BASELINE: {model}", flush=True)
        print(f"{'='*60}", flush=True)

        model_results = {"baseline": {}, "augmented": {}}

        for bench_name, questions in datasets.items():
            print(f"  {bench_name} ({len(questions)} q)...", flush=True)
            results = run_single_benchmark(bench_name, questions, model, "baseline", max_per_bench)
            acc = sum(1 for r in results if r["correct"]) / max(len(results), 1) * 100

            categories = {}
            for r in results:
                cat = r["category"]
                if cat not in categories:
                    categories[cat] = {"total": 0, "correct": 0}
                categories[cat]["total"] += 1
                if r["correct"]:
                    categories[cat]["correct"] += 1

            model_results["baseline"][bench_name] = {
                "evaluated": len(results),
                "accuracy": round(acc, 1),
                "categories": categories,
                "details": results,
            }
            print(f"  >>> {bench_name}: {acc:.1f}%", flush=True)

        all_results["models"][model] = model_results

    # Run augmented for tool-capable models only
    for model in AUGMENTED_MODELS:
        print(f"\n{'='*60}", flush=True)
        print(f"AUGMENTED: {model}", flush=True)
        print(f"{'='*60}", flush=True)

        for bench_name, questions in datasets.items():
            print(f"  {bench_name} ({len(questions)} q)...", flush=True)
            results = run_single_benchmark(bench_name, questions, model, "augmented", max_per_bench)
            acc = sum(1 for r in results if r["correct"]) / max(len(results), 1) * 100

            categories = {}
            for r in results:
                cat = r["category"]
                if cat not in categories:
                    categories[cat] = {"total": 0, "correct": 0}
                categories[cat]["total"] += 1
                if r["correct"]:
                    categories[cat]["correct"] += 1

            all_results["models"][model]["augmented"][bench_name] = {
                "evaluated": len(results),
                "accuracy": round(acc, 1),
                "categories": categories,
                "details": results,
            }
            print(f"  >>> {bench_name}: {acc:.1f}%", flush=True)

    elapsed = time.time() - start
    all_results["total_time_s"] = round(elapsed)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nDone in {elapsed/60:.0f} minutes. Results: {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
