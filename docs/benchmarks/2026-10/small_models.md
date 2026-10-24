# Small local models with GeoSpark's tools: what goes wrong, and what now catches it

Four open models served from a local workstation (Qwen 3.5 4B and 9B, gpt-oss 20B, Gemma 4 12B)
answered 10 questions through GeoSpark's full tool set and its own answer checks, exactly as Ask runs
them: distances between named places, a mountain's elevation, containment, a GNSS height to AHD, a
GDA94 to GDA2020 conversion, a buffer area, a "which is closer" comparison. Correct answers were computed
with GeoSpark's verified tools. Run October 2026; harness `smallmodel/eval_small.py` (`EVAL_BASE_URL=… python eval_small.py MODEL…`), scores `smallmodel/scores.json`.

What we were measuring is not only how often an answer is right, but how often a wrong one still
says `ok` (a silent error), how often it is caught (`partial` or `cannot_answer`), and how often a
right one is flagged (a false alarm).

## What the first runs found, and what changed

| Found | Change |
|---|---|
| The tools were called, then the model returned **no text**, marked `ok` (4 of 30 answers) | An empty answer is `cannot_answer` |
| A 4B model always sent one point as `[x, y]`; the tool failed with `'float' object is not subscriptable` and the model began **inventing EPSG codes** | `transform_coordinates` accepts one point and says plainly what shape it wants |
| Answers state numbers the tools never returned (a 3.14 km² buffer called "3,137 km²"; an area the model computed itself) | Every quantity in an answer must trace to a tool result (unit changes, rounding, sums and differences allowed) or the answer is `partial` |
| Space-grouped thousands ("2 726 638 m") were misread, flagging correct answers | Read as one number |
| A stated precision ("rounded to 0.001 m") was flagged | Precision phrases are not quantities |
| "Sunshine Coast is closer" after measuring 90.5 km to it and 70.6 km to the Gold Coast | Comparisons are checked against the measured distances; answers that name two places as "closer" are flagged |
| **"Gold Coast" geocoded to Ghana**, 16,549 km from Brisbane, with no ambiguity warning (on a server without a preferred country) | Two places in one question are read together: a close candidate in the other place's country is used, with a warning; an operator's preferred country is never overridden |

## Final runs (after the changes)

Three runs of 40 answers (120 in total):

| Model | Right, `ok` | Wrong, caught | **Wrong, silent** | Right, flagged |
|---|:---:|:---:|:---:|:---:|
| Qwen 3.5 4B | 28 | 2 (no answer text) | 0 | 0 |
| Qwen 3.5 9B | 29 | 0 | 0 | 1 (precision phrase; since fixed) |
| gpt-oss 20B | 28 | 1 (no answer text) | 0 | 1 (computed an area itself: right number, unchecked) |
| Gemma 4 12B | 29 | 0 | 1 (the Ghana geocode; since fixed) | 0 |

The two remaining non-clean results in the third run were both handled as intended: an empty reply
(`cannot_answer`) and an area the model calculated without the tool (`partial`). Not covered: other
question types, other prompts, and these models' behaviour under a busy workstation (timeouts are
reported as errors, not scored).
