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

Whether your LLM can compute distances depends heavily on which one you picked. Across 9 models we measured, the smallest open-weight ones (3.8B–9B) get distance questions wrong almost 95% of the time. The picture at the top of the market is not the rescue you'd expect either: among contemporary frontier APIs, accuracy ranges from 25% (Gemini 2.5 Pro) through 74% (Claude Sonnet 4.5) up to 95% (GPT-5.4) on the same set of questions. Surprisingly, gpt-oss 20B — open-weight and free to self-host — clocks in at 93.8%, essentially matching GPT-5.4. **GeoSpark backstops every model that can call a tool to a 76–96% answer rate**, which collapses that 70-point spread between frontier vendors and lets a 7B model running on your own CPU answer the same questions as well as a paid frontier API.

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

- **Multi-Agent Coordinator** — One command, right specialist. Intent classification routes your goal to the best agent automatically, with streaming progress and A2A messaging under the hood.
- **Autonomous Spatial Agents** — Give a goal, get a complete analysis. No manual step-by-step. Three built-in agents:
  - `GeoAgent` — Multi-step spatial analysis from natural language ("Find hospitals near the Eiffel Tower")
  - `SpatialReport` — One-command location intelligence dossier (amenities, accessibility, elevation, narrative)
  - `SiteSelector` — Optimal location finding with multi-criteria scoring ("Best pharmacy spot in Zurich near hospitals and schools")
- **Spatial Intelligence Memory** — Dual memory system that learns across sessions:
  - `SpatialFact` — time-agnostic truths ("Eiffel Tower is at 48.86 N, 2.29 E")
  - `SpatialEpisode` — timestamped observations ("PM2.5 was 120 in Delhi on 2026-04-09")
  - Vector-based recall with FAISS acceleration or numpy fallback
  - Automatic contradiction detection between conflicting facts
  - Auto-linking of related memories at cosine similarity > 0.6
- **Geospatial Context Database** — Tiered storage for missions, datasets, and analysis history:
  - L0/L1/L2 lazy loading: abstracts in the prompt, full data on demand
  - Hotness scoring: sigmoid(log1p(access)) * exp(-decay * age) balances frequency + recency
  - Hierarchical URIs like `geospark://missions/melbourne_flood/analysis/2026-04`
  - Recursive parent-child score propagation for context retrieval
  - Spatial bbox + temporal range filters, cold-context archival
- **Chat-to-Flow Builder** — Turn a natural-language goal into a validated Flow DAG. `ChatFlowSession` drives an LLM through incremental builder tool calls (`add_step`, `add_route`, `set_trigger`, `finish_flow`); invalid calls surface to the LLM as errors and are corrected before the Flow is emitted. Available via `geospark flow build "..."` or `POST /api/v1/flows/build`.
- **Enterprise Middleware** — Production hardening that shipped in Phase 8A: sliding-window rate limiting (per-IP and per-API-key with `X-RateLimit-*` headers), structured JSON-Lines audit logging with daily rotation, per-endpoint usage tracking with persisted counters, and transparent LRU+TTL caching for data channels.
- **Spatial Reasoning Engine** — Topology, geodesic distance, CRS transforms, buffering, area. All geometrically correct, not LLM-guessed.
- **MCP Server** — 6 tools for Claude Desktop and any MCP-compatible AI assistant. `pip install geospark-ai[mcp] && geospark-mcp`
- **GeoSpark Bench** — 535 questions, five categories. The v2 evaluation runs each of 9 models (Qwen / Llama / Gemma / Mistral / Phi at ≤9B, gpt-oss at 20B, and three frontier APIs) under three protocols: bare baseline, structured Chain-of-Thought, and tool-augmented. Outcome: a 7B model with our tools answers numeric distance questions about as well as Gemini 2.5 Pro does, at zero per-call cost. [Results →](docs/BENCHMARK_REPORT.md)
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

### Multi-agent coordinator (Phase 7C)

```python
from geospark.agents import AgentCoordinator

coord = AgentCoordinator()  # Auto-registers GeoAgent, SiteSelector, SpatialReport

# One entry point for any spatial goal — coordinator picks the right specialist
result = coord.run("Find the best location for a cafe in Melbourne CBD near schools")
print(f"Routed to: {result.agent_used}")   # site_selector (matched pattern)
print(result.summary)
```

### Chat-to-flow builder (Phase 8B)

```python
from geospark.flows import ChatFlowSession, FlowRunner, make_ollama_chat_fn

# LLM incrementally builds a validated Flow DAG via tool calls
session = ChatFlowSession(llm_fn=make_ollama_chat_fn("qwen2.5:7b"))
result = session.run("Geocode Valencia, Spain then check its elevation")

if result.flow is not None:
    print(f"Built flow with {len(result.flow.steps)} steps in {result.turns} turns")
    FlowRunner().run(result.flow)  # Execute the generated DAG
```

### Spatial intelligence memory (Phase 7A)

```python
from geospark.memory import SpatialIntelligence

intel = SpatialIntelligence()

# Remember timeless facts and timestamped episodes
intel.remember_fact("Eiffel Tower is at 48.8584 N, 2.2945 E", source="user")
intel.remember_episode("PM2.5 was 120 in Delhi", importance=0.8, source="tool:air_quality")

# Vector-based recall with automatic scoring (similarity + recency + importance)
results = intel.recall("Paris landmarks", limit=5)

# Detect contradicting facts automatically
for c in intel.find_contradictions():
    print(f"Conflict: {c.fact_a_content}  vs.  {c.fact_b_content}")
```

### Geospatial context database (Phase 7B)

```python
from geospark.context import ContextStore, ContextRetriever, GeoContext

store = ContextStore()
retriever = ContextRetriever(store)

# Save a mission with tiered content
store.save(GeoContext(
    uri="geospark://missions/melbourne_flood_2024",
    category="missions",
    name="Melbourne Flood 2024",
    abstract="Major flooding event in Melbourne CBD",  # L0 — always in prompt
    overview={"severity": "high", "area_km2": 42},      # L1 — loaded for context
    full_data={"affected_population": 15000},           # L2 — loaded on demand
    bounds_wgs84=[144.9, -37.9, 145.1, -37.7],
    tags=["flood", "melbourne", "disaster"],
))

# Retrieve with hierarchical scoring (semantic + hotness + parent propagation)
results, stats = retriever.retrieve(query="flood melbourne", limit=5)
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
# Multi-agent coordinator (routes to the right specialist automatically)
geospark multi-agent "Find the best cafe spot in Melbourne near schools"
geospark multi-agent "Analyze Federation Square" --stream   # Live progress
geospark agents                                              # List registered agents

# Autonomous agents (direct access)
geospark agent "Find all parks within 2km of Big Ben"
geospark report "Federation Square, Melbourne"
geospark site-select --within "Paris" --near "metro,schools" --facility restaurant

# Spatial intelligence memory
geospark memory recall "flood risk Melbourne"    # Vector-based recall
geospark memory contradictions                   # Find conflicting facts
geospark memory stats                            # FAISS + count info
geospark memory compact                          # Archive old episodes

# Geospatial context database
geospark context list                            # All stored contexts
geospark context show geospark://missions/flood  # View at L0/L1/L2
geospark context query "flood melbourne"         # Hierarchical retrieval
geospark context stats                           # Hottest contexts
geospark context archive-cold                    # Move cold to _archive/

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
geospark flow build "Monitor NDVI in Valencia; alert if it drops below 0.3" --run
```

### Try the Live API (no install needed)

Explore all **62+ endpoints** interactively at **[geospark.terrascout.app/docs](https://geospark.terrascout.app/docs)**.

```bash
# Quick distance check
curl -X POST https://geospark.terrascout.app/api/v1/distance \
  -H "Content-Type: application/json" \
  -d '{"lat_a": 48.8566, "lon_a": 2.3522, "lat_b": 51.5074, "lon_b": -0.1278}'

# Build a flow from a natural-language goal (Phase 8B)
curl -X POST https://geospark.terrascout.app/api/v1/flows/build \
  -H "Content-Type: application/json" \
  -d '{"goal": "Geocode Valencia then check its elevation", "max_turns": 10}'
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
           │ MCP                  │ REST API (62+ endpoints)
           v                      v
┌──────────────────────────────────────────────────┐
│         Multi-Agent Coordinator (Phase 7C)       │
│   Intent classification · A2A msg · Streaming    │
└──────────┬───────────────────────────────────────┘
           │
           v
┌──────────────────────────────────────────────────┐
│           Autonomous Agents Layer                │
│  GeoAgent · SpatialReport · SiteSelector         │
└──────────┬───────────────────────────────────────┘
           │
           v
┌──────────────────────────────────────────────────┐
│         Spatial Intelligence (Phase 7A/B)        │
│  Facts + Episodes + Contradictions (VectorStore) │
│  Tiered Context DB · Hotness · Hierarchy         │
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

What follows is a quick read of the v2 numbers; the underlying paper, theory, and limitations discussion are part of a separate manuscript currently undergoing peer review.

The v2 sweep covered 9 models in 3 buckets:
- 5 small open-weight (3.8B–9B): Qwen 2.5 7B, Llama 3.1 8B, Gemma 2 9B, Mistral 7B, Phi-3.5 3.8B
- 1 mid open-weight: gpt-oss 20B
- 3 frontier APIs: GPT-5.4 (`gpt-5.4-2026-03-05`), Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`), Gemini 2.5 Pro

Each model ran the suite three times: just the question, then a step-by-step prompt where the model writes a short reasoning trace and tags its conclusion `FINAL ANSWER:`, and finally the same question with our MCP tools attached. We report Wilson 95% intervals throughout. The per-call cost ledger is checked in (~$41 of API spend; the open tier is free).

### Numeric distance — the headline cell (`distance_absolute`, n=80 per model)

These are "what's the distance from X to Y?" questions in metres, with ground truth from `pyproj.Geod.inv()` on WGS84. A response counts as correct if it lands within 10% of the true geodesic.

| Model | Tier | Bare LLM | Step-by-step (CoT) | + GeoSpark tools |
|---|---|:---:|:---:|:---:|
| Qwen 2.5 7B | open ≤9B | 5.0% | 20.0% | **76.2%** |
| Llama 3.1 8B | open ≤9B | 5.0% | 21.2% | 7.5% (a) |
| Gemma 2 9B | open ≤9B | 37.5% (b) | 6.2% (c) | — |
| Mistral 7B | open ≤9B | 2.5% | 2.5% | 0.0% (a) |
| Phi-3.5 3.8B | open ≤9B | 1.2% | 6.2% | — |
| **gpt-oss 20B** | open mid | **93.8%** | 93.8% | 91.2% |
| OpenAI GPT-5.4 | frontier | 95.0% | 90.0% (c) | 95.0% |
| Anthropic Claude Sonnet 4.5 | frontier | 73.8% | 92.5% | **96.2%** |
| Google Gemini 2.5 Pro | frontier | 25.0% | 55.0% | 85.0% |

Annotations:
- (a) Tools were available but the model didn't use them properly. Llama emitted tool calls but mangled the coordinates it got back — a classic kilometres-vs-metres mix-up appears repeatedly. Mistral skipped the tool layer entirely and tried to answer in plain text.
- (b) Gemma's 37.5% looks decent but it's not actually computing — when we trace the right answers, they all land on famous long-distance pairs whose approximate great-circle distance is the kind of trivia LLMs pick up in training. On shorter or less-prominent routes, errors are random.
- (c) Step-by-step prompting was a regression for these two models. Forcing Gemma to reason step-by-step routes it away from its memorisation strategy and into computation, where it falls apart. GPT-5.4 starts at the ceiling and CoT just adds format noise.

### Where the tools matter most

The bare-LLM range across the 9 models spans 1.2% to 95% — basically the full available stretch on a percentage scale. Plug the tools in and every model that emits valid tool calls finishes between 76% and 96%. Largest jump: Qwen (+71 points). Smallest: GPT-5.4 (zero — its baseline was already 95%).

For practical deployment this means two different pictures depending on which LLM you've already chosen:
- **Self-hosting on commodity hardware?** Qwen 7B + GeoSpark gets you to 76% on numeric distance, comparable to Gemini 2.5 Pro + GeoSpark (85%) at zero marginal cost per call.
- **Already paying for a frontier API?** Tools rarely improve absolute accuracy at the top of the market — but they replace probabilistic guessing with a deterministic engine call, so you get an auditable trace of how each answer was computed.

### What aggregate scores hide — the per-predicate split

GeoTopo aggregate scores look unremarkable across the open-weight tier (Qwen 56%, Llama 60%, Gemma 72%). The decomposition tells a different story. Here's Qwen 2.5 7B's bare-LLM accuracy, by predicate, on n=210:

| Predicate | n | Bare-LLM accuracy | What's going on |
|---|---|:---:|---|
| `intersects` | 30 | **93%** | dataset skews `True` here, model defaults `True` |
| `within` | 45 | 89% | same pattern |
| `contains` | 54 | 56% | mixed labels, model is guessing |
| `contains_with_hole` | 24 | 54% | mixed labels, model is guessing |
| `touches` | 27 | 22% | dataset skews `False`, model still says `True` |
| `disjoint` | 30 | **3%** | dataset skews `False`, model says `True` anyway |

The model isn't reasoning about topology at all — it's defaulting to "yes" and the dataset's predicate distribution disguises that as competence. With GeoSpark in the loop, every predicate hits 100% because the engine just calls Shapely. The same pattern shows up at the frontier with different specifics: GPT-5.4 hits 100% on `intersects` and `disjoint` but **0% on `touches`** at n=27.

### What we learned (one-line each)

- The "LLMs can't compute distances" framing is too coarse — vendor matters as much as scale at the top of the market
- gpt-oss 20B is the unexpected open-weight datapoint of the study; it ties GPT-5.4 on numeric distance baseline at zero cost
- Tools are a leveller: they erase the ~70-point bare-LLM gap between top and bottom of the frontier tier
- Step-by-step prompting helps some models, hurts others — there's no universal recipe
- Aggregate accuracy on multi-class benchmarks can miss the actual failure mode entirely; you need per-class numbers to see model bias
- Knowledge questions ("did the Amazon experience deforestation between 2015 and 2023?") are unaffected by tools — they're already solved by training data at every scale

> Per-cell JSONs and the cost ledger live alongside this README in the repository. To re-run the bench yourself: `python -m geospark.bench run`. The full paper-form discussion accompanies the manuscript currently under peer review and will be linked here once the venue is announced.

## Why GeoSpark?

GeoSpark's value proposition depends on which LLM you're using. The table below maps each capability to the gap GeoSpark fills, with v2-paper-verified numbers.

| Problem | Without GeoSpark (open ≤9B) | Without GeoSpark (frontier) | With GeoSpark (any tier) |
|---|---|---|---|
| "How far is A from B?" (numeric) | 0–5% — model emits implausible numbers or refuses | 25–95% (vendor-dependent) | **76–96%** geodesic computation |
| "Is point A inside region B?" | 56% aggregate, but `disjoint` only 3% (yes-bias) | 60–82% baseline | **100%** ground-truth predicate |
| "Did region X change since 2020?" | 65–90% (already works at all tiers) | 78–92% | tools add no value here — knowledge tasks work without GeoSpark |
| CRS confusion | Silent errors | Silent errors | Automatic detection & transformation |
| "Which landmark is closest?" | 0–46% baseline | varies | Exact nearest-neighbor + verifiable trace |
| Audit trail / verifiability | None — model just emits a number | None at baseline | Per-call tool trace, deterministic engine, reproducible |

**Where GeoSpark adds the most value**: small open-weight models that need to compute (Qwen + tools = 76% on numeric distance, vs 5% baseline) and frontier deployments where you need verifiability rather than additional accuracy (GPT-5.4 baseline = augmented = 95%, but augmented gives you a deterministic tool trace).

**Where GeoSpark adds the least value**: knowledge-based spatial questions ("did the Amazon experience deforestation"). All models above 65% at baseline; tools are unnecessary overhead.

## Project Status

| Phase | Status | Tests | Description |
|-------|--------|-------|-------------|
| **Phase 0-3** — Foundation to Platform | **Complete** | 441 | Protocol, engine, tools, MCP, Bench, Flows, Knowledge Graph, Plugins |
| **Phase 4** — Deployment | **Complete** | 446 | Live API, Docker, PyPI, Ollama, API auth, 5-model benchmarks |
| **Phase 5** — Autonomous Agents | **Complete** | 446 | GeoAgent, SpatialReport, SiteSelector |
| **Phase 6** — Data Channels | **Complete** | 474 | Weather, Air Quality, NASA Fires — free, real-time |
| **Phase 7A** — Spatial Memory | **Complete** | 540 | Facts + Episodes, VectorStore (FAISS), contradictions, auto-linking |
| **Phase 7B** — Context Database | **Complete** | 589 | Tiered L0/L1/L2 loading, hotness scoring, hierarchical retrieval |
| **Phase 7C** — Multi-Agent Coordination | **Complete** | 657 | Toolkit, A2A messaging, coordinator with streaming |
| **Phase 7 UI** — Guide & Pages | **Complete** | 679 | Onboarding guide, Memory/Context UI pages, Coordinator tab |
| **Phase 8A** — Enterprise Hardening | **Complete** | 754 | Rate limiting, audit logging, usage tracking, channel cache |
| **Phase 8B** — Chat-to-Flow Builder | **Complete** | **776** | Natural-language goal → validated Flow DAG via LLM tool calling |

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

GeoSpark is deployed and accessible at **[geospark.terrascout.app](https://geospark.terrascout.app/docs)** — 62+ endpoints with interactive Swagger documentation.

## Author

Created by **Mazdak Ghasemi Tootkaboni** ([University of Melbourne](https://www.unimelb.edu.au/))

- ORCID: [0000-0001-8084-5270](https://orcid.org/0000-0001-8084-5270)
- GitHub: [@Maz2580](https://github.com/Maz2580)

## License

[Apache 2.0](LICENSE) — Copyright 2024-2026 Mazdak Ghasemi Tootkaboni
