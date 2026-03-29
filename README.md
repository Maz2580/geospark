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

Current LLMs fail at spatial reasoning — mislabeling topological relationships ~80% of the time and showing 42–80% performance drops on complex spatial tasks ([source](https://arxiv.org/abs/2310.11783)). **GeoSpark fixes this.**

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

- **GeoSpark Protocol (GSP)** — A standardized JSON protocol for spatial queries. Like MCP, but for geospatial.
- **Spatial Reasoning Engine** — Topology, distance, CRS transforms, buffering, area calculations. All geometrically correct.
- **MCP Server** — Use GeoSpark as a tool in Claude, ChatGPT, or any MCP-compatible AI assistant.
- **Pluggable Tools** — Geocoding, satellite imagery (STAC), terrain/elevation, routing, spectral indices, change detection.
- **GeoSpark Bench** — 535 benchmark questions across 5 suites proving LLMs fail 70%+ on spatial tasks. [See results →](examples/benchmark_demo.ipynb)
- **GeoSpark Flows** — DAG-based workflow automation with conditional routing and pre-built templates.
- **Spatial Knowledge Graph** — Entity-relation graph with BFS traversal, auto-relate, and natural language queries.
- **Plugin System** — Community plugin ecosystem with manifest-based discovery, lifecycle hooks, and dependency management.
- **Zero-Cost Stack** — OpenRouter free models + Supabase free tier. Full spatial AI at $0/month.

## Quick Start

```bash
pip install geospark-ai
```

### As a Python library

```python
from geospark import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner

# Spatial relationship check
SpatialReasoner.check_relationship(polygon_a, polygon_b, "intersects")

# Distance calculation (geodesic, not Euclidean)
SpatialReasoner.calculate_distance(
    {"type": "Point", "coordinates": [2.2945, 48.8584]},   # Eiffel Tower
    {"type": "Point", "coordinates": [2.3376, 48.8606]},   # Louvre
)
# Returns: ~3,300 meters (actual geodesic distance)
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
geospark geocode "Tokyo Tower, Japan"
geospark elevation 35.6586 139.7454
geospark distance 48.8566 2.3522 51.5074 -- -0.1278  # Paris → London
geospark ask "Is Tokyo closer to Seoul or Beijing?"
geospark tools    # List available tools
geospark info     # System info
```

### Try the Live API (no install needed)

Explore all 11 endpoints interactively at **[geospark.terrascout.app/docs](https://geospark.terrascout.app/docs)**

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
           │ MCP                  │ REST API
           v                      v
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
│Geocoder│ │Satellite │ │Terrain │ │Routing │ │Change  │
│        │ │(STAC,    │ │(Elev.) │ │(OSRM)  │ │Detect. │
│        │ │NDVI, EVI)│ │        │ │        │ │        │
└────────┘ └──────────┘ └────────┘ └────────┘ └────────┘
           │
    ┌──────┴──────┬──────────┬──────────┐
    v             v          v          v
┌────────┐ ┌──────────┐ ┌────────┐ ┌────────┐
│ Flows  │ │Knowledge │ │Plugins │ │Spatial │
│(DAG    │ │Graph     │ │(Commun │ │RAG     │
│Runner) │ │(BFS,NL)  │ │ity)   │ │        │
└────────┘ └──────────┘ └────────┘ └────────┘
```

## Benchmark Results

GeoSpark Bench v1.0 includes **535 questions** across 5 benchmark suites. We evaluated **Qwen 2.5 7B** (via Ollama) on spatial reasoning tasks — baseline (LLM alone) vs. augmented (LLM + GeoSpark tools).

| Benchmark | Questions | LLM Alone | With GeoSpark | Improvement |
|-----------|-----------|-----------|---------------|-------------|
| **GeoDistance** | 210 | 0% | **75%** | **+75%** |
| **GeoReason** | 55 | 85% | **95%** | **+10%** |
| **GeoTopo** | 210 | 45% | **50%** | **+5%** |
| **GeoChange** | 36 | 90% | 85% | -5% |
| **GeoMultimodal** | 24 | 30% | 25% | -5% |

**Key finding**: LLMs literally **cannot compute** geodesic distances from coordinates (0% accuracy). With GeoSpark tool augmentation, accuracy rises to 75%. LLMs can reason about *relative proximity* from world knowledge, but GeoSpark fills the gap where ground-truth computation is required.

> Evaluated with [GeoSpark Bench](docs/BENCHMARK_REPORT.md) v1.0. Run your own: `python -m geospark.bench run --benchmark geotopo`

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
| **Phase 0** — Foundation | **Complete** | 50 | Protocol, engine, CRS, tools, CLI, MCP, Docker, CI/CD |
| **Phase 1** — Launch | **Complete** | 96 | Bench v0.1, baselines, demo notebook, GitHub repo |
| **Phase 2** — Ecosystem | **Complete** | 249 | 8 tools, RAG, memory, planner, cache, 4 LLM integrations |
| **Phase 3** — Platform | **Complete** | 446 | Bench v1.0, Flows, Knowledge Graph, Plugin System |
| **Phase 4** — Scale | **In Progress** | 446 | Live API, Docker deploy, API auth, benchmarking |

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

GeoSpark is deployed and accessible at **[geospark.terrascout.app](https://geospark.terrascout.app/docs)** — 11 endpoints with interactive Swagger documentation.

## Author

Created by **Mazdak Ghasemi Tootkaboni** ([University of Melbourne](https://www.unimelb.edu.au/))

- ORCID: [0000-0001-8084-5270](https://orcid.org/0000-0001-8084-5270)
- GitHub: [@Maz2580](https://github.com/Maz2580)

## License

[Apache 2.0](LICENSE) — Copyright 2024-2026 Mazdak Ghasemi Tootkaboni
