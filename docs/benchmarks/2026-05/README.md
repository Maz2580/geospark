# Nine-model evaluation, May 2026 ("GeoSpark Bench v2")

The scripts and the full per-question output behind the "GeoSpark Bench v2" results in the main README.
They were run on 5 and 6 May 2026 against the code at commit
[`2760f89`](https://github.com/Maz2580/geospark/tree/2760f8985d65ec378a7de65bebcecaa5c3603385).

| File | What it is |
|---|---|
| `run_multimodel.py` | Shared harness: the three conditions (direct answer, step-by-step prompt, GeoSpark tools through the MCP servers), the Ollama client and the scorer (`score_answer`) |
| `run_open_full.py` | Runs the six open-weight models through Ollama with its default sampling; tools only for the models whose Ollama build supports tool calling |
| `run_frontier.py` | Runs GPT-5.4, Claude Sonnet 4.5 and Gemini 2.5 Pro through their own SDKs; Gemini is called at temperature 0, the other two with the providers' default sampling |
| `open_checkpoints/`, `frontier_checkpoints/` | One file per model, condition and benchmark: every question as sent, the expected answer, the model's answer, whether it was scored correct, and the tools it called |
| `frontier_cost_ledger.jsonl` | One line per frontier API call (6,400 calls; tokens and US$, about US$41 in total). One line is truncated and is skipped when totalling |
| `tables_from_records.py` | Rebuilds the result counts from the files above, with no model calls |

How the questions were asked and scored:

- Each question was sent in its plain-language form (`prompt_natural` in the datasets): landmarks and cities by
  name, with no coordinate geometry attached. Under the tools condition the model looks the places up itself.
- A numeric answer counts as correct when the first number in the reply is within 10% of the reference
  distance; a true/false answer is read from the first "true"/"false" (or "yes"/"no") in the reply.
- Topology questions under the tools condition go straight to the engine with the stored geometries, so those
  cells check the engine rather than the model.

To rerun: in a virtual environment with `pip install -e ".[dev,mcp]"`, start Ollama for the open models and set
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` (or put them in `.env` at the repository root) for
the frontier models, then `python docs/benchmarks/2026-05/run_open_full.py` and
`python docs/benchmarks/2026-05/run_frontier.py`. Both resume from the checkpoint files, so delete or move
those first to start fresh. The scripts are as they were run, except that they now find the repository root
three folders up (they originally lived in a folder directly under it). For the code exactly as it was in May,
check out commit `2760f89` and copy this folder into it.
