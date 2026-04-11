# GeoSpark - Project Intelligence

## Project Overview
**GeoSpark** is an open-source Geospatial Intelligence Protocol & Engine that gives AI models genuine spatial reasoning capabilities. It is the "MCP for geospatial."

- **Language**: Python 3.11+
- **Package manager**: pip (venv at `.venv/`)
- **License**: Apache 2.0
- **Status**: Phase 7A complete -- 540 tests passing, live at geospark.terrascout.app
- **PyPI**: `pip install geospark-ai[mcp]` — https://pypi.org/project/geospark-ai/
- **MCP**: `geospark-mcp` CLI command (6 tools, official MCP SDK)

## Architecture

```
geospark/
├── protocol/       # GSP schema (Pydantic models for queries/results)
├── engine/         # Spatial reasoning core (topology, CRS, distance, planner, cache)
│   ├── core.py          # Engine orchestrator + QueryChain
│   ├── spatial_reasoner.py  # Topology, distance, geometric operations
│   ├── crs_handler.py   # CRS transformations, validation
│   ├── planner.py       # Query execution planner
│   ├── temporal_engine.py   # Time-series queries, change detection
│   ├── aggregator.py    # Zonal stats, spatial joins
│   └── cache.py         # Spatial-aware LRU caching
├── rag/            # Spatial retrieval-augmented generation
│   ├── retriever.py     # Spatial + semantic feature retrieval
│   ├── chunker.py       # Context-window-sized spatial chunks
│   └── context_builder.py  # Optimal LLM context from spatial data
├── tools/          # Pluggable tools (8 registered)
│   ├── geocoding/       # Nominatim geocoder + reverse geocoder
│   ├── satellite/       # STAC client, NDVI, spectral indices
│   ├── terrain/         # Elevation (Open Elevation API)
│   ├── routing/         # OSRM route analyzer
│   ├── change_detection/  # Pixel change detection
│   └── normalized_result.py  # Consistent result shape for all tools
├── integrations/   # LLM connectors (5 providers)
│   ├── openrouter.py    # Free LLM integration (7 model aliases)
│   ├── openai_tools.py  # OpenAI function calling
│   ├── anthropic_tools.py  # Anthropic tool use
│   ├── ollama_tools.py  # Ollama (local models)
│   ├── generic.py       # Any OpenAI-compatible API
│   ├── mcp_server.py    # Monolithic MCP server (legacy)
│   └── supabase_db.py   # PostGIS spatial database backend
├── mcp_servers/    # Domain-specific MCP servers (Arion pattern)
│   ├── spatial_reasoning.py  # Topology, distance, operations
│   ├── geocoding.py     # Address <-> coordinates
│   ├── terrain.py       # Elevation queries
│   └── launcher.py      # Multi-server launcher
├── memory/         # Session persistence + spatial memory + intelligence
│   ├── session_store.py   # Save/resume conversations
│   ├── spatial_memory.py  # Persistent spatial knowledge (basic)
│   ├── intelligence.py    # Enhanced dual memory: facts + episodes + contradictions
│   └── vector_store.py    # FAISS/numpy vector storage for embedding search
├── bench/          # GeoSpark Bench evaluation framework (5 benchmarks, 535 questions)
│   ├── datasets/        # JSON benchmark datasets
│   ├── generate_datasets.py  # Dataset generator
│   ├── runner.py        # BenchRunner + load/list
│   └── scorer.py        # Scoring + parsing
├── flows/          # GeoSpark Flows (workflow automation)
│   ├── flow_schema.py   # Flow, FlowStep, FlowRoute, FlowRun models
│   ├── flow_builder.py  # Fluent builder API
│   ├── flow_runner.py   # Topological execution engine
│   └── templates.py     # Pre-built flow templates
├── knowledge/      # Spatial Knowledge Graph
│   ├── entities.py      # SpatialEntity, SpatialRelation models
│   ├── graph.py         # SpatialKnowledgeGraph (BFS, auto-relate, query)
│   └── loaders.py       # GeoJSON + Overpass loaders
├── plugins/        # Community Plugin System
│   ├── manifest.py      # PluginManifest (geospark.plugin.json schema)
│   ├── loader.py        # PluginLoader (discover, load, validate)
│   └── hooks.py         # PluginHooks (lifecycle callbacks)
├── utils/          # Shared utilities
├── api.py          # FastAPI REST server (34 endpoints, incl. /status, /memory/*)
└── cli.py          # CLI entry point (Click + Rich, 13 commands)
```

## Development Commands

```bash
# Activate venv (ALWAYS use this - never install globally)
source .venv/Scripts/activate    # Windows/Git Bash
# or: .venv\Scripts\activate     # Windows CMD

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check geospark/ tests/
ruff format geospark/ tests/

# Type check
mypy geospark/

# CLI
python -m geospark.cli info
python -m geospark.cli geocode "Paris, France"

# Docker
docker compose up              # Full stack with PostGIS
docker compose up geospark     # Just GeoSpark API
```

## Code Style & Conventions

- **Type hints**: Required on all public functions
- **Docstrings**: Google-style on all public classes and functions
- **Models**: Pydantic v2 BaseModel for all data schemas
- **Async**: Use async where I/O is involved (httpx for HTTP)
- **Imports**: `from __future__ import annotations` at top of every module
- **Testing**: pytest with fixtures; test files mirror source structure
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **Coordinates**: Always (lon, lat) order internally (GeoJSON standard), convert from (lat, lon) at boundaries using `Point.from_latlon()`

## Key Design Decisions

1. **Protocol-first**: GSP (GeoSpark Protocol) is a JSON schema that any tool can implement. Design the protocol, then build the engine.
2. **Pluggable tools**: Tools are lazy-loaded. No tool should be imported unless explicitly requested.
3. **LLM-agnostic**: Never hard-code to a specific LLM provider. All integrations go through the `integrations/` module.
4. **CRS safety**: Every geometry operation must handle CRS. Default is EPSG:4326. Use `crs_handler.py` for all transformations.
5. **Spatial indexing**: H3 hexagonal grid is the primary spatial index. See `rag/spatial_index.py`.
6. **Zero-config start**: `Engine()` should work with no arguments (in-memory backend, no tools). Scale up by adding tools and backends.
7. **Tool calling patterns** (from system prompt analysis):
   - Tool descriptions: "What it does. When to use it. What it returns. Do NOT use for X."
   - Required `explanation` field on every tool call (forces model to reason before calling)
   - Single-tool-per-iteration loop for free/small models (Manus pattern)
   - Structured results with `status`, `metadata.crs`, and `suggestion` on errors
   - Fallback regex parser for models that write tool calls as plain text
8. **Zero-cost stack**: OpenRouter free models + Supabase free tier (PostGIS). See `.env`.

## Dependencies (Core)

- `pydantic>=2.0` - Data models and validation
- `shapely>=2.0` - Geometry operations
- `pyproj>=3.6` - CRS transformations
- `httpx` - Async HTTP client
- `click` - CLI framework
- `rich` - Terminal formatting

## Dependencies (Optional, by feature)

- `geopandas` - Vector data processing
- `rasterio` - Raster data access
- `h3` - Hexagonal spatial indexing
- `duckdb` - Analytical spatial queries
- `pystac-client` - Satellite data via STAC
- `fastapi` - REST API server
- `folium` - Map visualization

## File Naming Patterns

- Source: `geospark/<module>/<feature>.py`
- Tests: `tests/<module>/test_<feature>.py`
- Docs: `docs/<topic>.md`
- Tools: `geospark/tools/<category>/<tool_name>.py` (must extend `BaseTool`)

## Common Gotchas

- **Coordinate order**: GeoJSON uses `[lon, lat]`, NOT `[lat, lon]`. Always verify.
- **CRS**: Never assume EPSG:4326. Always check and transform.
- **Approximate vs geodesic**: For rough estimates use degree-to-meter approximation (111,320 m/deg). For production use pyproj geodesic calculations.
- **File locks on Windows**: Venv files can get locked by background processes. If venv is corrupted, kill python processes first then recreate.

## Roadmap Phase (Current: Phase 7A complete, Phase 7B next)

See `docs/ROADMAP.md` for the full roadmap with all phases and details.

### Completed Phases
- **Phase 0**: Foundation -- protocol, engine, CRS, tools, CLI, MCP, Docker, CI/CD (50 tests)
- **Phase 1**: Launch -- Bench v0.1, demo notebook, Git, PyPI, README (96 tests)
- **Phase 2**: Ecosystem -- spectral indices, routing, RAG, memory, 4 LLM integrations (249 tests)
- **Phase 3**: Platform -- Bench v1.0 (535q), Flows, Knowledge Graph, Plugin System (441 tests)
- **Phase 4**: Deployment -- live server, Docker prod, MCP+PyPI, Ollama, CLI upgrades (446 tests)
- **Phase 5**: Agents -- GeoAgent, SiteSelector, SpatialReport (autonomous)
- **Phase 5.5**: LLM Gateway -- chat, generate, embeddings, 9 models
- **Phase 6**: Data Channels -- Weather, Air Quality, NASA FIRMS, agent integration (474 tests)
- **Phase 7A**: Spatial Intelligence -- dual memory, vector store, contradictions, auto-linking (540 tests)

### Current: Phase 7B - Geospatial Context Database
- [ ] `GeoContext` model: uri, abstract (L0), overview (L1), full data (L2)
- [ ] Hierarchical storage, lazy loading, hotness scoring
- [ ] Recursive directory retrieval with spatial + temporal filtering
