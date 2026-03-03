# Add a GeoSpark Benchmark

Create a new benchmark for the GeoSpark Bench evaluation framework.

## Instructions

1. Read `geospark/bench/` to understand the benchmark structure
2. Ask the user for:
   - Benchmark name (e.g., "geotopo", "geodistance")
   - What spatial reasoning capability it tests
   - Difficulty levels to include
   - Number of test cases
3. Create the benchmark dataset at `geospark/bench/datasets/<name>/`:
   - `metadata.json` - benchmark description, version, category
   - `test_cases.json` - array of test cases with input, expected output, difficulty
4. Add a runner in `geospark/bench/` that loads and scores the benchmark
5. Create baseline evaluations showing how GPT-4 / Claude / Gemini perform without GeoSpark
6. Run the benchmark: `.venv/Scripts/python.exe -m pytest tests/bench/ -v`

## Test Case Format
```json
{
  "id": "geotopo_001",
  "difficulty": "easy",
  "question": "Does polygon A contain point B?",
  "geometry_a": {"type": "Polygon", "coordinates": [...]},
  "geometry_b": {"type": "Point", "coordinates": [...]},
  "expected": true,
  "category": "contains"
}
```
