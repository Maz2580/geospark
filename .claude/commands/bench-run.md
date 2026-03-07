# GeoSpark Bench — Run & Interpret Benchmarks

Run GeoSpark Bench evaluations, interpret results, compare models, and identify spatial reasoning gaps.

Use this when you want to evaluate a model's spatial reasoning, compare two models, or understand where LLMs fail at geospatial tasks.

## Quick Reference

```bash
# List available benchmarks
.venv/Scripts/python.exe -m geospark.bench list

# Run a benchmark with mock adapter (test the framework)
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --model mock

# Run with sampling (20% of questions for quick iteration)
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --model mock --sample 0.2

# Dry run (preview questions without calling model)
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --dry-run

# Filter by difficulty or category
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --difficulty hard
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --category contains_with_hole

# Output formats
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --model mock --output markdown
.venv/Scripts/python.exe -m geospark.bench run --benchmark geotopo --model mock --output json --save results.json
```

## Python API

```python
from geospark.bench import GeoSparkBench, BenchmarkName, PromptMode, MockAdapter

# Quick run
bench = GeoSparkBench(model="mock")
results = bench.run(benchmarks=[BenchmarkName.GEOTOPO])
print(results[0].accuracy)

# Custom adapter
adapter = MockAdapter(default="True")  # or your own ModelAdapter
bench = GeoSparkBench(adapter=adapter)
results = bench.run(
    benchmarks=[BenchmarkName.GEOTOPO, BenchmarkName.GEODISTANCE],
    prompt_mode=PromptMode.STRUCTURED,
    sample=0.2,
)

# Compare two runs
from geospark.bench import report
report.diff(result_a, result_b)
```

## Available Benchmarks

| Name | Questions | Tests | Difficulty Mix |
|------|-----------|-------|---------------|
| **geotopo** | 100 | Topology: contains, intersects, within, disjoint, touches, polygon-with-hole | Easy/Medium/Hard |
| **geodistance** | 100 | Distance: absolute geodesic, proximity threshold, nearest neighbor | Easy/Medium/Hard |
| **geochanage** | 36 | Change detection: curated real-world scenarios | Easy/Medium/Hard |

## Interpreting Results

### What to look for

1. **Overall accuracy** — Raw percentage. LLMs typically score 30-50% on topology, worse on distance.
2. **Natural vs Structured gap** — Run both `PromptMode.NATURAL` and `PromptMode.STRUCTURED`. A large gap suggests the model can parse GeoJSON but can't reason spatially from text alone.
3. **Per-category breakdown** — Look for categories where accuracy drops:
   - `contains_with_hole` < 50% → Model doesn't understand polygon holes
   - `disjoint` high, `contains` low → Model defaults to "no" when unsure
   - `nearest_neighbor` low → Model can't compare multiple distances
4. **Confidence intervals** — Wide CIs (e.g., [20%-80%]) mean too few questions in that category for reliable conclusions.
5. **By difficulty** — If easy ≈ hard, the model is guessing. Real understanding shows easy > medium > hard.

### Red flags

- **Accuracy near 50% on boolean questions** → Random guessing
- **Same accuracy across all categories** → Model ignoring geometry, pattern-matching keywords
- **Structured > Natural by 30%+** → Model can compute but can't extract spatial info from text
- **All distances off by 10x+** → Model confusing km and meters, or using Euclidean not geodesic

## Adding a Custom Model Adapter

To benchmark your own model, implement the `ModelAdapter` protocol:

```python
from geospark.bench.models import ModelAdapter

class MyModelAdapter:
    @property
    def model_id(self) -> str:
        return "my-model-v1"

    def complete(self, prompt: str) -> str:
        # Call your model here and return the text response
        return my_model.generate(prompt)

# Use it
bench = GeoSparkBench(adapter=MyModelAdapter())
results = bench.run(benchmarks=[BenchmarkName.GEOTOPO])
```

## Workflow: Full Evaluation

1. **Quick sanity check**: Run with `--sample 0.2` to make sure things work
2. **Full natural run**: `--mode natural` — tests raw spatial reasoning
3. **Full structured run**: `--mode structured` — tests GeoJSON interpretation
4. **Save results**: `--output json --save results/<model>_<mode>.json`
5. **Compare**: Use `report.diff()` to compare natural vs structured, or model A vs model B
6. **Report**: `--output markdown` for README-ready tables

## Understanding the Dual-Prompt Design

Every question has two versions:

- **Natural**: `"Does the bounding box of Paris contain the Eiffel Tower? Answer with True or False."`
- **Structured**: Same question + actual GeoJSON geometries in the prompt

This is GeoSpark Bench's unique feature. The gap between natural and structured scores reveals whether a model fails because it lacks spatial data (fixable with tools) or because it lacks spatial reasoning ability (harder to fix).
