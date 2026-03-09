<p align="center">
  <h1 align="center">GeoSpark</h1>
  <p align="center"><strong>The Open-Source Geospatial Intelligence Protocol & Engine</strong></p>
  <p align="center"><em>Give any AI model a spatial mind. Open source. Run anywhere.</em></p>
</p>

<p align="center">
  <a href="https://github.com/Maz2580/geospark/actions"><img src="https://img.shields.io/github/actions/workflow/status/geospark/geospark/ci.yml?branch=main&label=tests" alt="CI"></a>
  <a href="https://pypi.org/project/geospark/"><img src="https://img.shields.io/pypi/v/geospark?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/geospark/"><img src="https://img.shields.io/pypi/pyversions/geospark" alt="Python"></a>
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
- **Pluggable Tools** — Geocoding, satellite imagery (STAC), terrain/elevation, change detection, and more.
- **Zero-Cost Stack** — OpenRouter free models + Supabase free tier. Full spatial AI at $0/month.
- **GeoSpark Bench** — Benchmark suite for evaluating spatial reasoning in AI models (coming soon).

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
└──────────┬───────────────────────────────────────┘
           │
    ┌──────┴──────┬──────────────┬─────────────┐
    v             v              v             v
┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐
│Geocoder│ │Satellite │ │ Terrain  │ │  Change    │
│(Nomin.)│ │ (STAC)   │ │(Elevat.) │ │ Detection  │
└────────┘ └──────────┘ └──────────┘ └────────────┘
```

## Benchmark Results

We evaluated **Gemma 12B** on 200 spatial reasoning questions — without any tools, using only its training data. Then we compared to GeoSpark's ground-truth engine.

### GeoTopo — Topological Reasoning (100 questions)

| Category | LLM Alone | GeoSpark | Gap |
|----------|-----------|----------|-----|
| contains (point in polygon) | 52.6% | **100%** | +47.4% |
| contains_with_hole | 50.0% | **100%** | +50.0% |
| intersects | 50.0% | **100%** | +50.0% |
| within | 33.3% | **100%** | +66.7% |
| disjoint | 0% | **100%** | +100% |
| touches (boundary) | 0% | **100%** | +100% |
| **Overall** | **30%** | **100%** | **+70%** |

### GeoDistance — Distance Reasoning (100 questions)

| Category | LLM Alone | GeoSpark | Gap |
|----------|-----------|----------|-----|
| absolute distance | 0% | **100%** | +100% |
| nearest neighbor | 0% | **100%** | +100% |
| proximity threshold | 84.3% | **100%** | +15.7% |
| **Overall** | **43%** | **100%** | **+57%** |

**Key finding**: LLMs can reason about *relative proximity* from world knowledge (84% on "is X near Y?") but **cannot compute** distances or topology from coordinates (0%). GeoSpark fills exactly this gap.

> Evaluated with [GeoSpark Bench](docs/ROADMAP.md) v0.1. Run your own: `python -m geospark.bench run --benchmark geotopo`

## Why GeoSpark?

| Problem | Without GeoSpark | With GeoSpark |
|---|---|---|
| "Is point A inside region B?" | LLM guesses (30% accuracy) | Ground-truth topology check (100%) |
| "How far is A from B?" | LLM can't compute (0% accuracy) | Geodesic calculation in meters (100%) |
| "What changed here since 2020?" | LLM hallucinates | Real satellite change detection |
| CRS confusion | Silent errors | Automatic detection & transformation |
| "Which landmark is closest?" | LLM guesses wrong (0%) | Exact nearest-neighbor computation (100%) |

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0** — Foundation | **Complete** | Protocol, engine, tools, integrations, 50 tests |
| **Phase 1** — Launch | **In Progress** | Benchmark, demo notebook, PyPI, public launch |
| Phase 2 — Ecosystem | Planned | More tools, memory, spatial RAG, plugin system |
| Phase 3 — Platform | Planned | GeoSpark Flows, knowledge graph, enterprise |

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
