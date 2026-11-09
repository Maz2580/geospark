# Benchmark 2 repeat runs: Qwen 3.5 4B and Phi-4-mini 3.8B

Written 2026-11-09 21:36 AEDT, before any run.

Why: the per-question answers of the October 2026 runs of these two models were kept only in a temporary
folder and were lost on a restart; only their scores survive (docs/benchmarks/2026-10/results_summary.json,
paper Table 5). The answers are needed for the Benchmark 2 panel of Figure 6.

Plan, fixed in advance:
- Three repeats of each model, without and with tools, on the full Benchmark 2 sample (seed 7: 20 distance and
  18 topology questions), on the same workstation, with livebench.py's prompts, scoring and 2,000-token limit.
  Replies are streamed (as in the November reruns of Qwen 3.5 9B and Gemma 4 12B); nothing else differs.
- All three repeats are reported, whatever they show. None is selected or discarded.
- Each repeat is saved in run1/, run2/, run3/ (one JSON file per model and mode, every answer included).
