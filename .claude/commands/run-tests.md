# Run GeoSpark Tests

Run the test suite using the project virtual environment.

## Instructions

1. ALWAYS use the project venv: `.venv/Scripts/python.exe -m pytest` -- never system Python
2. Run the requested scope:
   - All: `.venv/Scripts/python.exe -m pytest tests/ -v`
   - Module: `.venv/Scripts/python.exe -m pytest tests/<module>/ -v`
   - Single: `.venv/Scripts/python.exe -m pytest tests/<file>.py -v`
   - Coverage: `.venv/Scripts/python.exe -m pytest tests/ -v --cov=geospark --cov-report=term-missing`
3. On failure: read failing test + source, fix, re-run failing test first, then full suite
4. Report a summary table of results
