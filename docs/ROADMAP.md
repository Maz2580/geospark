# GeoSpark Roadmap

**Last updated**: March 2026
**Current phase**: Phase 1D (Launch) / Phase 2A (Remote Sensing Tools)

This is the **working roadmap** -- the concrete, ordered steps we follow session by session.
For the full strategic vision, see PRD.md, ARCHITECTURE.md, and BUSINESS_PLAN.md.

---

## What's Built (Phase 0 -- COMPLETE)

Everything checked off below is working and tested (50 tests passing).

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
- [x] 50 tests (protocol, engine, MCP, OpenRouter, system prompt)
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
- [ ] Verify CI/CD runs on GitHub

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
- [ ] 60-second demo GIF or screenshot for README

**Exit criteria**: Non-technical person can look at the notebook and immediately
understand why GeoSpark matters.

### Phase 1D: Launch

- [x] Polish README (badges, install instructions, architecture diagram, benchmark table)
- [x] Prepare launch posts (docs/launch/):
  - Hacker News: "GeoSpark: Give any AI model spatial reasoning (LLMs fail 80% of spatial tasks)"
  - Reddit r/MachineLearning, r/gis, r/Python
- [ ] Create PyPI package (`pip install geospark`)
- [ ] Twitter/X thread
- [ ] Submit to FOSS4G / academic venue

**Exit criteria**: Project is public, installable, and getting stars.

---

## Phase 2: Ecosystem Growth

Only start Phase 2 after Phase 1D (launch). The goal here is depth and community.

### Phase 2A: Remote Sensing & Analysis Tools

Expand GeoSpark's tool coverage with production-quality analyses.
Patterns learned from GeoRetina's Arion (MCP servers) and chat2geo (GEE analyses).

**Spectral indices** (reference: `resources/Arion/mcp-servers/geospatial-analysis/raster/`):
- [ ] NDVI -- Normalized Difference Vegetation Index
- [ ] EVI -- Enhanced Vegetation Index
- [ ] SAVI -- Soil-Adjusted Vegetation Index
- [ ] NDWI / MNDWI -- Water indices
- [ ] NDBI -- Built-up index
- [ ] Use `rasterio.MemoryFile` for in-memory raster processing (no temp files)

**Earth Engine analyses** (reference: `resources/chat2geo/lib/geospatial/gee/`):
- [ ] Google Earth Engine authentication helper (`ee.Initialize` wrapper)
- [ ] Urban Heat Island (UHI) analysis -- Landsat LST, SUHII/ISA/UHHI metrics
  - Port the exact formulas from chat2geo: `ST_B10 * 0.00341802 + 149.0 - 273.15`
  - Cloud masking via QA_PIXEL bit manipulation
  - Three composite metrics: SUHII (urban-rural delta), ISA (impervious surface), UHHI (LST x population)
- [ ] Land Use / Land Cover mapping -- Google Dynamic World V1 classification
- [ ] LULC Change Detection -- bi-temporal with probability masking
- [ ] Air pollution analysis -- Sentinel-5P (CO, NO2, CH4, Aerosols)
  - Percentage change mode when `start_date_2`/`end_date_2` are provided
  - Edge case handling for sign changes in percentage calculation

**Other tools**:
- [ ] Route analyzer -- OSRM integration for routing/isochrones
- [ ] Climate querier -- ERA5 / OpenWeather data access
- [ ] Population estimator -- WorldPop data access
- [ ] Reverse geocoder -- coordinates to address

**Exit criteria**: 12+ working tools across 6+ categories, all tested, all registered.

### Phase 2B: Tool Output Normalization & Routing

Make all tools return consistent, LLM-friendly results.
Pattern learned from Arion (bounds normalization) and chat2geo (enum-gated routing).

**Normalized result shape** -- every tool returns:
- [ ] `bounds_wgs84: [minx, miny, maxx, maxy]` -- always in WGS84
- [ ] `crs: "EPSG:4326"` -- explicit CRS
- [ ] `statistics: {min, max, mean, std, percentiles: {p25, p50, p75}}` -- for numeric results
- [ ] `metadata.description` -- interpretive text explaining what the values mean
  (e.g., "NDVI ranges -1 to 1. Values above 0.3 indicate healthy vegetation.")
- [ ] `metadata.data_source` -- where the data came from
- [ ] `visualization: {legend_config, geojson}` -- for map rendering
- [ ] `suggestion` -- next analysis the LLM might consider

**Enum-gated tool routing** (from chat2geo pattern):
- [ ] Add `Literal[...]` type constraints on analysis function parameters
  - Prevents LLM from hallucinating analysis names that don't exist
  - e.g., `function_type: Literal["UHI", "LULC", "LULC_Change", "Air_Pollution", "NDVI"]`

**GEE dataset catalog** (from chat2geo `searchGeeDatasets` pattern):
- [ ] Supabase table of GEE datasets with full-text search
- [ ] `search_satellite_datasets` tool -- LLM searches before loading, no hallucinated dataset IDs
- [ ] Fields: collection_id, name, description, bands, temporal_range, spatial_resolution

**Exit criteria**: All tools return the normalized shape. LLM cannot hallucinate invalid
analysis names or dataset IDs.

### Phase 2C: MCP Server Architecture

Split monolithic MCP server into domain-specific servers.
Pattern learned from Arion (6 separate FastMCP servers by domain).

- [ ] `geospark/mcp_servers/spatial_reasoning.py` -- topology, distance, containment
- [ ] `geospark/mcp_servers/spectral_indices.py` -- NDVI, EVI, SAVI, NDWI, NDBI
- [ ] `geospark/mcp_servers/geocoding.py` -- geocode, reverse geocode, batch geocode
- [ ] `geospark/mcp_servers/satellite_data.py` -- STAC search, GEE integration
- [ ] `geospark/mcp_servers/terrain.py` -- elevation, slope, aspect, viewshed
- [ ] `geospark/mcp_servers/vector_operations.py` -- buffer, dissolve, spatial join
- [ ] Launcher script: `python -m geospark.mcp_servers` starts all, or `--server spatial_reasoning` for one
- [ ] Each server independently discoverable by MCP hosts (Claude Desktop, Arion, etc.)
- [ ] XML-structured tool categories in system prompt (Arion pattern):
  ```
  <tool_category name="GeoSpark-Spectral-Indices">
    <tool_description>Calculate NDVI (MCP tool: calculate_ndvi)</tool_description>
  </tool_category>
  ```

**ROI context injection** (from geo_agentic_starter_kit pattern):
- [ ] When API/MCP request includes `drawn_geometry`, inject as user context message
  before the latest query -- allows zero-parameter tool calls on selected areas

**Exit criteria**: Each MCP server works standalone. Claude Desktop can discover and
use GeoSpark's spatial tools by adding one server config line.

### Phase 2D: Memory, Context & Session Persistence

GeoSpark should remember context across sessions and let users resume where they left off.
Inspired by Claude Code's `.claude/` memory directory and Google Opal's persistent memory.

**Conversation persistence** (`geospark/memory/`):
- [ ] Session store -- save full conversation + tool results to Supabase
  - Schema: `sessions(id, user_id, title, messages JSONB[], tool_history JSONB[], created_at, updated_at)`
  - Auto-generate title from first user message
- [ ] Resume API -- `engine.resume(session_id)` reloads conversation context
  - FastAPI endpoint: `POST /api/v1/sessions/{id}/resume`
  - CLI: `geospark resume <session_id>` or `geospark resume --latest`
- [ ] Session list -- `GET /api/v1/sessions` shows past conversations with summaries
- [ ] Context compression -- when conversation exceeds context window, summarize older
  turns while preserving tool results and spatial data

**Long-term spatial memory** (`geospark/memory/spatial_memory.py`):
- [ ] Persistent memory store in Supabase:
  - `spatial_memories(id, user_id, scope, memory_type, content, geometry, embedding, score, created_at)`
  - `scope`: "session" (this conversation) vs "project" (all conversations) vs "global" (shared)
  - `memory_type`: "tool_result" | "user_preference" | "spatial_knowledge" | "workflow_outcome"
- [ ] Auto-extract memories from tool results (e.g., "user frequently queries Paris area")
- [ ] Two-step retrieval (Arion pattern): search by embedding similarity first, retrieve full memory by ID
- [ ] Memory scoring: `final_score = similarity * 0.7 + recency * 0.3`
- [ ] User-managed: "remember this", "forget that", "what do you remember about my project?"

**GeoSpark config directory** (like Claude Code's `.claude/`):
- [ ] `~/.geospark/` or project-level `.geospark/`:
  - `memory.json` -- persistent preferences and spatial knowledge
  - `sessions/` -- cached conversation state for offline resume
  - `config.toml` -- user settings (default model, default CRS, preferred tools)
  - `credentials.toml` -- API keys (alternative to .env, encrypted at rest)

**Exit criteria**: User can close GeoSpark, reopen it next day, run `geospark resume --latest`,
and continue exactly where they left off with full spatial context preserved. Memory accumulates
across sessions ("you usually work with EPSG:32631, shall I use that?").

### Phase 2E: Spatial RAG

The deep technical moat -- spatial retrieval that no text RAG system does.

- [ ] H3 spatial indexing (`geospark/rag/spatial_index.py`)
- [ ] Spatial retriever -- find relevant features by location + semantics
- [ ] Spatial chunker -- break large datasets into context-window-sized pieces
- [ ] Context builder -- assemble optimal spatial context for LLM prompts
- [ ] Integration with spatial memory (Phase 2D) for cross-session knowledge

**Exit criteria**: `engine.ask("What hospitals are near the 2024 flood zone in Valencia?")`
retrieves relevant spatial data from the knowledge graph and answers accurately.

### Phase 2F: Engine Completeness

Fill in the engine modules promised in ARCHITECTURE.md.

- [ ] Query planner -- decompose complex queries into operation chains
- [ ] Temporal engine -- time-series queries, "what changed between X and Y"
- [ ] Aggregator -- zonal statistics, spatial joins, hexagonal aggregation
- [ ] Cache -- H3-based spatial cache keys, TTL, memory + disk levels
- [ ] Protocol extensions -- query.py (builder), validator.py, serializer.py

**Exit criteria**: Multi-step queries work (geocode → buffer → find_within → sort).

### Phase 2G: More LLM Integrations

- [ ] OpenAI function calling integration (direct, not via OpenRouter)
- [ ] Anthropic tool use integration (direct)
- [ ] LangChain tool wrapper
- [ ] Ollama integration (local models)
- [ ] Per-agent model selection (from Arion pattern: each agent can override the default model)

**Exit criteria**: GeoSpark works with 4+ LLM providers out of the box.

---

## Phase 3: Community, Workflows & Benchmark Authority

### Phase 3A: GeoSpark Bench v1.0

- [ ] Expand to 200+ questions per benchmark
- [ ] Add GeoMultiModal benchmark (combining imagery + text + vector)
- [ ] Add GeoReason benchmark (multi-step spatial reasoning chains)
- [ ] Publish academic preprint describing methodology
- [ ] Create online leaderboard (Papers With Code integration)
- [ ] Run baselines on 5+ models (GPT-4, Claude, Gemini, Llama, Mistral)

### Phase 3B: GeoSpark Flows -- AI-Powered Spatial Workflow Automation (MAJOR DIFFERENTIATOR)

Like n8n but for spatial tasks, and you don't drag-and-drop -- you describe what you want
in natural language, and the AI builds the workflow for you. Combined with Google Opal-style
agent messaging: each step in the workflow is an AI agent you can talk to.

**This is what makes GeoSpark unique**: no other spatial tool combines workflow automation
with AI agents + spatial reasoning + persistent memory.

Reference: [Google Opal agent step](https://blog.google/innovation-and-ai/models-and-research/google-labs/opal-agent/),
[n8n workflow automation](https://n8n.io/), [n8n-geo](https://github.com/paschendale/n8n-geo).

**Workflow schema** (`geospark/flows/`):
- [ ] `flow_schema.py` -- Pydantic models for workflow definition:
  ```python
  class FlowStep(BaseModel):
      id: str
      name: str                              # "Calculate NDVI"
      tool: str                              # "calculate_ndvi"
      parameters: dict[str, Any]             # tool parameters
      agent_instructions: str                # what this agent should do/know
      routes: list[FlowRoute]               # conditional next steps
      memory_scope: Literal["step", "flow"]  # what this step remembers

  class FlowRoute(BaseModel):
      condition: str         # natural language: "if NDVI < 0.3"
      target_step_id: str    # which step to go to
      description: str       # "vegetation stress detected"

  class Flow(BaseModel):
      id: str
      name: str                              # "Weekly Farm Monitor"
      description: str
      steps: list[FlowStep]
      trigger: FlowTrigger                   # manual, scheduled, event-based
      memory: dict[str, Any]                 # persistent state across runs
      created_by_chat: bool                  # was this built via conversation?
  ```

**AI-generated workflows** (chat-to-flow):
- [ ] `flow_builder.py` -- LLM generates a `Flow` from natural language:
  - User: "Monitor my farm's NDVI every Monday. If vegetation drops below 0.3, alert me
    and run a UHI analysis to check if heat stress is the cause."
  - AI creates: 4-step flow (geocode farm → NDVI analysis → condition check → UHI analysis)
  - User reviews, makes small edits, saves
- [ ] `flow_editor.py` -- modify individual steps via chat:
  - "Change the NDVI threshold to 0.25"
  - "Add a step that saves results to my Supabase project"
  - "Make it run every day instead of weekly"
- [ ] Flow templates -- pre-built flows for common spatial tasks:
  - "Farm health monitor" (NDVI + weather + alert)
  - "Urban growth tracker" (LULC change + population + area stats)
  - "Air quality reporter" (Sentinel-5P + temporal comparison + PDF report)
  - "Disaster response" (flood extent + nearest hospitals + population affected)

**Flow execution engine**:
- [ ] `flow_runner.py` -- executes a `Flow` step by step
  - Each step calls the appropriate GeoSpark tool
  - Results from step N are available to step N+1 (data piping)
  - Flow-level memory persists across runs (Supabase storage)
- [ ] **Plan-then-act** pattern (Google Opal):
  - Before executing, the agent decomposes the user's goal into steps
  - Shows the plan to the user for approval
  - Adapts dynamically if a step fails or returns unexpected results
- [ ] **Dynamic routing** (Google Opal):
  - Conditions described in natural language: "if temperature > 35°C"
  - Agent evaluates conditions using tool results and routes to correct next step
  - Multiple paths possible (branching workflows)
- [ ] **Interactive agent chat** (Google Opal):
  - Each flow step can pause and ask the user for input
  - "I found 3 possible AOIs. Which one should I analyze?" (with map preview)
  - User responds, agent continues the workflow

**Agent messaging within flows**:
- [ ] Each step has its own `agent_instructions` -- a mini system prompt
  - e.g., step 1: "You are a geocoding specialist. Find the exact boundary of the user's farm."
  - e.g., step 3: "You are a vegetation health analyst. Interpret NDVI values in context."
- [ ] Users can send messages to individual step agents:
  - "Hey step 3, use a stricter threshold of 0.2 instead of 0.3"
  - Agent updates its behavior without rebuilding the whole flow
- [ ] Inter-agent communication:
  - Step 2 agent can flag: "unusual cloud cover detected, step 3 should use a longer date range"
  - Agent-to-agent messages stored in flow memory for audit trail

**Triggers & scheduling**:
- [ ] Manual trigger (run now)
- [ ] Schedule trigger (cron-like: "every Monday at 9am")
- [ ] Event trigger (webhook: "when new Sentinel-2 image available for this AOI")
- [ ] Condition trigger ("when NDVI drops below threshold in stored AOI")
- [ ] Trigger history and run logs stored in Supabase

**Flow persistence** (Supabase schema):
- [ ] `flows(id, user_id, name, description, flow_definition JSONB, trigger JSONB, created_at)`
- [ ] `flow_runs(id, flow_id, status, started_at, completed_at, results JSONB[], agent_messages JSONB[])`
- [ ] `flow_memory(flow_id, key, value JSONB, updated_at)` -- persistent state across runs

**CLI & API**:
- [ ] `geospark flow create` -- start chat-to-flow builder
- [ ] `geospark flow list` -- show saved flows
- [ ] `geospark flow run <flow_id>` -- execute a flow
- [ ] `geospark flow edit <flow_id>` -- modify via chat
- [ ] `geospark flow history <flow_id>` -- show past runs
- [ ] REST: `POST /api/v1/flows`, `GET /api/v1/flows`, `POST /api/v1/flows/{id}/run`

**Exit criteria**: User describes a spatial workflow in natural language, AI creates it,
user makes minor edits, flow runs successfully with real data, results persist across runs.
User can message individual step agents to adjust behavior without rebuilding.

### Phase 3C: Spatial Knowledge Graph

- [ ] Administrative boundary graph (from OSM/Overture)
- [ ] POI relationship graph
- [ ] Land use context layer
- [ ] Graph query interface

### Phase 3D: Community Plugin System

Pattern learned from Arion (plugin manifest with lifecycle hooks).

- [ ] Plugin manifest format (`geospark.plugin.json`):
  ```json
  {
    "id": "ndvi-analysis",
    "name": "NDVI Analysis",
    "version": "1.0.0",
    "entry": "geospark/tools/satellite/ndvi.py",
    "mcp_server_name": "GeoSpark-Spectral",
    "requires": ["rasterio", "numpy"]
  }
  ```
- [ ] Plugin lifecycle hooks: before_tool_call, after_tool_call, tool_result_persist
- [ ] Flow step plugins -- community-contributed workflow steps
- [ ] Tool submission process (PR-based with auto-testing)
- [ ] Tool quality scoring
- [ ] Community leaderboard
- [ ] GeoSpark Hub web portal (tool + flow template discovery)

---

## Phase 4: Enterprise & Scale

### Phase 4A: Enterprise Features

- [ ] Multi-tenant server mode
- [ ] Authentication (SSO/SAML)
- [ ] Audit logging
- [ ] Rate limiting & usage tracking

### Phase 4B: Scale

- [ ] Distributed query execution (Dask/Ray)
- [ ] Streaming data support
- [ ] Edge deployment (ARM/Jetson)
- [ ] Planetary-scale indexing

### Phase 4C: Strategic Positioning

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
