# Is the datum and height gap real? Fairness checks

The first re-check asked each question once, through the plain API, with no tools. These checks ask
whether the gap survives more favourable conditions for the models. Run 2026-10-24/25; total API
spend for the whole October 2026 re-check, all tests included: US$8.46.

## 1. With the providers' own code execution, at high effort

The 17 questions that need a national grid (6 ellipsoid-to-AHD heights; UK OSTN15/OSGM15, NZGeoid2016,
GEOID18 and NADCON) were asked again with each provider's code sandbox switched on (Anthropic
`code_execution_20260521`, OpenAI `code_interpreter`) and effort "high".

Both sandboxes have PROJ installed (pyproj 3.7.2, PROJ 9.5.1) but **no internet access** (checked:
`Could not resolve host: cdn.proj.org`), so neither can fetch a grid.

| | Exact | Within 0.5 m | Wrong | Declined |
|---|:---:|:---:|:---:|:---:|
| GPT-6.1 | 0 | 0 | 0 | 17 |
| Claude Opus 5.5 | 4 | 6 | 7 (worst 9.9 m, Wellington; 8.2 m at Hobart with the geoid's sign reversed) | 0 |

Both models noticed the grid was missing; neither used PROJ's silent "ballpark" result. GPT-6.1
declined; Opus 5.5 labelled its numbers estimates.

## 2. Repeated runs (no tools)

The same 17 questions, three runs per model:

| | Run 1 | Run 2 | Run 3 | Same outcome in all three |
|---|---|---|---|:---:|
| GPT-6.1 | 16 declined, 1 within 0.5 m | 17 declined | 16 declined, 1 exact | 16/17 |
| Claude Opus 5.5 | 8 wrong (worst 5.3 m) | 7 wrong (5.3 m) | 8 wrong (6.3 m) | 13/17 |

For one question Opus's error changed by 4.5 m between runs.

## 3. AI-written GIS code, run as a user would

Eight everyday scripting tasks (an area, a 500 m buffer, a distance, a road length, the true area of
a Web Mercator parcel, points within 1 km, GDA94 MGA to GDA2020 latitude/longitude, a drone height to
AHD). Each model wrote a script; the script ran unchanged in a fresh virtual environment (geopandas
1.0.1, pyproj 3.7.1, PROJ 9.5.1, PROJ downloads off by default) with internet access, as on a
user's computer. Answers were compared with independently computed values (`codegen/`).

| Model | Correct | What went wrong |
|---|:---:|---|
| Claude Opus 5.5 | **8/8** | — (its AHD script turns on grid downloads and rejects an unchanged height) |
| GPT-6.1 | **7/8** | AHD: stopped with an error instead of a number. It downloaded the grid itself but PROJ doesn't re-scan its folders after a download, so its own check found nothing (GeoSpark handles exactly this). Safe, but no answer. |
| gpt-oss 20B (local) | 6/8 | AHD printed **40.0, the input unchanged**: PROJ's silent ballpark, 4.74 m off with no warning. GDA2020 printed geocentric-looking numbers. |
| Qwen 3.5 4B (local) | 1/8 | Silent errors: area 1.2% off, road length 27% off, 1 shop within 1 km instead of 6; four scripts crashed. |

## What this means for the claims

- **Holds:** answered directly (chat, API, or the providers' offline code sandboxes), the two frontier
  models can't use the national grids: GPT-6.1 declines and Opus 5.5 estimates, sometimes metres off,
  and differently from run to run. GeoSpark's `convert_height` and `transform_coordinates` give the
  official answer with its method and accuracy, checked against the agencies (`agency_checks.md`).
- **Does not hold for frontier models writing code:** when Opus 5.5 or GPT-6.1 write a script that you
  run with internet access, they handle areas, buffers, Web Mercator, datum shifts and even AHD
  correctly (or fail safely). The "AI writes silently wrong GIS code" problem is real for the smaller
  local models we tried, including the classic silent AHD error.
- **Not tested:** models with web browsing, other prompts or system prompts, and models other than
  those listed. All questions were written by us; there are 32 datum questions and 8 code tasks.
