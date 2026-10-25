# Re-check with current models, October 2026

Two tests, run on 2026-10-24. Scores are in `results_summary.json`; the write-up is in the main
README under "Re-check with current models (October 2026)".

| File | What it is |
|---|---|
| `livebench.py` | GeoSpark Bench sample (20 numeric distance + 18 topology questions, seed 7), bare or with GeoSpark's tools |
| `make_datum_set.py`, `datum_questions.json` | 21 Australian datum and height questions; official answers from PROJ's most accurate EPSG operations and AUSGeoid2020 |
| `make_grid_set.py`, `grid_questions.json` | 11 questions that need national grids: OSTN15, OSGM15, NZGeoid2016, GEOID18, NADCON |
| `datum_run.py` | Runs a question set on a model (bare, or `--tools` with `transform_coordinates` and `convert_height`) and scores the error in metres |
| `results_summary.json` | Per-model scores, errors, tool use and cost (no model text) |
| `agency_checks.md` | GeoSpark's answers compared with Geoscience Australia, Ordnance Survey, LINZ, NGS and 2,000 Victorian survey marks; and `layer check` on real data |
| `fairness.md` | Whether the gap survives code execution, high effort and repeated runs; and AI-written GIS code |
| `results_datum_all_runs.json` | Every datum run's grades and errors (bare, tools, code execution, repeats) |
| `sun_horizon.md`, `sun_horizon/` | Sun position and sunrise against NREL SPA; terrain horizons against PVGIS |
| `small_models.md`, `smallmodel/` | Small local models through Ask's tool loop: silent errors found, what now catches them, final scores |
| `codegen/` | The eight scripting tasks, their answers (`make_tasks.py`), the runner and `scores.json` |

## Re-run

From the repository root, in a virtual environment with `pip install -e ".[dev]"`:

```bash
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=...   # or put them in .env.bench (gitignored)
export GEOSPARK_DATA_DIR=$PWD/docs/benchmarks/2026-10/.data   # grids are cached here, not in system folders
cd docs/benchmarks/2026-10
python livebench.py run --provider anthropic --model claude-opus-5-5 --mode bare
python datum_run.py run --provider openai --model gpt-6.1-sol --set datum_questions.json --tools
python datum_run.py report
```

Any OpenAI-compatible server works with `--provider workstation` (set `WORKSTATION_LLM_URL` and
`WORKSTATION_LLM_API_KEY`). Spending stops at `LIVEBENCH_BUDGET_USD` (default 8).

Settings used: reasoning effort "low" for GPT-6.1; Opus 5.5 at its defaults (thinking is always on for Opus 5.5, adaptive, effort "medium"); reply limit
2,000 tokens (8,000 for the datum sets), one run per question. To regenerate the official answers,
run `make_datum_set.py` / `make_grid_set.py` with `PROJ_NETWORK=ON`; they stop rather than use a
ballpark operation if a grid is missing.
