"""
Full open-weight matrix run with per-cell checkpointing.

Uses the per-question functions from run_multimodel.py (ask_baseline,
ask_augmented, ask_cot, ask_direct_tool, ask_baseline_smart, score_answer)
but orchestrates the (model, mode, benchmark) cells with checkpoint files,
so a long run can resume after interruption.

Differences from run_multimodel.py main():
- Adds the 'cot' condition for every model
- Per-cell JSON checkpoint files in ./open_checkpoints/
- --resume flag skips cells already on disk
- --models, --modes, --benches CLI flags
- Optional --include-gpt-oss flag adds gpt-oss:20b as open-weight upper bound

Usage:
    # Full Path B open run on the VM:
    python run_open_full.py --modes baseline,cot,augmented --include-gpt-oss

    # Resume after interruption:
    python run_open_full.py --resume

    # CoT only on the two reviewer-targeted benchmarks:
    python run_open_full.py --modes cot --benches geodistance,georeason
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
ROOT = Path(__file__).resolve().parents[3]  # repository root (the scripts originally ran from a folder directly under it)
sys.path.insert(0, str(ROOT))

import run_multimodel as rm  # noqa: E402

CHECKPOINT_DIR = HERE / "open_checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = HERE / "open_results.json"

DEFAULT_MODELS = [
    "qwen2.5:7b",
    "llama3.1:8b",
    "gemma2:9b",
    "mistral:7b",
    "phi3.5:3.8b",
]
TOOL_CAPABLE = {"qwen2.5:7b", "llama3.1:8b", "mistral:7b", "gpt-oss:20b"}


def cell_path(model: str, mode: str, bench: str) -> Path:
    safe = lambda s: re.sub(r"[^a-zA-Z0-9_.-]", "_", s)
    return CHECKPOINT_DIR / f"{safe(model)}__{safe(mode)}__{safe(bench)}.json"


def run_one_cell(model: str, mode: str, bench: str, questions: list[dict],
                 cap: int | None) -> dict:
    rm.CURRENT_MODEL = model
    if cap:
        questions = questions[:cap]
    details = []
    use_tools = bench in rm.TOOL_BENCHMARKS and mode == "augmented"
    use_direct = bench in rm.DIRECT_TOOL_BENCHMARKS and mode == "augmented"
    is_knowledge = bench in rm.KNOWLEDGE_BENCHMARKS
    n = len(questions)
    for i, q in enumerate(questions):
        qtext = q.get("prompt_natural", "")
        if not qtext:
            continue
        choices = q.get("choices")
        expected = q.get("ground_truth", "")
        t0 = time.time()
        if mode == "cot":
            resp = rm.ask_cot(qtext, choices)
        elif use_direct:
            resp = rm.ask_direct_tool(q)
        elif use_tools:
            resp = rm.ask_augmented(qtext, choices)
        elif is_knowledge and mode == "augmented":
            resp = rm.ask_baseline_smart(qtext, choices, bench)
        else:
            resp = rm.ask_baseline(qtext, choices)
        dt = time.time() - t0
        correct = rm.score_answer(resp.get("answer"), expected, q.get("answer_type", "text"))
        details.append({
            "question": qtext[:200],
            "question_id": q.get("id"),
            "expected": str(expected),
            "answer": (resp.get("answer") or "")[:300],
            "correct": correct,
            "error": resp.get("error"),
            "category": q.get("category", "unknown"),
            "tools_used": resp.get("tools_used", []),
            "extraction": resp.get("extraction"),
            "latency_s": round(dt, 2),
            # Full provenance for replay/audit
            "prompt_full": resp.get("prompt_full", ""),
            "raw_response": resp.get("raw_response", ""),
            "transcript": resp.get("transcript", []),
        })
        if (i + 1) % 20 == 0 or i == n - 1:
            done = i + 1
            acc = sum(1 for d in details if d["correct"]) / done * 100
            print(f"      [{done}/{n}] acc={acc:.0f}%", flush=True)
    correct = sum(1 for d in details if d["correct"])
    return {
        "evaluated": len(details),
        "correct": correct,
        "accuracy": round(100 * correct / max(len(details), 1), 1),
        "details": details,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--modes", default="baseline,cot,augmented")
    ap.add_argument("--benches",
                    default="geotopo,geodistance,geochange,georeason,geomultimodal")
    ap.add_argument("--cap", type=int, default=None,
                    help="max questions per benchmark; default = use full dataset")
    ap.add_argument("--include-gpt-oss", action="store_true",
                    help="add gpt-oss:20b as open-weight upper bound")
    ap.add_argument("--resume", action="store_true",
                    help="skip cells with existing checkpoints")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.include_gpt_oss and "gpt-oss:20b" not in models:
        models.append("gpt-oss:20b")
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    benches = [b.strip() for b in args.benches.split(",") if b.strip()]

    datasets = {}
    for f in sorted(rm.DATASETS_DIR.glob("*.json")):
        if f.stem in benches:
            datasets[f.stem] = json.load(open(f))["questions"]
            print(f"Loaded {f.stem}: {len(datasets[f.stem])} questions", flush=True)

    out = {
        "timestamp": datetime.now().isoformat(),
        "config": {"models": models, "modes": modes, "benches": benches, "cap": args.cap},
        "models": {},
    }
    started = time.time()

    for model in models:
        out["models"].setdefault(model, {m: {} for m in modes})
        for mode in modes:
            # Skip augmented for non-tool-capable models (matches paper convention)
            if mode == "augmented" and model not in TOOL_CAPABLE:
                print(f"SKIP {model:14s}  augmented  (no tool-call support)", flush=True)
                continue
            for bench in benches:
                if bench not in datasets:
                    continue
                cp = cell_path(model, mode, bench)
                if args.resume and cp.exists():
                    print(f"  RESUME  {model:14s} {mode:10s} {bench:14s}", flush=True)
                    out["models"][model][mode][bench] = json.loads(cp.read_text())
                    continue
                print(f"\n=== {model:14s} {mode:10s} {bench:14s}  "
                      f"({len(datasets[bench])} q, cap={args.cap}) ===", flush=True)
                t0 = time.time()
                cell = run_one_cell(model, mode, bench, datasets[bench], args.cap)
                cell["wall_time_s"] = round(time.time() - t0)
                cp.write_text(json.dumps(cell, indent=2))
                out["models"][model][mode][bench] = cell
                print(f"   --> {cell['accuracy']}%  ({cell['wall_time_s']}s)", flush=True)

    out["total_time_s"] = round(time.time() - started)
    OUTPUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"\nDone. {OUTPUT_FILE}  total={out['total_time_s']}s", flush=True)


if __name__ == "__main__":
    main()
