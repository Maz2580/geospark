# GeoSpark: Product Requirements Document (PRD)

**Version**: 1.0
**Date**: March 2026
**Status**: Phase 3 Complete -- 441 tests, 535 benchmark questions, 9 modules

---

## Executive Summary

**GeoSpark** is an open-source **Geospatial Intelligence Protocol & Engine** that gives any AI model genuine spatial reasoning capabilities. It is the "MCP for geospatial" -- a standardized protocol and runtime that bridges the fundamental gap between language models and spatial understanding.

Current LLMs fail catastrophically at spatial reasoning (42-80% performance drop on complex spatial tasks). No major AI company has solved this. GeoSpark fills this gap by providing:

1. **A Protocol (GSP)** -- Standardized way for AI models to query, reason about, and return geospatial information
2. **A Reasoning Engine** -- Performs topology, distance, containment, adjacency, and temporal-spatial operations that LLMs cannot
3. **A Spatial Knowledge Graph** -- Provides geographic context that grows with community contributions
4. **A Tool Ecosystem** -- Pluggable spatial operations (change detection, data fusion, CRS conversion, tiling)
5. **An Evaluation Framework (GeoSpark Bench)** -- Benchmarks for measuring spatial reasoning capabilities

**Tagline**: *"Give any AI model a spatial mind. Open source. Run anywhere."*

---

## Problem Statement

### The Core Problem
AI models cannot reason about space. They process spatial problems through language patterns, not genuine spatial understanding. This manifests as:

- **Topology failures**: LLMs mislabel "disjoint" as "overlaps" ~80% of the time
- **Distance blindness**: Cannot reliably reason about proximity, catchment areas, or spatial clustering
- **CRS confusion**: Cannot handle coordinate reference system transformations
- **Temporal-spatial gaps**: Cannot track how places change over time
- **Multi-format chaos**: No unified way to ingest satellite imagery, vector data, LiDAR, street-level photos

### Who Suffers
| User Segment | Pain Point | Current Workaround |
|---|---|---|
| **AI developers** | Can't add geospatial capabilities to their apps | Build custom pipelines from scratch (~6-12 months) |
| **GIS professionals** | AI tools don't understand their domain | Manual analysis + fragmented toolchains |
| **Researchers** | No standard way to benchmark spatial AI | Each paper creates its own evaluation |
| **Climate/disaster responders** | Can't ask natural language questions about spatial data | Expensive proprietary platforms (ArcGIS, Earth Engine) |
| **Urban planners** | Can't combine multimodal data for decision-making | Hire GIS specialists for each project |

### Market Validation
- Geospatial AI market: $37.13B (2025) → $126.58B (2035) at 22.6% CAGR
- Every major AI company has identified this gap (Google, Microsoft, Meta, Anthropic, OpenAI)
- No open-source solution exists that provides LLMs with genuine spatial reasoning

---

## Product Vision

### One-Line Vision
*GeoSpark makes spatial intelligence a first-class capability for every AI application, the same way MCP made tool use a first-class capability.*

### Vision Statement
In a world where AI can write code, generate images, and reason about complex topics, it still cannot answer: "What buildings were built within 500m of this river in the last 3 years?" GeoSpark changes this by providing an open protocol and engine that any AI model can use to understand, query, and reason about the physical world.

### Success Looks Like
- **6 months**: 5,000+ GitHub stars, adopted by 3+ geospatial research labs
- **12 months**: 20,000+ stars, integrated with 2+ major LLM providers, benchmark becomes the standard
- **24 months**: 50,000+ stars, protocol adopted as industry standard, acquisition interest from major AI companies

---

## Target Users

### Primary: AI/ML Developers (the "OpenClaw audience")
- Building AI agents and applications
- Want to add geospatial capabilities without becoming GIS experts
- Value: SDK/API that "just works" with their existing LLM pipeline
- **Size**: ~2M developers working with LLM APIs globally

### Secondary: GIS/Remote Sensing Professionals
- Domain experts frustrated by fragmented toolchains
- Want AI-powered automation of repetitive spatial tasks
- Value: LLM-powered automation that understands their domain
- **Size**: ~500K GIS professionals globally

### Tertiary: Researchers & Academics
- Need reproducible benchmarks for spatial reasoning
- Want to publish papers using standardized evaluation
- Value: GeoSpark Bench as the "ImageNet of spatial reasoning"
- **Size**: ~50K geospatial AI researchers

### Quaternary: Decision Makers (Climate, Urban, Agriculture)
- Need answers from spatial data, not raw maps
- Want natural language interface to geospatial intelligence
- Value: Ask questions, get grounded visual answers
- **Size**: ~1M professionals in climate, planning, agriculture

---

## Core Product Components

### 1. GeoSpark Protocol (GSP) -- The Standard

A JSON-based protocol for spatial queries and results, designed to be LLM-friendly.

**Why a protocol matters**: MCP succeeded because it defined a standard, not just a tool. GSP does the same for spatial intelligence.

```
GSP Query Example:
{
  "type": "spatial_query",
  "operation": "find_within",
  "geometry": { "type": "Point", "coordinates": [51.5074, -0.1278] },
  "radius_m": 5000,
  "filters": {
    "category": "hospital",
    "temporal": { "after": "2020-01-01" }
  },
  "return": ["geometry", "attributes", "distance"]
}

GSP Result:
{
  "type": "spatial_result",
  "features": [...],
  "spatial_context": {
    "crs": "EPSG:4326",
    "bbox": [...],
    "topology": { "within": "Greater London", "intersects": [...] }
  },
  "confidence": 0.94,
  "sources": ["osm", "sentinel-2-2025-02"]
}
```

**Key Design Principles**:
- LLM-readable (JSON with clear semantics)
- Composable (queries can chain)
- Source-agnostic (works with any data backend)
- Temporally-aware (every query can include time dimension)
- CRS-transparent (automatic transformation)

### 2. GeoSpark Engine -- The Brain

A Python-based reasoning engine that:

| Capability | What It Solves | How |
|---|---|---|
| **Topology reasoning** | LLMs fail at spatial relations | PostGIS-backed topology operations with natural language interface |
| **Distance & proximity** | LLMs can't reason about distance | Geodesic calculations, spatial indexing (H3, S2), catchment analysis |
| **CRS handling** | The #1 source of geospatial errors | Automatic detection and transformation via pyproj |
| **Temporal-spatial queries** | Change detection, time series | STAC integration, temporal indexing, change detection algorithms |
| **Multi-format ingestion** | Format fragmentation | Unified reader for GeoTIFF, GeoJSON, GeoParquet, Shapefile, COG, NetCDF, LAS/LAZ |
| **Multi-modal fusion** | Combining heterogeneous data | Alignment pipeline for satellite + street-level + vector + sensor data |
| **Spatial aggregation** | "Summarize this region" | Zonal statistics, hexagonal aggregation, spatial joins |

### 3. GeoSpark RAG -- Spatial Retrieval

Retrieval-Augmented Generation optimized for spatial data:

- **Spatial indexing**: H3/S2 hexagonal grids for efficient spatial retrieval
- **Semantic + spatial search**: Find relevant data by both content and location
- **Temporal retrieval**: Get the right version of data for a given time
- **Multi-resolution**: Handle data at different spatial scales
- **Context window optimization**: Spatial data is large; smart chunking and summarization

### 4. GeoSpark Tools -- The Ecosystem

Pluggable tools that extend the engine:

| Tool | Purpose | Data Sources |
|---|---|---|
| `satellite_viewer` | Browse and query satellite imagery | Sentinel-2, Landsat, Planet (via STAC) |
| `change_detector` | Detect changes between time periods | Any temporal raster data |
| `geocoder` | Convert addresses ↔ coordinates | Nominatim, Overture Maps |
| `route_analyzer` | Calculate routes, travel times, service areas | OpenStreetMap, OSRM |
| `terrain_analyzer` | Elevation, slope, aspect, viewshed | SRTM, Copernicus DEM |
| `climate_querier` | Temperature, precipitation, weather | ERA5, NOAA, OpenWeather |
| `population_estimator` | Population density, demographics | WorldPop, Meta population maps |
| `land_use_classifier` | Classify land cover from imagery | ESA WorldCover, NLCD |
| `flood_risk_assessor` | Flood susceptibility analysis | DEM + hydrology + historical floods |
| `crop_health_monitor` | NDVI, crop stress detection | Sentinel-2, Landsat |

### 5. GeoSpark Bench -- The Standard

A comprehensive benchmark suite for evaluating spatial reasoning in AI models:

| Benchmark | What It Tests | Difficulty |
|---|---|---|
| **GeoTopo** | Topological reasoning (contains, intersects, touches, etc.) | Easy → Hard |
| **GeoDistance** | Distance and proximity reasoning | Easy → Hard |
| **GeoChange** | Temporal change detection and description | Medium → Hard |
| **GeoMultiModal** | Combining visual + textual + vector spatial data | Hard |
| **GeoReason** | Complex multi-step spatial reasoning chains | Very Hard |
| **GeoWorld** | Real-world geospatial questions with ground truth | Very Hard |

**Why this matters**: Whoever defines the benchmark defines the field. GeoSpark Bench becomes the standard way to evaluate spatial reasoning, citing GeoSpark in every paper.

---

## Key Differentiators

### vs. Google Earth AI (closest competitor)
| Dimension | Google Earth AI | GeoSpark |
|---|---|---|
| **Open source** | No (proprietary) | Yes (Apache 2.0) |
| **Run anywhere** | Google Cloud only | Local, any cloud, edge |
| **Data privacy** | Data goes to Google | Data stays with you |
| **Extensible** | Limited | Fully pluggable |
| **LLM agnostic** | Gemini only | Any LLM |
| **Protocol** | Proprietary API | Open standard (GSP) |
| **Cost** | Enterprise pricing | Free (pay for compute/LLM only) |

### vs. LangChain/LlamaIndex (general AI frameworks)
- GeoSpark is purpose-built for spatial reasoning, not a general framework
- Handles CRS, topology, multi-band imagery, temporal data natively
- Spatial RAG is fundamentally different from text RAG
- Tools are geospatial-specific with domain expertise built in

### vs. TorchGeo/Rasterio/GeoPandas (geospatial libraries)
- GeoSpark orchestrates these tools rather than replacing them
- Adds the AI/reasoning layer on top
- Natural language interface to complex spatial operations
- Protocol-based, designed for LLM integration

---

## Defensible Moats

### 1. Protocol Standard (Network Effect)
Once GSP is adopted by even a few major projects, it becomes the standard. Switching costs increase with adoption. This is the strongest moat.

### 2. Community Ecosystem
Tools, adapters, benchmarks, and spatial knowledge contributions from the community create value that no single company can replicate.

### 3. Benchmark Authority
GeoSpark Bench becomes the "ImageNet of spatial reasoning." Every paper evaluating spatial AI cites and uses it. This creates permanent mindshare.

### 4. Spatial Knowledge Graph
Geographic context (what's near what, administrative boundaries, land use patterns) grows with community contributions and is unique to GeoSpark.

### 5. Domain Expertise
Building credible geospatial AI tools requires BOTH AI expertise AND domain expertise. Most AI companies have the former but not the latter. Your geospatial background is a competitive advantage.

---

## Technical Requirements

### Performance
- Protocol response time: <500ms for simple spatial queries
- Multi-format ingestion: Handle GeoTIFF up to 10GB, GeoJSON up to 1GB
- Spatial indexing: Support 100M+ features with sub-second query
- Concurrent users: Support 100+ concurrent queries in server mode

### Compatibility
- Python 3.10+
- LLM providers: OpenAI, Anthropic, Google, Ollama (local), any OpenAI-compatible API
- Data formats: GeoTIFF, COG, GeoJSON, GeoParquet, Shapefile, KML, GeoPackage, NetCDF, LAS/LAZ
- Spatial backends: PostGIS, SpatiaLite, DuckDB Spatial, in-memory (GeoPandas)
- Cloud: AWS, GCP, Azure, self-hosted
- Edge: ARM support for Raspberry Pi / NVIDIA Jetson deployment

### Security & Privacy
- All data processing local by default
- No telemetry without explicit opt-in
- Support for air-gapped environments
- Credential management for data source authentication

---

## User Stories

### AI Developer Stories
1. As a developer, I want to add spatial reasoning to my ChatGPT-like app so that users can ask questions about locations
2. As a developer, I want to connect my LLM to satellite imagery so it can answer "what changed here?"
3. As a developer, I want to handle CRS transformations automatically so I don't need GIS expertise

### GIS Professional Stories
4. As a GIS analyst, I want to ask natural language questions about my spatial data so I can get answers faster
5. As a remote sensing specialist, I want to automate change detection workflows so I can process more data
6. As a cartographer, I want AI to suggest optimal visualizations for my spatial data

### Researcher Stories
7. As a researcher, I want a standard benchmark for spatial reasoning so I can compare models
8. As a researcher, I want reproducible spatial AI experiments so my results are verifiable

### Decision Maker Stories
9. As a disaster responder, I want to ask "show me all buildings affected by flooding in the last 24 hours"
10. As an urban planner, I want to ask "what impact would a new highway have on traffic patterns within 10km?"

---

## Release Strategy

### Phase 0: Foundation (Months 1-2)
- Core protocol specification (GSP v0.1)
- Basic spatial reasoning engine (topology, distance, CRS)
- 3 tools (geocoder, satellite_viewer, terrain_analyzer)
- Python SDK with OpenAI/Anthropic integration
- Demo notebook showing "LLM + GeoSpark vs. LLM alone"

### Phase 1: Launch (Months 3-4)
- GSP v1.0 with full specification
- 8 tools covering major use cases
- GeoSpark Bench v1.0 (3 benchmarks: GeoTopo, GeoDistance, GeoChange)
- CLI interface
- Docker container for easy deployment
- Hacker News / Reddit launch
- Academic preprint on spatial reasoning benchmark

### Phase 2: Ecosystem (Months 5-8)
- Spatial RAG with H3/S2 indexing
- Multi-modal fusion pipeline
- Community tool registry
- Plugin system for custom tools
- MCP server integration (GeoSpark as MCP tool)
- Partnerships with 3+ geospatial data providers

### Phase 3: Scale (Months 9-12)
- Spatial Knowledge Graph
- Real-time streaming data support
- Edge deployment (ARM, NVIDIA Jetson)
- Enterprise features (auth, multi-tenant, audit logging)
- GeoSpark Bench v2.0 (6 benchmarks)
- Conference presentations (FOSS4G, AGU, NeurIPS)

---

## Metrics & KPIs

| Metric | 6-Month Target | 12-Month Target |
|---|---|---|
| GitHub Stars | 5,000 | 20,000 |
| Monthly Active Users | 500 | 5,000 |
| Community Contributors | 20 | 100 |
| Published Tools | 15 | 40 |
| Academic Citations | 5 | 30 |
| LLM Provider Integrations | 3 | 6 |
| Data Source Integrations | 10 | 25 |
| Enterprise Inquiries | 5 | 25 |

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Google open-sources equivalent | High | Medium | Move fast; community lock-in; protocol standard |
| Low initial adoption | High | Medium | Viral demo; academic partnerships; conference presence |
| Technical complexity too high | Medium | Medium | Modular architecture; start simple; iterate |
| Data provider API changes | Medium | High | Abstraction layer; multiple provider support |
| AI model improvements make GeoSpark less needed | Low | Low | Reasoning layer still needed; benchmark remains relevant |
| Competitor with more funding | Medium | Medium | Community moat; protocol standard; first-mover |

---

## Appendix: Competitive Landscape

### Direct Competitors (Open Source)
- **TorchGeo** (Microsoft): PyTorch for geospatial -- training focus, not reasoning
- **Clay Foundation Model**: Foundation model, not a reasoning framework
- **Prithvi (NASA/IBM)**: Foundation model for EO, not an integration protocol
- **GeoAI (opengeos)**: Educational tools, not production reasoning engine

### Indirect Competitors (Proprietary)
- **Google Earth AI + AlphaEarth**: Closest to our vision but closed-source
- **Esri ArcGIS + AI**: Enterprise, expensive, vendor-locked
- **Palantir Foundry**: Defense/enterprise, not accessible
- **Planet + Anthropic**: Partnership, not a product

### Complementary Projects (We Integrate With)
- GDAL/OGR, Rasterio, GeoPandas, Shapely, Fiona
- STAC, COG, GeoParquet ecosystem
- PostGIS, DuckDB Spatial
- LangChain, LlamaIndex (we can be a tool provider)
- MCP (we can be an MCP server)
