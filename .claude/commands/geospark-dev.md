# GeoSpark Dev — Guided Feature Development

A guided workflow for adding new tools, benchmark questions, integrations, or engine capabilities to GeoSpark. This skill ensures every addition follows GeoSpark's established patterns and conventions.

Use this when you need to add any new feature to GeoSpark and want step-by-step guidance.

## Step 1: Identify the Feature Type

Ask the user what they want to build. The answer determines the workflow:

| Type | Entry Point | Key Pattern |
|------|-------------|-------------|
| **New Tool** | `geospark/tools/<category>/` | Extend `BaseTool`, register in `registry.py` |
| **New Benchmark** | `geospark/bench/datasets/` | `BenchQuestion` schema, dual prompts, generated ground truth |
| **New Integration** | `geospark/integrations/` | Provider-agnostic, env-var config, no hard-coded endpoints |
| **Engine Capability** | `geospark/engine/` | Static methods on `SpatialReasoner`, geodesic-correct |
| **API Endpoint** | `geospark/api.py` | FastAPI route, Pydantic request/response models |

## Step 2: Research Before Writing

Before writing any code:
1. Read the relevant existing code to understand patterns (use `find_symbol` or `Read`)
2. Check `docs/ROADMAP.md` to see if this feature is planned and what phase it belongs to
3. Check `docs/ARCHITECTURE.md` for any design guidance
4. Look at `resources/` reference repos (Arion, chat2geo) for inspiration if applicable

## Step 3: Implementation Patterns

### For New Tools

```
geospark/tools/<category>/<tool_name>.py
```

1. Read `geospark/tools/base.py` — every tool extends `BaseTool`
2. Read an existing tool (e.g., `geospark/tools/geocoding/nominatim.py`) as a template
3. Implementation checklist:
   - [ ] Extends `BaseTool`
   - [ ] Defines `name`, `description`, `supported_operations`
   - [ ] Implements `execute(query: SpatialQuery) -> SpatialResult`
   - [ ] Uses `httpx` for HTTP (never `requests`)
   - [ ] Returns `SpatialResult` with errors on failure (never raises)
   - [ ] Coordinates are always `(lon, lat)` order (GeoJSON)
4. Register in `geospark/tools/registry.py`
5. Add MCP tool definition in `geospark/integrations/mcp_server.py`:
   ```python
   # Follow the What + When + Returns + Do NOT pattern:
   {
       "name": "tool_name",
       "description": (
           "What it does. "
           "Use when [specific scenario]. "
           "Returns [what the result looks like]. "
           "Do NOT use for [common misuse]."
       ),
       "inputSchema": {
           "properties": {
               "explanation": {  # REQUIRED on every tool
                   "type": "string",
                   "description": "One sentence explaining WHY you need this.",
               },
               # ... tool-specific params
           },
           "required": ["explanation", ...],
       },
   }
   ```
6. Write tests at `tests/tools/test_<tool_name>.py`

### For New Benchmark Questions

1. Read `geospark/bench/models.py` — understand `BenchQuestion`, `AnswerType`, `Difficulty`
2. Read `geospark/bench/generate_datasets.py` — add your generator there
3. Every question MUST have:
   - `prompt_natural` — plain English question
   - `prompt_structured` — same question with GeoJSON geometries
   - `ground_truth` — computed by GeoSpark engine (never hand-labeled)
   - `difficulty` — easy/medium/hard
   - `category` — specific sub-type
4. Run generator: `.venv/Scripts/python.exe -m geospark.bench.generate_datasets`
5. Verify: `.venv/Scripts/python.exe -m geospark.bench list`

### For New Integrations

1. Read existing integrations (`openrouter.py`, `supabase_db.py`) for patterns
2. Key rules:
   - API keys from environment variables (never hard-coded)
   - All config in `.env` / `.env.example`
   - Implement as a class with clear public methods
   - Add to `geospark/integrations/__init__.py`
3. If it's an LLM provider, implement the `ModelAdapter` protocol from `bench/models.py`

### For Engine Capabilities

1. Read `geospark/engine/spatial_reasoner.py` — static methods preferred
2. Use `pyproj.Geod` for geodesic calculations (never approximate with degrees)
3. Use `shapely` for geometry operations
4. Add corresponding `SpatialOperation` enum value in `protocol/schema.py` if needed

## Step 4: Test & Verify

```bash
# Run all tests
.venv/Scripts/python.exe -m pytest tests/ -v

# Run specific test file
.venv/Scripts/python.exe -m pytest tests/<path>/test_<name>.py -v

# Lint
.venv/Scripts/python.exe -m ruff check geospark/ tests/
```

## Step 5: Document

- Update `CLAUDE.md` if the feature changes architecture or conventions
- Update `docs/ROADMAP.md` — check off completed items
- If adding a new tool, update the tool count in `README.md`

## Conventions Cheat Sheet

| Convention | Rule |
|-----------|------|
| Coordinates | `(lon, lat)` always. Use `Point.from_latlon()` at boundaries. |
| HTTP | `httpx` (async), never `requests` |
| Data models | Pydantic v2 `BaseModel` |
| Imports | `from __future__ import annotations` at top |
| Tool results | `{"status": "success/error", "tool": "name", "result": {...}, "metadata": {"crs": "EPSG:4326"}}` |
| Error handling | Return errors in result, never raise from tools |
| CRS | Never assume EPSG:4326. Always validate. |
| Venv | Always use `.venv/Scripts/python.exe` |
