# Repeat runs of two small models, November 2026

The October runs of Qwen 3.5 4B and Phi-4-mini 3.8B saved only their scores (`../results_summary.json`), not the
text of each answer. To have the answers, both models were run three more times on 9 November 2026, on the same
workstation and the same question sample as `../livebench.py` (seed 7: 20 distance and 18 topology questions),
without and with GeoSpark's tools. The one difference is that replies are streamed, as in `../reruns_2026-11/`.

`PLAN.md` was written before the first run. It fixed what would be reported: all three runs, none dropped.

Correct answers, distance (of 20) and topology (of 18):

| Model | Tools | Run 1 | Run 2 | Run 3 | October (`results_summary.json`) |
|---|---|---|---|---|---|
| Qwen 3.5 4B | no | 19, 17 | 20, 18 | 19, 17 | 18, 18 |
| Qwen 3.5 4B | yes | 19, 16 | 20, 17 | 19, 17 | 20, 18 |
| Phi-4-mini 3.8B | no | 2, 8 | 2, 9 | 4, 4 | 3, 9 |
| Phi-4-mini 3.8B | yes | 4, 7 | 5, 9 | 3, 8 | 4, 9 |

With tools, Qwen 3.5 4B called them on all 38 questions in every run; Phi-4-mini never called them.
`results_summary.json` keeps the October scores. These runs show how far a single run can move.

| File | What it is |
|---|---|
| `run1/`, `run2/`, `run3/` | One file per model and mode: each answer's text, tool calls, time and whether it was scored correct |
| `run_log.txt` | Console output of the three runs |
| `PLAN.md` | The plan, written before running |
| `SHA256SUMS.txt` | Checksums of the files above (`shasum -a 256 -c SHA256SUMS.txt`) |
| `../repeat_streaming.py` | The script that ran them |
