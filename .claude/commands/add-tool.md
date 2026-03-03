# Add a new GeoSpark tool

Create a new pluggable spatial tool for GeoSpark. This skill scaffolds the tool module, registers it, writes tests, and updates documentation.

## Instructions

1. Read `geospark/tools/base.py` to understand the `BaseTool` interface
2. Read `geospark/tools/registry.py` to see how tools are registered
3. Ask the user for:
   - Tool name (e.g., "flood_risk")
   - Tool category (e.g., "hydrology")
   - Description of what it does
   - What spatial operations it supports
   - What external data sources or APIs it uses
4. Create the tool file at `geospark/tools/<category>/<tool_name>.py`:
   - Must extend `BaseTool`
   - Must define `name`, `description`, `supported_operations`
   - Must implement `execute(self, query: SpatialQuery) -> SpatialResult`
   - Add `__init__.py` in the category directory if it doesn't exist
5. Register the tool in `geospark/tools/registry.py` TOOL_CLASSES dict
6. Write tests at `tests/tools/test_<tool_name>.py`
7. Run tests using the venv: `.venv/Scripts/python.exe -m pytest tests/tools/test_<tool_name>.py -v`

## Checklist
- [ ] Tool extends BaseTool
- [ ] Supports at least one SpatialOperation
- [ ] Returns SpatialResult with proper features and context
- [ ] Registered in TOOL_CLASSES
- [ ] Tests pass
- [ ] Uses httpx for any HTTP calls (not requests)
- [ ] Handles errors gracefully (returns SpatialResult with errors, never raises)
