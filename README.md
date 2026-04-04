<p align="center">
  <h1 align="center">GeoSpark</h1>
  <p align="center"><strong>The Open-Source Geospatial Intelligence Protocol & Engine</strong></p>
  <p align="center"><em>Give any AI model a spatial mind. Open source. Run anywhere.</em></p>
</p>

<p align="center">
  <a href="https://github.com/Maz2580/geospark/actions"><img src="https://img.shields.io/github/actions/workflow/status/Maz2580/geospark/ci.yml?branch=main&label=tests" alt="CI"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/v/geospark-ai?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/pyversions/geospark-ai" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
</p>

---

Current LLMs fail at spatial reasoning — achieving 0% on geodesic distance computation and ~48% (random chance) on topological reasoning across five model families in our benchmarks. **GeoSpark fixes this.**

## The Problem

Ask any LLM: *"Is the Louvre inside the 7th arrondissement of Paris?"*

It will confidently guess — and get it wrong most of the time. LLMs have no geometric engine, no coordinate system awareness, and no way to verify spatial claims. They hallucinate distances, confuse containment with proximity, and silently swap lat/lon.

## The Solution

GeoSpark gives AI models **ground-truth spatial reasoning** through a standardized protocol:

```python
from geospark import Engine
from geospark.protocol import SpatialQuery, SpatialOperation

engine = Engine(tools=["geocoder", "terrain"])

# Geocode a location (not guessing — real coordinates)
result = engine.execute(SpatialQuery(
    operation=SpatialOperation.GEOCODE,
    metadata={"query": "Eiffel Tower, Paris"}
))

# Check spatial relationships (100% accurate, not LLM guessing)
from geospark.engine.spatial_reasoner import SpatialReasoner

park = {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]]}
point = {"type": "Point", "coordinates": [2.295, 48.855]}

SpatialReasoner.check_relationship(park, point, "contains")  # True — ground truth
```

## Key Features

- **Autonomous Spatial Agents** — Give a goal, get a complete analysis. No manual step-by-step. Three built-in agents:
  - `GeoAgent` — Multi-step spatial analysis from natural language ("Find hospitals near the Eiffel Tower")
  - `SpatialReport` — One-command location intelligence dossier (amenities, accessibility, elevation, narrative)
  - `SiteSelector` — Optimal location finding with multi-criteria scoring ("Best pharmacy spot in Zurich near hospitals and schools")
- **Spatial Reasoning Engine** — Topology, geodesic distance, CRS transforms, buffering, area. All geometrically correct, not LLM-guessed.
- **MCP Server** — 6 tools for Claude Desktop and any MCP-compatible AI assistant. `pip install geospark-ai[mcp] && geospark-mcp`
- **GeoSpark Bench** — 535 benchmark questions, 5 LLM families evaluated. LLMs score 0% on distance; with GeoSpark tools, 70%. [Results →](docs/BENCHMARK_REPORT.md)
- **GeoSpark Protocol (GSP)** — Standardized JSON protocol for spatial queries and results.
- **Live Data Channels** — Pluggable real-time data sources:
  - Weather (Open-Meteo) — current conditions + forecast for any location
  - Air Quality (OpenAQ) — PM2.5, NO2, O3 from government stations with WHO health categories
  - Active Fires (NASA FIRMS) — near-real-time satellite fire detections
- **Pluggable Tools** — Geocoding, satellite imagery (STAC), terrain/elevation with vertical datum awareness (NAVD88/EGM96/WGS84), routing, spectral indices.
- **GeoSpark Flows** — DAG-based workflow automation with persistence (Supabase), CLI, and REST API.
- **Spatial Knowledge Graph** — Entity-relation graph with OSM admin boundaries, BFS traversal, and natural language queries.
- **Zero-Cost Stack** — Local Ollama (primary, no limits) + OpenRouter free tier (fallback) + Supabase free tier. All inference on your hardware.

## Quick Start

```bash
pip install geospark-ai
```

### Autonomous Agents (the fastest way to use GeoSpark)

```python
from geospark.agents import GeoAgent, SpatialReport, SiteSelector

# Autonomous spatial analysis — plans and executes multi-step workflows
agent = GeoAgent()
result = agent.run("Find all hospitals within 2km of the Eiffel Tower")
print(result.summary)  # "Within 2km of the Eiffel Tower, there are 3 hospitals..."

# Location intelligence dossier — one command, complete analysis
reporter = SpatialReport()
report = reporter.analyze("Federation Square, Melbourne")
print(report.accessibility)  # Nearest hospital, school, pharmacy with distances

# Optimal site selection — multi-criteria spatial scoring
selector = SiteSelector()
result = selector.find(within="Zurich", near=["hospital", "school"], facility_type="pharmacy")
print(result.best)  # Best-scoring location with explanation
```

### As a Python library

```python
from geospark.engine.spatial_reasoner import SpatialReasoner

# Distance calculation (geodesic on WGS84 ellipsoid, not Euclidean)
SpatialReasoner.calculate_distance(
    {"type": "Point", "coordinates": [2.2945, 48.8584]},   # Eiffel Tower
    {"type": "Point", "coordinates": [2.3376, 48.8606]},   # Louvre
)
# Returns: ~3,300 meters (actual geodesic distance)

# Spatial relationship check (ground-truth, not LLM-guessed)
SpatialReasoner.check_relationship(polygon_a, polygon_b, "intersects")
```

### Vertical Datum Awareness

```python
from geospark.tools.terrain.vertical_datum import infer_datum, format_elevation_warning

# Infer vertical datum from elevation source
info = infer_datum("3dep")  # USGS 3DEP → NAVD88
print(info.datum, info.height_type)  # "NAVD88", "orthometric"

# Warn when mixing datums (NAVD88 vs EGM96 = ~17m difference in Colorado)
warning = format_elevation_warning("3dep", "srtm", "Denver, CO")
# "WARNING: Comparing elevations from '3dep' (NAVD88) and 'srtm' (EGM96)..."
```

### As an MCP Server (for Claude Desktop)

```bash
pip install geospark-ai[mcp]
geospark-mcp  # Starts stdio MCP server with 6 spatial tools
```

Add to your Claude Desktop config (`~/.claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "geospark": { "command": "geospark-mcp" }
  }
}
```

### Natural language spatial questions

```python
from geospark import Engine

engine = Engine(tools=["geocoder", "terrain"])
result = engine.ask("How far is the Eiffel Tower from Big Ben?")
print(result.spatial_context.summary)
# Automatically geocodes both locations + computes geodesic distance
```

Tries local Ollama first (free, fast), falls back to OpenRouter.

### CLI

```bash
# Autonomous agents
geospark agent "Find all parks within 2km of Big Ben"
geospark report "Federation Square, Melbourne"
geospark site-select --within "Paris" --near "metro,schools" --facility restaurant

# Spatial tools
geospark geocode "Tokyo Tower, Japan"
geospark elevation 35.6586 139.7454
geospark distance 48.8566 2.3522 51.5074 -- -0.1278  # Paris → London
geospark ask "Is Tokyo closer to Seoul or Beijing?"

# Live data channels
geospark data weather "Melbourne, Australia"     # Weather + forecast
geospark data air-quality "Delhi"                # PM2.5, NO2, O3
geospark data fires "Amazon Rainforest"          # Active fire detections
geospark data status                             # Check all channels

# Flow workflows
geospark flow list                     # List templates
geospark flow run distance_analysis    # Run a template
```

### Try the Live API (no install needed)

Explore all 28 endpoints interactively at **[geospark.terrascout.app/docs](https://geospark.terrascout.app/docs)**

```bash
# Quick test
curl -X POST https://geospark.terrascout.app/api/v1/distance \
  -H "Content-Type: application/json" \
  -d '{"lat_a": 48.8566, "lon_a": 2.3522, "lat_b": 51.5074, "lon_b": -0.1278}'
```

### Run the Benchmark

```bash
# Run GeoSpark Bench on topological reasoning
python -m geospark.bench run --benchmark geotopo

# Run all benchmarks
python -m geospark.bench run

# List available benchmarks
python -m geospark.bench list
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   User / LLM                    │
│         (Claude, ChatGPT, Ollama, ...)          │
└──────────┬──────────────────────┬───────────────┘
           │ MCP                  │ REST API (28 endpoints)
           v                      v
┌──────────────────────────────────────────────────┐
│           Autonomous Agents Layer                │
│  GeoAgent · SpatialReport · SiteSelector         │
└──────────┬───────────────────────────────────────┘
           │
           v
┌──────────────────────────────────────────────────┐
│              GeoSpark Protocol (GSP)             │
│         Standardized JSON query/result           │
└──────────┬───────────────────────────────────────┘
           │
           v
┌──────────────────────────────────────────────────┐
│             Spatial Reasoning Engine              │
│  Topology · Distance · CRS · Buffer · Centroid   │
│  Planner · Cache · Temporal · Aggregator         │
└──────────┬───────────────────────────────────────┘
           │
    ┌──────┴──────┬──────────┬──────────┬──────────┐
    v             v          v          v          v
┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│Geocoder│ │Satellite │ │Terrain │ │Routing │ │Spectral│
│        │ │(STAC)    │ │+ Datum │ │(OSRM)  │ │Indices │
│        │ │          │ │Aware.  │ │        │ │        │
└────────┘ └──────────┘ └────────┘ └────────┘ └────────┘
           │
    ┌──────┴──────┬──────────┬──────────┐
    v             v          v          v
┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐
│ Flows  │ │Knowledge │ │Plugins │ │Spatial │
│+ Persist│ │Graph+OSM │ │        │ │RAG     │
│(Supa.) │ │(Admin)   │ │        │ │(Embed) │
└────────┘ └──────────┘ └────────┘ └────────┘
```

## Benchmark Results

GeoSpark Bench v1.0 — **535 questions** across 5 benchmarks, evaluated on **5 LLM families** (Qwen, Llama, Gemma, Mistral, Phi) via Ollama.

### Baseline: LLM Alone (No Tools)

| Benchmark | Qwen 2.5 7B | Llama 3.1 8B | Gemma 2 9B | Mistral 7B | Phi-3.5 3.8B | Mean |
|-----------|:-----------:|:-----------:|:----------:|:----------:|:-----------:|:----:|
| GeoDistance | **0%** | **0%** | 30% | **0%** | **0%** | **6%** |
| GeoTopo | 45% | 50% | 50% | 50% | 45% | 48% |
| GeoChange | 90% | 65% | 80% | 85% | 75% | 79% |
| GeoReason | 85% | 65% | 90% | 75% | 70% | 77% |
| GeoMultimodal | 30% | 35% | 30% | 35% | 35% | 33% |

### With GeoSpark Tool Augmentation

| Benchmark | Qwen 2.5 7B | Llama 3.1 8B | Mistral 7B | Improvement (best) |
|-----------|:-----------:|:-----------:|:----------:|:------------------:|
| GeoDistance | **70%** | 10% | 0% | **+70%** |
| GeoReason | **100%** | 65% | 80% | **+15%** |
| GeoTopo | 50% | 50% | 50% | +5% |

**Key findings**:
- **0% on distance** across 4/5 models — LLMs cannot compute geodesic distances from coordinates
- **48% on topology** — random chance on binary questions, confirming no spatial predicate capability
- **79% on change detection** — knowledge-based spatial reasoning works; the deficit is strictly computational
- **70% with tools** (Qwen 2.5 7B) — tool augmentation fixes the computational gap
- **100% on reasoning** (Qwen 2.5 7B) — structured prompting solves multi-step spatial chains

> Full results: [Benchmark Report](docs/BENCHMARK_REPORT.md) | Run your own: `python -m geospark.bench run`

## Why GeoSpark?

| Problem | Without GeoSpark | With GeoSpark |
|---|---|---|
| "Is point A inside region B?" | LLM guesses (30% accuracy) | Ground-truth topology check (100%) |
| "How far is A from B?" | LLM can't compute (0% accuracy) | Geodesic calculation in meters (100%) |
| "What changed here since 2020?" | LLM hallucinates | Real satellite change detection |
| CRS confusion | Silent errors | Automatic detection & transformation |
| "Which landmark is closest?" | LLM guesses wrong (0%) | Exact nearest-neighbor computation (100%) |

## Project Status

| Phase | Status | Tests | Description |
|-------|--------|-------|-------------|
| **Phase 0-3** — Foundation to Platform | **Complete** | 446 | Protocol, engine, tools, MCP, Bench, Flows, Knowledge Graph, Plugins |
| **Phase 4** — Deployment | **Complete** | 446 | Live API, Docker, PyPI, Ollama, API auth, 5-model benchmarks |
| **Phase 5** — Autonomous Agents | **Complete** | 446 | GeoAgent, SpatialReport, SiteSelector |
| **Phase 6** — Data Channels | **Complete** | 446 | Weather, Air Quality, NASA Fires — free, real-time |

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## Development

```bash
# Clone and setup
git clone https://github.com/Maz2580/geospark.git
cd geospark
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint & format
ruff check geospark/ tests/
ruff format geospark/ tests/

# Type check
mypy geospark/
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Live API

GeoSpark is deployed and accessible at **[geospark.terrascout.app](https://geospark.terrascout.app/docs)** — 28 endpoints with interactive Swagger documentation.

## Author

Created by **Mazdak Ghasemi Tootkaboni** ([University of Melbourne](https://www.unimelb.edu.au/))

- ORCID: [0000-0001-8084-5270](https://orcid.org/0000-0001-8084-5270)
- GitHub: [@Maz2580](https://github.com/Maz2580)

## License

[Apache 2.0](LICENSE) — Copyright 2024-2026 Mazdak Ghasemi Tootkaboni
