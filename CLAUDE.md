# GeoSpark - Project Intelligence

## Project Overview
**GeoSpark** is an open-source Geospatial Intelligence Protocol & Engine that gives AI models genuine spatial reasoning capabilities. It is the "MCP for geospatial."

- **Language**: Python 3.11+
- **Package manager**: pip (venv at `.venv/`)
- **License**: Apache 2.0
- **Status**: Phase 0 (Foundation)

## Architecture

```
geospark/
├── protocol/       # GSP schema (Pydantic models for queries/results)
├── engine/         # Spatial reasoning core (topology, CRS, distance)
├── rag/            # Spatial retrieval-augmented generation
├── tools/          # Pluggable tools (satellite, geocoding, terrain, etc.)
├── integrations/   # LLM connectors (OpenRouter, MCP, Supabase)
│   ├── openrouter.py    # Free LLM integration with optimized tool calling
│   ├── mcp_server.py    # MCP server handler (spatial tools for any AI)
│   └── supabase_db.py   # PostGIS spatial database backend
├── bench/          # GeoSpark Bench evaluation framework
├── utils/          # Shared utilities
├── api.py          # FastAPI REST server
└── cli.py          # CLI entry point (Click + Rich)
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

## Roadmap Phase (Current: Phase 0 → Phase 1)

### Phase 0 - Foundation (COMPLETE)
- [x] PRD, Architecture, Business Plan (docs/)
- [x] Project skeleton with venv + Docker
- [x] Protocol schema (Pydantic models)
- [x] Spatial reasoning engine (topology, distance, CRS)
- [x] First 3 tools (geocoder, satellite, terrain) + change detection stub
- [x] CLI (geospark.cli)
- [x] MCP server handler with optimized tool descriptions
- [x] pyproject.toml with proper extras (geo, api, llm, viz, satellite, postgis)
- [x] CI/CD (GitHub Actions .github/workflows/ci.yml)
- [x] Custom Claude skills (.claude/commands/) and agents (.claude/agents/)
- [x] OpenRouter integration (free LLM + tool calling, 7 model aliases)
- [x] Supabase PostGIS integration (spatial DB backend)
- [x] FastAPI REST server (geospark/api.py) with 8 endpoints
- [x] System prompt optimization (based on Manus/Devin/Cursor/Claude Code analysis)
- [x] Fallback tool call parser for unreliable free models
- [x] Full pipeline demo (examples/demo_full_pipeline.py)
- [x] 50 passing tests (protocol, engine, MCP, OpenRouter, system prompt)

### Phase 1 - Launch (IN PROGRESS)
- [ ] GeoSpark Bench v0.1 (benchmark datasets + runner)
- [ ] Demo notebook (side-by-side: LLM alone vs LLM + GeoSpark)
- [ ] Git init + first commit
- [ ] README.md with badges, quickstart, architecture diagram
- [ ] PyPI package publish
- [ ] Public launch (HN, Reddit, Twitter)
