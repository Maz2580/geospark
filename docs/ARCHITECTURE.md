# GeoSpark: Technical Architecture & Roadmap

**Version**: 2.0
**Date**: March 2026
**Status**: Phase 3 Complete -- 441 tests passing

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Python   │  │ CLI      │  │ REST     │  │ MCP Server   │   │
│  │ SDK      │  │ Interface│  │ API      │  │ (for LLMs)   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       └──────────────┴─────────────┴───────────────┘           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ GeoSpark Protocol (GSP)
┌───────────────────────────┴─────────────────────────────────────┐
│                     GEOSPARK CORE ENGINE                        │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Query Parser & Planner                     │    │
│  │  (Parses GSP queries → execution plan → tool routing)   │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                           │                                     │
│  ┌────────────┐  ┌───────┴────────┐  ┌──────────────────┐    │
│  │  Spatial    │  │  Tool          │  │  Spatial         │    │
│  │  Reasoning  │  │  Orchestrator  │  │  Knowledge       │    │
│  │  Engine     │  │                │  │  Graph           │    │
│  │            │  │  (Routes to    │  │                  │    │
│  │  - Topology │  │   appropriate  │  │  - OSM data      │    │
│  │  - Distance │  │   tools)       │  │  - Admin bounds  │    │
│  │  - CRS     │  │                │  │  - POI database  │    │
│  │  - Temporal │  │                │  │  - Land use      │    │
│  │  - Aggreg. │  │                │  │  - Relationships │    │
│  └────────────┘  └───────┬────────┘  └──────────────────┘    │
│                          │                                     │
│  ┌───────────────────────┴───────────────────────────────┐    │
│  │                    TOOL LAYER                          │    │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐  │    │
│  │  │Satellite│ │Change    │ │Geocoder │ │Terrain   │  │    │
│  │  │Viewer   │ │Detector  │ │         │ │Analyzer  │  │    │
│  │  └─────────┘ └──────────┘ └─────────┘ └──────────┘  │    │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐  │    │
│  │  │Route    │ │Climate   │ │Land Use │ │Population│  │    │
│  │  │Analyzer │ │Querier   │ │Classif. │ │Estimator │  │    │
│  │  └─────────┘ └──────────┘ └─────────┘ └──────────┘  │    │
│  │  ┌─────────┐ ┌──────────┐                            │    │
│  │  │Flood    │ │Custom    │  (Community-contributed)    │    │
│  │  │Risk     │ │Tools...  │                            │    │
│  │  └─────────┘ └──────────┘                            │    │
│  └───────────────────────────────────────────────────────┘    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────────────┐
│                      DATA LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │ Spatial      │  │ Raster       │  │ External Data    │     │
│  │ Database     │  │ Storage      │  │ Connectors       │     │
│  │              │  │              │  │                  │     │
│  │ - PostGIS    │  │ - Local FS   │  │ - STAC APIs      │     │
│  │ - SpatiaLite │  │ - S3/GCS/    │  │ - Overture Maps  │     │
│  │ - DuckDB     │  │   Azure Blob │  │ - OSM Overpass   │     │
│  │   Spatial    │  │ - COG server │  │ - Weather APIs   │     │
│  └──────────────┘  └──────────────┘  └──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Architecture

### 1. `geospark.protocol` -- The GSP Standard

```
geospark/protocol/
├── schema.py          # GSP JSON schema definitions (Pydantic models)
├── query.py           # Query builder and parser
├── result.py          # Result formatter with spatial context
├── validator.py       # Schema validation
└── serializer.py      # GeoJSON/GeoParquet/WKT serialization
```

**Key Design**: GSP queries are Pydantic models that validate input, plan execution, and format output. This ensures type safety and enables auto-documentation.

```python
# Example: Building a GSP query programmatically
from geospark.protocol import SpatialQuery, Point

query = SpatialQuery(
    operation="find_within",
    geometry=Point(lat=51.5074, lon=-0.1278),
    radius_m=5000,
    filters={"category": "hospital"},
    temporal={"after": "2020-01-01"}
)
result = engine.execute(query)
```

### 2. `geospark.engine` -- The Reasoning Core

```
geospark/engine/
├── spatial_reasoner.py   # Topology, distance, containment operations
├── crs_handler.py        # CRS detection, transformation, validation
├── temporal_engine.py    # Time-series queries, change detection logic
├── aggregator.py         # Zonal stats, spatial joins, hexagonal aggregation
├── planner.py            # Query execution planner (optimizes multi-step queries)
├── cache.py              # Spatial-aware caching (H3-based cache keys)
└── fusion.py             # Multi-modal data alignment and fusion
```

**Key Design**: The engine is stateless and composable. Each operation takes spatial data in, returns spatial data out. Complex queries are decomposed by the planner into chains of simple operations.

### 3. `geospark.rag` -- Spatial Retrieval-Augmented Generation

```
geospark/rag/
├── spatial_index.py      # H3/S2 hexagonal spatial indexing
├── retriever.py          # Retrieve relevant spatial data for a query
├── chunker.py            # Smart spatial data chunking for context windows
├── embedder.py           # Spatial-aware embeddings (location + content)
├── ranker.py             # Rank retrieved data by spatial + semantic relevance
└── context_builder.py    # Build optimal context from spatial data
```

**Key Innovation**: Unlike text RAG where chunks are sequential, spatial RAG must handle 2D (and temporal 3D) data. GeoSpark RAG uses hexagonal indexing to chunk the world into queryable cells, each with metadata about what data is available.

### 4. `geospark.tools` -- Pluggable Tool System

```
geospark/tools/
├── base.py               # BaseTool abstract class (all tools implement this)
├── registry.py           # Tool discovery and registration
├── satellite/
│   ├── stac_client.py    # STAC API client for satellite data access
│   ├── cog_reader.py     # Cloud-Optimized GeoTIFF reader
│   └── band_math.py      # NDVI, NDWI, and custom band calculations
├── geocoding/
│   ├── nominatim.py      # OpenStreetMap Nominatim geocoder
│   └── overture.py       # Overture Maps geocoder
├── terrain/
│   ├── elevation.py      # Elevation queries (SRTM, Copernicus DEM)
│   ├── slope_aspect.py   # Slope and aspect calculations
│   └── viewshed.py       # Viewshed analysis
├── routing/
│   ├── osrm.py           # OSRM routing engine
│   └── network.py        # Network analysis (shortest path, service areas)
├── change_detection/
│   ├── pixel_change.py   # Pixel-level change detection
│   ├── object_change.py  # Object-level change detection
│   └── temporal_stack.py # Multi-temporal image stack analysis
├── climate/
│   ├── era5.py           # ERA5 reanalysis data access
│   └── weather.py        # Current weather data
└── custom/               # Community-contributed tools
    └── README.md         # How to create a custom tool
```

**Plugin Interface**:
```python
from geospark.tools.base import BaseTool, ToolResult

class MyCustomTool(BaseTool):
    name = "my_tool"
    description = "Does something spatial"

    def execute(self, query: SpatialQuery) -> ToolResult:
        # Implementation
        return ToolResult(data=result, metadata={...})
```

### 5. `geospark.integrations` -- LLM & Platform Connectors

```
geospark/integrations/
├── openai_tools.py       # OpenAI function calling / tool use
├── anthropic_tools.py    # Anthropic/Claude tool use
├── mcp_server.py         # MCP server implementation
├── langchain_tools.py    # LangChain tool wrappers
├── ollama_tools.py       # Ollama (local LLM) integration
└── generic.py            # Generic OpenAI-compatible API
```

**MCP Server**: GeoSpark exposes itself as an MCP server, allowing any MCP-compatible AI (Claude, etc.) to use spatial reasoning as a tool.

### 6. `geospark.bench` -- Evaluation Framework

```
geospark/bench/
├── __init__.py           # GeoSparkBench high-level API
├── models.py             # BenchQuestion, BenchAnswer, ModelAdapter, enums
├── runner.py             # BenchRunner (load, filter, sample, run)
├── scorer.py             # Scoring (accuracy, F1, CIs, per-category)
├── report.py             # Console, markdown, JSON, diff reports
├── generate_datasets.py  # Reproducible dataset generator
├── datasets/
│   ├── geotopo.json      # 210 topological reasoning questions
│   ├── geodistance.json  # 210 distance/proximity questions
│   ├── geochanage.json   # 36 change detection questions
│   ├── georeason.json    # 55 multi-step spatial reasoning chains
│   └── geomultimodal.json # 24 multimodal spatial questions
└── baselines/
    └── run_baselines.py  # Run evaluations against LLMs
```

**Key Design**: 535 total questions across 5 benchmarks. Dual-prompt design (natural language + structured GeoJSON) on every question. ModelAdapter protocol for plugging in any LLM provider.

### 7. `geospark.flows` -- Workflow Automation

```
geospark/flows/
├── __init__.py           # Package exports
├── flow_schema.py        # Flow, FlowStep, FlowRoute, FlowRun, FlowTrigger
├── flow_builder.py       # Fluent builder API (chainable add_step/add_route/build)
├── flow_runner.py        # Topological execution engine (Kahn's algorithm)
└── templates.py          # Pre-built flow templates (vegetation, distance, area, change)
```

**Key Design**: Flows are directed acyclic graphs (DAGs) of steps. The runner uses topological sorting to determine execution order, evaluates conditions for dynamic routing, and resolves cross-step parameter references (`{step_id.key}`). Templates provide starting points for common spatial workflows.

### 8. `geospark.knowledge` -- Spatial Knowledge Graph

```
geospark/knowledge/
├── __init__.py           # Package exports
├── entities.py           # SpatialEntity, SpatialRelation (Pydantic models)
├── graph.py              # SpatialKnowledgeGraph (BFS, auto-relate, query)
└── loaders.py            # GeoJSONLoader, OverpassLoader
```

**Key Design**: In-memory graph where entities have geometries and typed relations. Auto-relate discovers spatial relationships (contains, intersects, within, near) between entities. Natural language query parser supports "find X near Y" patterns. BFS for shortest path between entities.

### 9. `geospark.plugins` -- Community Plugin System

```
geospark/plugins/
├── __init__.py           # Package exports
├── manifest.py           # PluginManifest (geospark.plugin.json schema)
├── loader.py             # PluginLoader (discover, load, validate, unload)
└── hooks.py              # PluginHooks (5 lifecycle callbacks)
```

**Key Design**: Plugins are directories containing a `geospark.plugin.json` manifest and a Python module with a `BaseTool` subclass. The loader discovers plugins by scanning directories, validates entry points and dependencies, and dynamically imports tool classes via `importlib`. Hooks provide before/after/error callbacks for tool lifecycle events.

---

## Data Architecture

### Spatial Database Options (Pluggable)

| Backend | Use Case | Pros | Cons |
|---|---|---|---|
| **SpatiaLite** | Default, single-user, no setup | Zero config, portable | Limited scale |
| **DuckDB Spatial** | Analytics, large datasets | Fast OLAP, GeoParquet native | Newer ecosystem |
| **PostGIS** | Production, multi-user | Industry standard, full topology | Requires server |

### Spatial Indexing Strategy

GeoSpark uses **H3 hexagonal indexing** (Uber's system) as its primary spatial index:

- **Why H3**: Uniform hexagonal cells avoid edge effects of rectangular grids; hierarchical resolution (0-15); efficient neighbor traversal; well-supported ecosystem
- **Resolution mapping**:
  - H3 res 4 (~1,770 km^2): Continental-scale queries
  - H3 res 7 (~5.16 km^2): City-scale queries
  - H3 res 9 (~0.105 km^2): Neighborhood-scale queries
  - H3 res 11 (~0.002 km^2): Building-scale queries

### Caching Strategy

```
Cache Key: f"{h3_cell}:{data_source}:{temporal_key}:{query_hash}"

Levels:
1. Memory cache (LRU, configurable size)
2. Disk cache (SQLite, configurable TTL)
3. Remote cache (Redis, optional for server mode)
```

---

## Technology Stack

### Core Dependencies

| Component | Technology | Why |
|---|---|---|
| **Language** | Python 3.10+ | Geospatial ecosystem is Python-centric |
| **Spatial operations** | Shapely 2.x, PyProj | Industry standard geometry/projection libs |
| **Raster processing** | Rasterio, rio-tiler | Cloud-optimized raster access |
| **Vector processing** | GeoPandas, Fiona | Vector data manipulation |
| **Spatial database** | DuckDB + spatial ext | Zero-config, fast, GeoParquet native |
| **Spatial indexing** | h3-py | Hexagonal hierarchical spatial index |
| **API server** | FastAPI | Async, auto-docs, Pydantic integration |
| **Protocol models** | Pydantic v2 | Type-safe data models, JSON schema |
| **Data access** | pystac-client | STAC API for satellite data |
| **HTTP** | httpx | Async HTTP client |
| **CLI** | Click | CLI framework |
| **Testing** | pytest + pytest-asyncio | Standard Python testing |
| **Containerization** | Docker + docker-compose | Reproducible deployment |

### Optional Dependencies (installed per feature)

| Feature | Dependencies |
|---|---|
| PostGIS backend | psycopg2, sqlalchemy |
| MCP server | mcp-python |
| LangChain integration | langchain-core |
| GPU acceleration | torch, torchgeo |
| 3D/LiDAR support | laspy, open3d |
| Visualization | folium, matplotlib, pydeck |

---

## Development Status

| Phase | Status | Tests | Key Deliverables |
|-------|--------|-------|-----------------|
| **Phase 0** - Foundation | **Complete** | 50 | Protocol, engine, CRS, 3 tools, CLI, MCP, Docker, CI/CD |
| **Phase 1** - Launch | **Complete** | 96 | Bench v0.1 (236q), baselines, demo notebook, GitHub, README |
| **Phase 2** - Ecosystem | **Complete** | 249 | 8 tools, NormalizedResult, 3 MCP servers, memory, RAG, planner, cache, 4 LLM integrations |
| **Phase 3** - Platform | **Complete** | 441 | Bench v1.0 (535q), Flows, Knowledge Graph, Plugin System |
| **Phase 4** - Scale | **Next** | -- | Enterprise features, cloud hosting, marketplace, advanced benchmarking |

See [ROADMAP.md](ROADMAP.md) for the detailed, task-level roadmap.

---

## Deployment Architecture

### Local Development
```
pip install geospark
# or
docker run -p 8000:8000 geospark/geospark:latest
```

### Production (Docker Compose)
```yaml
services:
  geospark:
    image: geospark/geospark:latest
    ports:
      - "8000:8000"
    environment:
      - GEOSPARK_DB=postgis
      - GEOSPARK_CACHE=redis
    depends_on:
      - postgis
      - redis

  postgis:
    image: postgis/postgis:16-3.4
    environment:
      - POSTGRES_DB=geospark
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

### Cloud Deployment Options
```
                    ┌─────────────────────────┐
                    │   Load Balancer          │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
     ┌────────┴────────┐ ┌──────┴───────┐ ┌────────┴────────┐
     │ GeoSpark API    │ │ GeoSpark API │ │ GeoSpark API    │
     │ Instance 1      │ │ Instance 2   │ │ Instance N      │
     └────────┬────────┘ └──────┬───────┘ └────────┬────────┘
              │                  │                   │
              └──────────────────┼───────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
     ┌────────┴────────┐ ┌──────┴───────┐ ┌────────┴────────┐
     │ PostGIS         │ │ Redis Cache  │ │ Object Storage  │
     │ (Primary+Rep.)  │ │ (Cluster)    │ │ (S3/GCS/Azure)  │
     └─────────────────┘ └──────────────┘ └─────────────────┘
```

---

## API Design

### Python SDK

```python
import geospark

# Initialize with your LLM
engine = geospark.Engine(
    llm="anthropic",  # or "openai", "ollama", "custom"
    spatial_backend="duckdb",  # or "postgis", "spatialite"
    tools=["satellite", "geocoder", "terrain", "change_detection"]
)

# Natural language spatial query
result = engine.ask(
    "Find all hospitals within 10km of the 2024 flood zone in Valencia, Spain"
)

# Programmatic spatial query
from geospark.protocol import SpatialQuery, Polygon

query = SpatialQuery(
    operation="intersect",
    geometry=flood_zone_polygon,
    buffer_m=10000,
    filters={"category": "hospital"},
    return_fields=["name", "capacity", "distance_to_flood"]
)
result = engine.execute(query)

# Spatial reasoning chain
chain = engine.chain([
    {"operation": "geocode", "query": "Valencia, Spain"},
    {"operation": "buffer", "radius_m": 50000},
    {"operation": "find_within", "category": "hospital"},
    {"operation": "calculate_distance", "to": "flood_zone"},
    {"operation": "sort", "by": "distance", "order": "asc"}
])
result = chain.run()

# GeoSpark Bench evaluation
from geospark.bench import GeoSparkBench

bench = GeoSparkBench(model="gpt-4", tools=engine.tools)
results = bench.run(benchmarks=["geotopo", "geodistance", "geochanage"])
results.report()
```

### REST API

```
POST /api/v1/query
{
  "type": "spatial_query",
  "operation": "find_within",
  "geometry": {"type": "Point", "coordinates": [51.5074, -0.1278]},
  "radius_m": 5000,
  "filters": {"category": "hospital"}
}

POST /api/v1/ask
{
  "question": "What buildings were constructed near the Thames in the last 5 years?",
  "llm": "anthropic"
}

GET /api/v1/tools
GET /api/v1/bench/results
POST /api/v1/bench/run
```

### MCP Server Interface

```json
{
  "name": "geospark",
  "version": "1.0.0",
  "tools": [
    {
      "name": "spatial_query",
      "description": "Execute a spatial query to find, filter, or analyze geographic features",
      "parameters": { ... }
    },
    {
      "name": "satellite_view",
      "description": "View satellite imagery for a location and time period",
      "parameters": { ... }
    },
    {
      "name": "change_detection",
      "description": "Detect changes between two time periods at a location",
      "parameters": { ... }
    }
  ]
}
```

---

## Testing Strategy

### Test Pyramid

```
          ┌─────────────┐
          │  E2E Tests   │  10% - Full pipeline tests with real data
          │  (Slow)      │
         ┌┴─────────────┴┐
         │ Integration    │  30% - Tool + engine + database tests
         │ Tests          │
        ┌┴───────────────┴┐
        │  Unit Tests      │  60% - Individual function tests
        │  (Fast)          │
        └──────────────────┘
```

### Spatial-Specific Testing
- **CRS round-trip tests**: Transform data through multiple CRS and verify preservation
- **Topology validation**: Verify topological operations against PostGIS reference implementation
- **Multi-format tests**: Ingest same data in 5+ formats, verify identical results
- **Scale tests**: Verify operations work on 1M+ feature datasets
- **Benchmark regression**: Ensure benchmark scores don't regress between releases

---

## Security Considerations

- **No data exfiltration**: All processing is local by default
- **API key management**: Secure storage for data provider API keys (using keyring)
- **Input validation**: All GSP queries validated against schema before execution
- **SQL injection prevention**: Parameterized queries for all database operations
- **Rate limiting**: Configurable rate limits for API mode
- **Audit logging**: All queries logged (opt-in) for enterprise compliance
