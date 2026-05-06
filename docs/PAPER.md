# GeoSpark — research paper summary

This page summarises what the GeoSpark v2 measurement study found and where to find every supporting artefact. It is **not the paper** — the manuscript itself is the canonical text and the source of any quote-worthy phrasing. Everything here is a tour for code readers, written in a project-doc voice rather than a paper voice.

If you want the actual manuscript (DOCX + per-cell JSONs + figure-generation code), see the bundled v2 directory under `test_academic/Paper_preparation/versions/`.

---

## What the study set out to answer

How well do current LLMs do spatial computation, and how much of the gap can be closed by giving them tools?

We built a 535-question evaluation that separates two kinds of "spatial" task:
- **computational**: geodesic distance, topological predicates, area, etc. — questions whose ground truth is a number or a Boolean produced by an actual geometry library
- **knowledge-based**: change detection, real-world geographic facts — questions that are about *what the model knows*, not what it can calculate

Each model gets every question three ways: (1) bare prompt, (2) the same prompt with an explicit "think step by step" framing and a `FINAL ANSWER:` tag, (3) the same prompt but with our MCP-exposed tools available.

## Coverage

Nine models in three buckets, locked dated snapshots so re-runs are reproducible:

- Open-weight 3.8B–9B: Qwen 2.5 7B, Llama 3.1 8B, Gemma 2 9B, Mistral 7B, Phi-3.5 3.8B (Ollama, CPU)
- Open-weight 20B: gpt-oss 20B (Ollama, CPU)
- Frontier APIs: `gpt-5.4-2026-03-05`, `claude-sonnet-4-5-20250929`, `gemini-2.5-pro` (called at temperature 0)

Where the data allows, we run every available question per benchmark — 210 questions in the topology and distance benches; 24, 36, and 55 questions respectively in the three smaller curated knowledge benches. Reported accuracies all carry a 95% Wilson interval.

## What we found, in short

**1. Numeric distance is where the gap really lives.** In the smaller tier, four out of five models bottom out at 1–5%; they emit numbers that bear no relation to the actual geodesic. Gemma 2 9B is the lone exception at 37.5%, but its right answers cluster on landmark pairs whose approximate inter-city distances are common knowledge — i.e., the model is recalling, not computing.

**2. The frontier tier is not a uniform upper bound.** On the same set of questions, GPT-5.4 sits at 95% while Gemini 2.5 Pro sits at 25%. A 70-point spread between two production frontier APIs at temperature 0 is the cleanest evidence we have that this is a per-vendor capability rather than a story about generation or scale.

**3. gpt-oss 20B is the surprise.** A free, self-hostable 20B model lands at 93.8% on numeric distance — within a percentage point of GPT-5.4. Whatever OpenAI did to gpt-oss's training mix transferred this capability cleanly into open weights.

**4. Tools homogenise the picture.** Any model that emits valid tool calls ends up somewhere in the 76–96% band on these same questions. Open-weight Qwen 7B with our tools (76%) is in the same ballpark as a frontier API plus tools (Gemini 85%, GPT-5.4 95%, Claude 96%). The tool layer essentially turns the bare-LLM vendor lottery into a deterministic engine invocation.

**5. Chain-of-thought doesn't help universally.** It boosts Claude (+18.7) and Gemini (+30) substantially, gives modest help to Qwen (+15) and Llama (+16), but actively hurts Gemma (-31, because it bypasses memorisation) and GPT-5.4 (-5, because the model is already at the ceiling and CoT adds format noise). There is no single correct prompt strategy across model vendors.

**6. Aggregate accuracy hides predicate-level model bias.** Qwen looks "moderate" on GeoTopo at 56% aggregate; per-predicate, it scores 93% on `intersects` and 3% on `disjoint`. The model is just defaulting to "yes" and the dataset's class distribution makes that look acceptable in the aggregate. Even GPT-5.4 has a 0% cell on the `touches` predicate (n=27) hidden inside its 68% aggregate.

## Headline data table

`distance_absolute` accuracy (numeric-distance subcategory of GeoDistance, n=80 per model):

| Model | Tier | Bare | CoT | + Tools |
|---|---|:---:|:---:|:---:|
| Qwen 2.5 7B | open ≤9B | 5.0% | 20.0% | **76.2%** |
| Llama 3.1 8B | open ≤9B | 5.0% | 21.2% | 7.5% |
| Gemma 2 9B | open ≤9B | 37.5% | 6.2% | — |
| Mistral 7B | open ≤9B | 2.5% | 2.5% | 0.0% |
| Phi-3.5 3.8B | open ≤9B | 1.2% | 6.2% | — |
| gpt-oss 20B | open mid | 93.8% | 93.8% | 91.2% |
| GPT-5.4 | frontier | 95.0% | 90.0% | 95.0% |
| Claude Sonnet 4.5 | frontier | 73.8% | 92.5% | **96.2%** |
| Gemini 2.5 Pro | frontier | 25.0% | 55.0% | 85.0% |

For aggregate-by-benchmark and per-predicate decompositions, see `test_academic/Paper_preparation/paper_tables.md`.

## What the experiment cost

The frontier tier ran 6,400 API calls totalling 7.2M input tokens + 723K output tokens for **$40.73**. Breakdown:

| Provider | Spent |
|---|:---:|
| OpenAI (GPT-5.4) | $19.55 |
| Anthropic (Claude Sonnet 4.5) | $18.22 |
| Google (Gemini 2.5 Pro) | $2.97 |

Every call's tokens, latency, and dollar cost are appended to `test_academic/frontier_cost_ledger.jsonl` as it happens. The open-weight tier ran on a CPU VM via Ollama for ~15 hours; no per-call cost.

## How to verify any number in the paper

The point of shipping per-cell JSONs is that you don't need to trust us — you can pull any cell out of the checkpoint files and recompute. Example:

```python
import json
fp = "test_academic/frontier_checkpoints/openai__gpt-5.4-2026-03-05__baseline__geodistance.json"
data = json.load(open(fp))
numeric = [r for r in data["details"] if r["category"] == "distance_absolute"]
hits = sum(1 for r in numeric if r["correct"])
print(f"{hits}/{len(numeric)} = {100 * hits / len(numeric):.1f}%")
# 76/80 = 95.0%
```

Each detail entry contains the question text, the expected answer, the model's actual response, the parsed correctness flag, and (for tool-augmented runs) the trace of which tools were invoked and in what order.

## How to re-run the experiment

The two runners we wrote for this study (also bundled with the v2 paper):

```bash
# Open-weight tier — free, ~15 hours wall-clock on a multi-core CPU
# Pulls model weights via Ollama; resumable per-cell
python test_academic/run_open_full.py --include-gpt-oss --resume

# Frontier tier — needs OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY
# Has a hard --budget cap that aborts the run if API spend exceeds it
python test_academic/run_frontier.py \
    --providers openai,anthropic,gemini \
    --modes baseline,cot,augmented \
    --cap 210 --budget 50 --resume
```

Both scripts write per-(model, mode, benchmark) JSON checkpoints. `--resume` skips cells that already exist on disk, so an interrupted run continues without losing progress.

## A few methodology notes worth flagging

These are the choices that affect how reproducible the paper is, in case you're considering replicating it:

- **Locked dated model snapshots** for the frontier tier. We avoid floating aliases like `gpt-5.4` because in 2027 those may silently re-route to a different model.
- **Temperature 0 everywhere.** Open-weight models via Ollama default sampling; frontier models via the official SDKs at temp 0 where supported.
- **Claude Opus 4.7 is deliberately not benchmarked.** That's the model we drafted the manuscript on; self-benchmarking would be methodologically suspicious. Claude Sonnet 4.5 stands in as the production-snapshot Sonnet.
- **Per-subcategory reporting throughout.** Aggregating GeoTopo would hide the per-predicate bias; aggregating GeoDistance would mix Boolean threshold questions with numeric distance computation. We always show the breakdown.
- **A scoring bug we found and fixed.** The v1 academic-paper harness `test_academic/run_multimodel.py` had a `if not predicted or not expected: return False` short-circuit that auto-failed every Boolean `False` ground truth. The published library scorer (`geospark/bench/scorer.py`) was not affected. Full audit lives in the v2 bundle's `METHODOLOGY_AUDIT.md`.

## Citation (placeholder until arXiv ID is assigned)

```bibtex
@misc{geospark_v2_2026,
  title         = {GeoSpark: Ground-Truth Spatial Tool Augmentation for Large Language Models},
  author        = {Ghasemi Tootkaboni, Mazdak},
  year          = {2026},
  eprint        = {arXiv:XXXX.XXXXX},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  note          = {GeoSpark v0.5.1; \url{https://github.com/Maz2580/geospark}},
}
```

We will update this page with the arXiv identifier once the preprint is posted.
