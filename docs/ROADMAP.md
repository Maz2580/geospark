# GeoSpark Roadmap

**Last updated**: March 2026
**Current phase**: Phase 4 in progress — deployed live + published to PyPI

This is the **working roadmap** -- the concrete, ordered steps we follow session by session.
For the full strategic vision, see PRD.md, ARCHITECTURE.md, and BUSINESS_PLAN.md.

---

## What's Built (Phase 0 -- COMPLETE)

Everything checked off below is working and tested.

- [x] Protocol schema (GSP v0.1) -- Pydantic models for queries, results, geometries
- [x] Spatial reasoning engine -- topology, distance, buffer, centroid, area, convex hull
- [x] CRS handler -- coordinate validation, UTM suggestion, CRS info/transform
- [x] 3 working tools -- geocoder (Nominatim), satellite (STAC), terrain (elevation)
- [x] Tool registry -- lazy-loaded, pluggable BaseTool pattern
- [x] MCP server handler -- optimized tool descriptions (What+When+Returns+DoNOT)
- [x] OpenRouter integration -- 7 free model aliases, tool calling, fallback parsing
- [x] Supabase PostGIS backend -- 4 tables, 2 spatial functions, verified working
- [x] FastAPI REST server -- 8 endpoints (/health, /query, /check-relationship, /ask, etc.)
- [x] CLI (Click + Rich)
- [x] System prompt optimization -- based on Manus/Devin/Cursor/Claude Code analysis
- [x] Docker + docker-compose
- [x] CI/CD (GitHub Actions)
- [x] pyproject.toml with optional extras
- [x] .env with OpenRouter + Supabase credentials
- [x] 50 initial tests (protocol, engine, MCP, OpenRouter, system prompt)
- [x] Claude skills (8 commands) + agents (2 custom)
- [x] Full pipeline demo (examples/demo_full_pipeline.py)

---

## Phase 1: Launch Foundation

The goal of Phase 1 is to get GeoSpark from "working on my machine" to
"anyone can install it and be impressed in 5 minutes."

### Phase 1A: Git & Package (DO THIS FIRST)

No code changes -- just make the project a proper open-source repo.

- [x] `git init` + first commit (everything except .env, .venv, resources/)
- [x] Create .gitignore (verify .env and secrets are excluded)
- [x] Write README.md (tagline, 3-line quickstart, architecture diagram, badges)
- [x] Write CONTRIBUTING.md (how to add tools, run tests, code style)
- [x] Create LICENSE file (Apache 2.0)
- [x] Create GitHub repo + push (github.com/Maz2580/geospark)
- [x] Verify CI/CD runs on GitHub

**Exit criteria**: `pip install -e .` works from a fresh clone, tests pass in CI.

### Phase 1B: GeoSpark Bench v0.1 (THE DIFFERENTIATOR)

The benchmark is what makes GeoSpark citeable and shareable. Without it,
GeoSpark is "just another geo library." With it, every spatial AI paper must reference us.

- [x] Bench runner (`geospark/bench/runner.py`) -- loads datasets, runs model, scores
- [x] Bench scorer (`geospark/bench/scorer.py`) -- accuracy, F1, 95% CIs, per-category breakdown
- [x] Bench models (`geospark/bench/models.py`) -- ModelAdapter protocol, BenchQuestion, enums
- [x] Bench report (`geospark/bench/report.py`) -- console, markdown, JSON, diff mode
- [x] Bench CLI (`geospark/bench/__main__.py`) -- `python -m geospark.bench run/list`
- [x] **GeoTopo** benchmark -- 100 questions (contains, intersects, within, disjoint, touches, polygon-with-hole)
- [x] **GeoDistance** benchmark -- 100 questions (absolute distance, proximity threshold, nearest neighbor)
- [x] **GeoChange** benchmark -- 36 questions (curated real-world scenarios, text-based v0.1)
- [x] Dual-prompt design (natural + structured) on every question
- [x] Fixed geodesic distance (SpatialReasoner.calculate_distance via pyproj)
- [x] 46 bench tests passing (96 total)
- [x] Baseline evaluation script (`bench/baselines/run_baselines.py`)
- [x] Results: Gemma 12B baseline -- GeoTopo 30%, GeoDistance 43% (LLM alone)
- [x] Results table in README showing GeoSpark accuracy vs bare LLM

**Exit criteria**: `python -m geospark.bench run --benchmark geotopo --model llama-3.3-70b` works.
Results show clear accuracy gap (LLM alone ~40% vs LLM+GeoSpark ~95%+).

### Phase 1C: Demo Notebook (THE VIRAL MOMENT)

This is the thing people screenshot and share. It must be visually compelling.

- [x] Jupyter notebook: `examples/benchmark_demo.ipynb`
  - Side-by-side: LLM alone vs LLM + GeoSpark on spatial questions
  - Rich tables showing accuracy comparison across all benchmark categories
  - CRS handling demo, distance computation, topology checks
- [x] Example scripts for common use cases:
  - `examples/quickstart.py` -- 15 lines to add spatial reasoning to any LLM
  - `examples/mcp_server.py` -- run GeoSpark as MCP server for Claude
- [ ] 60-second demo GIF or screenshot for README (future)

**Exit criteria**: Non-technical person can look at the notebook and immediately
understand why GeoSpark matters.

### Phase 1D: Launch

- [x] Polish README (badges, install instructions, architecture diagram, benchmark table)
- [x] Prepare launch posts (docs/launch/):
  - Hacker News: "GeoSpark: Give any AI model spatial reasoning (LLMs fail 80% of spatial tasks)"
  - Reddit r/MachineLearning, r/gis, r/Python
- [x] PyPI package published (`pip install geospark-ai`) -- https://pypi.org/project/geospark-ai/
- [ ] Twitter/X thread (future)
- [ ] Submit to FOSS4G / academic venue (future)

**Exit criteria**: Project is public, installable, and getting stars.

---

## Phase 2: Ecosystem Growth (COMPLETE)

All Phase 2 modules are built, tested, and passing.

### Phase 2A: Remote Sensing & Analysis Tools
- [x] NDVI, EVI, SAVI, NDWI, NDBI, MSAVI spectral indices (6 total)
- [x] Route analyzer (OSRM integration)
- [x] Reverse geocoder (coordinates to address)
- [x] 8 working tools across 5 categories, all tested and registered

### Phase 2B: Tool Output Normalization & Routing
- [x] NormalizedResult shape (bounds_wgs84, crs, statistics, metadata, suggestion)
- [x] All tools return consistent, LLM-friendly results

### Phase 2C: MCP Server Architecture
- [x] 3 domain-specific MCP servers (spatial_reasoning, geocoding, terrain)
- [x] Multi-server launcher (`python -m geospark.mcp_servers`)
- [x] Each server independently discoverable by MCP hosts

### Phase 2D: Memory, Context & Session Persistence
- [x] Session store (save/resume conversations)
- [x] Spatial memory (persistent spatial knowledge)

### Phase 2E: Spatial RAG
- [x] Spatial retriever (location + semantic feature retrieval)
- [x] Spatial chunker (context-window-sized spatial chunks)
- [x] Context builder (optimal LLM context from spatial data)

### Phase 2F: Engine Completeness
- [x] Query planner (decompose complex queries into operation chains)
- [x] Temporal engine (time-series queries, change detection)
- [x] Aggregator (zonal statistics, spatial joins)
- [x] Cache (spatial-aware LRU caching)

### Phase 2G: More LLM Integrations
- [x] OpenAI function calling integration
- [x] Anthropic tool use integration
- [x] Ollama integration (local models)
- [x] Generic OpenAI-compatible API adapter
- [x] 4+ LLM providers supported out of the box

---

## Phase 3: Platform (COMPLETE)

All Phase 3 modules are built, tested (441 total tests), and passing.

### Phase 3A: GeoSpark Bench v1.0
- [x] Expanded to 200+ questions for GeoTopo (210) and GeoDistance (210)
- [x] GeoChange benchmark (36 curated change detection questions)
- [x] GeoReason benchmark (55 multi-step spatial reasoning chains: transitivity, distance chains, comparative, buffer intersection)
- [x] GeoMultimodal benchmark (24 questions combining satellite metadata + elevation + spatial context)
- [x] 535 total benchmark questions across 5 benchmarks
- [x] Dataset generator (`geospark/bench/generate_datasets.py`) for reproducible dataset creation
- [ ] Publish academic preprint describing methodology (future)
- [ ] Create online leaderboard / Papers With Code integration (future)
- [ ] Run baselines on 5+ models (future)

### Phase 3B: GeoSpark Flows
- [x] Flow schema (`flow_schema.py`) -- Flow, FlowStep, FlowRoute, FlowRun, FlowTrigger models
- [x] Fluent builder API (`flow_builder.py`) -- chainable add_step/add_route/set_trigger/build
- [x] Topological execution engine (`flow_runner.py`) -- Kahn's algorithm, condition evaluation, parameter resolution
- [x] 4 pre-built templates: vegetation_monitor, distance_analysis, area_survey, change_detection
- [x] 60 tests passing
- [ ] AI-generated workflows (chat-to-flow builder using LLM) (future)
- [ ] Interactive agent chat within flow steps (future)
- [ ] Triggers & scheduling (cron, webhook, condition-based) (future)
- [ ] Flow persistence to Supabase (future)
- [ ] CLI & REST API for flow management (future)

### Phase 3C: Spatial Knowledge Graph
- [x] SpatialEntity and SpatialRelation models (Pydantic)
- [x] SpatialKnowledgeGraph with add/find/query/neighbors/shortest_path(BFS)
- [x] Auto-relate: automatically infer spatial relationships between nearby entities
- [x] GeoJSON and Overpass loaders
- [x] Natural language query parser
- [x] Serialization (to_dict/from_dict)
- [x] 38 tests passing
- [ ] Integration with OSM/Overture administrative boundaries (future)
- [ ] Graph query interface with Cypher-like syntax (future)

### Phase 3D: Community Plugin System
- [x] Plugin manifest format (`geospark.plugin.json`) with 13 fields
- [x] Plugin discovery, loading, validation, dependency checking
- [x] 5 lifecycle hooks: before_tool_call, after_tool_call, on_error, on_load, on_unload
- [x] Dynamic class loading via importlib
- [x] 48 tests passing (including end-to-end fixture plugin test)
- [ ] GeoSpark Hub web portal for tool/flow discovery (future)
- [ ] Tool quality scoring and community leaderboard (future)

---

## Phase 4: Deployment & Distribution (IN PROGRESS)

### Phase 4A: Live Deployment (COMPLETE)
- [x] Production Docker setup (`Dockerfile.prod`, multi-stage build)
- [x] Live deployment on VM (`ubuntu@172.26.135.224`, `/mnt/geospark`)
- [x] Cloudflare Tunnel (`geospark` tunnel → `geospark.terrascout.app`)
- [x] Auto-deploy via cron (checks GitHub every 5 min, rebuilds on change)
- [x] API live at https://geospark.terrascout.app with 11 endpoints
- [x] Swagger UI at https://geospark.terrascout.app/docs

### Phase 4B: Code Quality (COMPLETE)
- [x] Geodesic buffer (64-point sampling via `geod.fwd()`, 0.2% error)
- [x] Geodesic area (`geod.geometry_area_perimeter()`, proper WGS84)
- [x] Two-geometry topology checks (was stub, now functional)
- [x] Geometric operations: union, intersection, difference (was stub)
- [x] Temporal engine: compare_periods with overlap/gap, detect_change with categories, compute_trends
- [x] 446 tests passing, 0 lint errors

### Phase 4C: MCP & PyPI (COMPLETE)
- [x] Official MCP SDK integration (`mcp>=1.0`, stdio transport)
- [x] `geospark-mcp` CLI entry point (6 tools registered)
- [x] Claude Desktop config template
- [x] Published to PyPI as `geospark-ai` v0.1.0
- [x] Install: `pip install geospark-ai[mcp]`

### Phase 4D: Local LLM & engine.ask() (COMPLETE)
- [x] Implement `engine.ask()` with auto provider fallback (Ollama → OpenRouter)
- [x] Qwen 2.5 7B deployed on server via Ollama (0.9s tool calls on CPU, no rate limits)
- [x] API `/api/v1/ask` now uses Ollama-first architecture
- [x] MCP server version fix (reports GeoSpark 0.1.0, not SDK version)

### Phase 4E: CLI & RAG Upgrades (COMPLETE)
- [x] CLI: `geospark distance`, `geospark check`, `geospark ask` commands
- [x] Embedding-based RAG via Ollama (cosine similarity, falls back to word overlap)
- [ ] Real satellite raster processing (wire up rasterio for NDVI) — deferred to Phase 5
- [ ] Run baselines on 5+ models for benchmark leaderboard — deferred to Phase 5

---

## Phase 5: Enterprise & Scale (FUTURE)

### Phase 5A: Enterprise Features
- [ ] Multi-tenant server mode
- [ ] Authentication (SSO/SAML)
- [ ] Audit logging
- [ ] Rate limiting & usage tracking

### Phase 5B: Scale
- [ ] Distributed query execution (Dask/Ray)
- [ ] Streaming data support
- [ ] Edge deployment (ARM/Jetson)
- [ ] Planetary-scale indexing

### Phase 5C: Strategic Positioning
- [ ] NeurIPS/ICLR workshop paper
- [ ] Enterprise pilot programs
- [ ] Partnership discussions with AI companies
- [ ] GeoSpark Bench v2.0 (6 benchmarks)

---

## Reference Material

Cloned repos in `resources/` for architecture reference (NOT dependencies):

| Repo | Stars | What to learn from it | Key files |
|---|---|---|---|
| **Arion** (GeoRetina) | 61 | Domain-specific MCP servers, tool pack pattern, plugin manifest, bounds_wgs84 normalization, per-agent model selection, two-step RAG memory | `mcp-servers/geospatial-analysis/`, `src/main/services/tooling/tool-registry.ts`, `src/main/services/plugin/plugin-types.ts` |
| **chat2geo** (GeoRetina) | 500 | Production GEE analyses (UHI/LULC/change/pollution), enum-gated function routing, GEE dataset catalog search, bi-temporal percentage change, standard result shape | `lib/geospatial/gee/analysis-functions/`, `app/(main)/api/chat/route.ts` |
| **geo_agentic_starter_kit** (GeoRetina) | 17 | Feature-sliced architecture, ROI context injection, MemoryFile raster pattern, clean Turf.js wrappers | `features/ai-assistant/lib/llm-tools/`, `features/geospatial-analysis/lib/turf-utils.ts` |
| **system-prompts-and-models-of-ai-tools** | -- | System prompt patterns from Manus, Devin, Cursor, Claude Code, Codex CLI | `Manus Agent Tools & Prompt/`, `Devin AI/`, `Cursor Prompts/` |
| **free-llm-api-resources** | -- | Catalog of free LLM APIs with tool calling support | `README.md` |
| **Google Opal** (web reference) | -- | Plan-then-act agent workflows, persistent memory (Google Sheets), dynamic routing, interactive chat within workflows, agent step as orchestration layer | [Blog post](https://blog.google/innovation-and-ai/models-and-research/google-labs/opal-agent/) |
| **n8n / n8n-geo** (web reference) | 60K+ | Visual workflow automation, 400+ integrations, fair-code license. n8n-geo adds QGIS spatial nodes. GeoSpark Flows improves on this with AI generation | [GitHub](https://github.com/n8n-io/n8n), [n8n-geo](https://github.com/paschendale/n8n-geo) |

---

## Decision Log

Decisions made during development that affect the roadmap:

| Date | Decision | Rationale |
|---|---|---|
| 2026-03-03 | Use OpenRouter free models instead of direct OpenAI/Anthropic | $0 cost during dev; 17 free models with tool calling |
| 2026-03-03 | Supabase for database instead of local PostGIS | Free tier, managed, PostGIS built-in, no Docker dep for DB |
| 2026-03-03 | System prompt: single-tool-per-iteration | Free models unreliable with parallel tool calls (from Manus analysis) |
| 2026-03-03 | Required `explanation` field on all tools | Improves tool selection accuracy for smaller models (from Cursor analysis) |
| 2026-03-03 | Fallback regex parser for tool calls | Some free models write tool calls as plain text, not structured JSON |
| 2026-03-04 | Split MCP server into domain-specific servers | Arion pattern: each analysis domain is independently discoverable/launchable |
| 2026-03-04 | Enum-gated function routing | chat2geo pattern: prevents LLM from hallucinating analysis names |
| 2026-03-04 | Normalized tool result shape with bounds_wgs84 | All three GeoRetina repos converge on this; improves LLM interpretation |
| 2026-03-04 | Port chat2geo GEE analyses (UHI, LULC, pollution) | Production-quality formulas, proven with 500-star adoption |
| 2026-03-04 | Plugin manifest system (Phase 3C) | Arion's lifecycle hooks pattern enables community tool ecosystem |
| 2026-03-04 | GEE dataset catalog in Supabase | chat2geo pattern: full-text search prevents hallucinated dataset IDs |
| 2026-03-04 | ROI context injection | geo_agentic_starter_kit pattern: inject drawn geometry as user context message |
| 2026-03-04 | Session persistence + resume (Phase 2D) | Users need to continue where they left off; Claude Code's `.claude/` memory proves this pattern works |
| 2026-03-04 | Long-term spatial memory with scopes | Arion's two-step memory + Opal's persistent memory; GeoSpark remembers spatial preferences and knowledge across sessions |
| 2026-03-04 | GeoSpark Flows: AI-powered workflow automation (Phase 3B) | n8n is manual drag-and-drop; Opal is Google-only. GeoSpark Flows = chat-to-workflow + spatial reasoning + open source |
| 2026-03-04 | Plan-then-act + dynamic routing in flows | Google Opal pattern: agent decomposes goal, shows plan, routes dynamically based on results |
| 2026-03-04 | Agent messaging within workflows | Google Opal pattern: each workflow step is an agent you can talk to and configure independently |
| 2026-03-04 | Flow templates for common spatial tasks | Pre-built workflows (farm monitor, urban growth, air quality, disaster response) lower barrier to entry |

---

## Competitive Positioning

```
                  HIGH SPATIAL + HIGH AUTOMATION
                               │
              Google Opal       │  *** GeoSpark ***
              (Google-only,     │  (open source, spatial reasoning,
               no spatial       │   AI workflows + memory + bench +
               reasoning)       │   MCP + free LLMs)
                               │
     CLOSED ECOSYSTEM ─────────┼──────── OPEN ECOSYSTEM
                               │
              n8n-geo           │  chat2geo / Arion
              (manual workflow, │  (chat UI, limited to
               no AI generation)│   GEE / single provider)
                               │
                  LOW SPATIAL + LOW AUTOMATION
```

GeoSpark is the only project that combines:
1. **Protocol standard (GSP)** -- none of the competitors have this
2. **Spatial reasoning engine** -- topology/CRS/distance that LLMs can't do
3. **Benchmark framework** -- citeable, shareable, defensible
4. **Multi-model free-tier routing** -- OpenRouter gives access to 200+ models at $0
5. **Domain-specific MCP servers** -- independently discoverable by any AI host
6. **AI-powered workflow automation** -- like n8n meets Opal but open source and spatial-native
7. **Persistent memory** -- conversations and spatial knowledge survive across sessions
8. **Agent messaging in workflows** -- talk to individual agents within a workflow (Opal-style)

---

## How to Use This Roadmap

1. **Before each session**: Read this file. Know which phase/task you're on.
2. **During work**: Check off items as they're completed.
3. **Phase gates**: Don't start a new phase until the exit criteria of the current phase are met.
4. **Scope creep**: If something isn't on this roadmap, ask "does this help us reach the current phase's exit criteria?"
5. **Updating**: When priorities change, update this file first, then code.
