# Add GeoSpark Benchmark Questions

Add new questions to an existing benchmark or create a new benchmark category.

## How It Works

GeoSpark Bench datasets are generated programmatically in `geospark/bench/generate_datasets.py`.
Ground truth is computed by our engine (Shapely + pyproj) — never hand-labeled.

## Instructions

1. Read `geospark/bench/models.py` to understand the question schema:
   - `BenchQuestion` — id, benchmark, category, difficulty, dual prompts, ground truth
   - `AnswerType` — boolean, numeric, category, text
   - `BenchmarkName` — geotopo, geodistance, geochanage

2. Read `geospark/bench/generate_datasets.py` to see existing generators

3. Determine what to add:
   - **New questions for existing category** → Edit the generator function
   - **New category in existing benchmark** → Add a new section in the generator
   - **New benchmark** → Add to `BenchmarkName` enum + new generator function

4. Every question MUST have:
   ```python
   {
       "id": "geotopo_101",                    # Unique ID
       "benchmark": "geotopo",                 # Which benchmark
       "category": "contains",                 # Sub-category
       "difficulty": "medium",                 # easy/medium/hard
       "prompt_natural": "Does X contain Y?",  # Natural language
       "prompt_structured": "...\n```json\n{GeoJSON}\n```\n...",  # With geometries
       "answer_type": "boolean",               # boolean/numeric/category/text
       "ground_truth": True,                   # Computed by engine
       "ground_truth_meta": {},                # Tolerance, sources, etc.
       "geometry_a": {...},                    # GeoJSON (for programmatic use)
       "geometry_b": {...},                    # Optional second geometry
       "source": "generated_v0.1",            # Provenance
   }
   ```

5. Regenerate datasets:
   ```bash
   .venv/Scripts/python.exe -m geospark.bench.generate_datasets
   ```

6. Verify:
   ```bash
   .venv/Scripts/python.exe -m geospark.bench list
   .venv/Scripts/python.exe -m geospark.bench run --benchmark <name> --model mock --sample 0.1
   ```

7. Run tests:
   ```bash
   .venv/Scripts/python.exe -m pytest tests/test_bench.py -v
   ```

## Quality Checklist

- [ ] Every question has `prompt_natural` AND `prompt_structured` (dual-prompt design)
- [ ] Ground truth computed by GeoSpark engine, not manually labeled
- [ ] Good True/False balance (not all True or all False)
- [ ] Difficulty levels are meaningful (easy ≠ hard)
- [ ] IDs are unique within the benchmark
- [ ] Uses real-world coordinates (not synthetic unless necessary)
