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
pip install geospark
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

### As an MCP Server (for Claude, ChatGPT, etc.)

```python
from geospark.integrations.mcp_server import GeoSparkMCPHandler

handler = GeoSparkMCPHandler()
tools = handler.get_tools()       # MCP tool definitions
result = handler.handle_tool_call("geocode", {
    "explanation": "Need coordinates for spatial analysis",
    "query": "Big Ben, London"
})
```

### With a free LLM (via OpenRouter)

```python
from geospark.integrations.openrouter import OpenRouterClient

client = OpenRouterClient()  # Uses OPENROUTER_API_KEY env var
answer = client.ask("Is the Eiffel Tower within 5km of the Louvre?")
print(answer)
# The model calls geocode + spatial_query tools automatically
```

### CLI

```bash
geospark geocode "Tokyo Tower, Japan"
geospark elevation 35.6586 139.7454
geospark tools    # List available tools
geospark info     # System info
```

### Docker

```bash
# In-memory backend
docker run -p 8000:8000 geospark/geospark:latest

# Full stack with PostGIS
docker compose up
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

GeoSpark Bench v1.0 includes **535 questions** across 5 benchmark suites. We evaluated **Gemma 12B** on spatial reasoning tasks -- without any tools, using only its training data. Then we compared to GeoSpark's ground-truth engine.

### GeoTopo — Topological Reasoning (210 questions)

| Category | LLM Alone | GeoSpark | Gap |
|----------|-----------|----------|-----|
| contains (point in polygon) | 52.6% | **100%** | +47.4% |
| contains_with_hole | 50.0% | **100%** | +50.0% |
| intersects | 50.0% | **100%** | +50.0% |
| within | 33.3% | **100%** | +66.7% |
| disjoint | 0% | **100%** | +100% |
| touches (boundary) | 0% | **100%** | +100% |
| **Overall** | **30%** | **100%** | **+70%** |

### GeoDistance — Distance Reasoning (210 questions)

| Category | LLM Alone | GeoSpark | Gap |
|----------|-----------|----------|-----|
| absolute distance | 0% | **100%** | +100% |
| nearest neighbor | 0% | **100%** | +100% |
| proximity threshold | 84.3% | **100%** | +15.7% |
| **Overall** | **43%** | **100%** | **+57%** |

### Additional Benchmarks

| Benchmark | Questions | Categories |
|-----------|-----------|------------|
| **GeoChange** | 36 | Change detection, change type classification |
| **GeoReason** | 55 | Multi-step reasoning: transitivity, distance chains, comparative, buffer intersection |
| **GeoMultimodal** | 24 | Vegetation health, elevation/climate, flood risk, urban classification |

**Key finding**: LLMs can reason about *relative proximity* from world knowledge (84% on "is X near Y?") but **cannot compute** distances or topology from coordinates (0%). GeoSpark fills exactly this gap.

> Evaluated with [GeoSpark Bench](docs/ROADMAP.md) v1.0. Run your own: `python -m geospark.bench run --benchmark geotopo`

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
| **Phase 3** — Platform | **Complete** | 441 | Bench v1.0, Flows, Knowledge Graph, Plugin System |
| Phase 4 — Scale | **Next** | -- | Enterprise features, cloud hosting, marketplace |

See [docs/ROADMAP.md](docs/ROADMAP.md) for the detailed roadmap.

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

## License

[Apache 2.0](LICENSE)
