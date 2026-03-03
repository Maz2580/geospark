# Lint and Format GeoSpark Code

Run linting and formatting on the codebase using ruff.

## Instructions

1. Always use venv: `.venv/Scripts/python.exe -m ruff`
2. Steps:
   - Check: `.venv/Scripts/python.exe -m ruff check geospark/ tests/`
   - Fix auto-fixable: `.venv/Scripts/python.exe -m ruff check --fix geospark/ tests/`
   - Format: `.venv/Scripts/python.exe -m ruff format geospark/ tests/`
3. Report what was fixed
4. If issues remain that can't be auto-fixed, list them and fix manually
