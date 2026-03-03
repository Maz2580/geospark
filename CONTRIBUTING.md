# Contributing to GeoSpark

Thank you for your interest in contributing to GeoSpark! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/geospark/geospark.git
cd geospark

# Create virtual environment (required -- never install globally)
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in development mode with all dev dependencies
pip install -e ".[dev]"

# Verify setup
pytest tests/ -v
```

## Code Style

- **Type hints** on all public functions
- **Google-style docstrings** on all public classes and functions
- **`from __future__ import annotations`** at the top of every module
- **snake_case** for functions/variables, **PascalCase** for classes
- **Pydantic v2 BaseModel** for all data schemas
- **Coordinates**: Always `(lon, lat)` order internally (GeoJSON standard)

We use **ruff** for linting and formatting:

```bash
ruff check geospark/ tests/    # Lint
ruff format geospark/ tests/   # Format
mypy geospark/                 # Type check
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_engine.py -v

# With coverage
pytest tests/ -v --cov=geospark
```

Tests mirror the source structure: `geospark/engine/core.py` -> `tests/test_engine.py`.

## Adding a New Tool

GeoSpark tools are pluggable and lazy-loaded. To add a new tool:

1. Create `geospark/tools/<category>/<tool_name>.py`
2. Extend `BaseTool` from `geospark/tools/base.py`
3. Add MCP tool definition to `geospark/integrations/mcp_server.py` following the **What + When + Returns + Do NOT** pattern
4. Add tests in `tests/tools/test_<tool_name>.py`
5. Register in the tool registry

Tool descriptions must include:
- What it does
- When to use it
- What it returns
- What NOT to use it for (negative guidance)

Every tool must accept an `explanation` parameter (forces the LLM to reason before calling).

## Pull Request Process

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes with tests
4. Ensure all tests pass: `pytest tests/ -v`
5. Ensure linting passes: `ruff check geospark/ tests/`
6. Submit a pull request with a clear description

## Key Conventions

- **Coordinate order**: GeoJSON uses `[lon, lat]`, NOT `[lat, lon]`. Always verify.
- **CRS safety**: Never assume EPSG:4326. Always check and transform using `crs_handler.py`.
- **Async I/O**: Use `httpx` for HTTP, not `requests`. Use `async` where I/O is involved.
- **No hard-coded LLM providers**: All integrations go through `integrations/`.
- **Structured results**: Tool results must include `status`, `result`, and `metadata` (with `crs`).

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
