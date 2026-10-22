# GeoSpark Bench datasets

535 spatial-reasoning questions in five benchmarks, used to measure how well LLMs
answer spatial questions with and without GeoSpark's tools.

| File | Benchmark | Questions | How it was made |
|---|---|---|---|
| `geotopo.json` | Topology (contains, intersects, within, disjoint, touches) | 210 | Generated |
| `geodistance.json` | Distance and proximity between real places | 210 | Generated |
| `georeason.json` | Multi-step spatial reasoning chains | 55 | Generated |
| `geochange.json` | Land-use / land-cover change (text-based) | 36 | Curated by the author |
| `geomultimodal.json` | Multimodal spatial questions | 24 | Curated by the author |

## Provenance

- **Generated questions** (`"source": "generated_v1.0"`) come from
  `geospark/bench/generate_datasets.py` with a fixed random seed (42). Ground-truth
  answers are computed, not hand-labelled: topology with Shapely, and distances
  geodesically on the WGS84 ellipsoid with pyproj.
- **Place coordinates** are approximate public coordinates of well-known landmarks and
  cities, entered by hand in `LANDMARKS` and related tables in that script. They are
  geographic facts (single points), not extracts from any database.
- **Curated questions** (`curated_v0.1`, `curated_v1.0`) were written by the author.

## Reproducing

```bash
python -m geospark.bench.generate_datasets
```

This regenerates the generated benchmarks identically. `tests/test_bench_reproducible.py`
checks that every question and ground-truth answer still matches the published files,
so a change to the generator or the geometry engine can't silently alter the benchmark.

## Licence

Apache License 2.0, the same as the rest of GeoSpark. If you use the benchmark in
research, please cite GeoSpark (see `CITATION.cff` in the repository root).
