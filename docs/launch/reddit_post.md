# GeoSpark: Open-source spatial reasoning for AI models (LLMs fail 70%+ on spatial tasks)

**TL;DR:** LLMs can't do geometry. They guess at topology, can't compute distances, and silently swap lat/lon. I built an open-source protocol + engine that gives any AI model 100% accurate spatial reasoning.

## The Problem

I benchmarked this with GeoSpark Bench v0.1 (236 spatial reasoning questions):

- "Is point A inside polygon B?" -- LLM guesses (30% accuracy)
- "How far is A from B?" (given coordinates) -- LLM can't compute (0% accuracy)
- "Which landmark is closest?" -- LLM guesses wrong (0%)

The only thing LLMs do well (84%) is proximity from world knowledge ("is Paris near Lyon?"). But real spatial applications need computation, not vibes.

## Benchmark Results

| Task | LLM Alone | GeoSpark | Gap |
|---|---|---|---|
| Topological reasoning | 30% | 100% | +70% |
| Distance computation | 43% | 100% | +57% |

## How It Works

GeoSpark provides a protocol (GSP) and engine that any LLM can use:

- **Computational geometry** via Shapely/GEOS for topology (contains, intersects, within, touches, disjoint)
- **Geodesic distance** via pyproj on WGS84 ellipsoid (exact meters, not Euclidean)
- **CRS handling** -- automatic coordinate reference system detection and transformation
- **Pluggable tools** -- geocoding (Nominatim), satellite imagery (STAC), terrain/elevation

Works as: Python library, MCP server (for Claude/ChatGPT), REST API (FastAPI), CLI

```python
from geospark.engine.spatial_reasoner import SpatialReasoner

SpatialReasoner.check_relationship(polygon, point, "contains")  # True (100% accurate)
SpatialReasoner.calculate_distance(point_a, point_b)  # 3,595 meters (geodesic)
```

## Stack

Python 3.10+, Pydantic v2, Shapely 2.x, pyproj, FastAPI, httpx. Zero cost: OpenRouter free models + Supabase free tier.

Apache 2.0 licensed.

**GitHub**: https://github.com/Maz2580/geospark

**Benchmark notebook**: https://github.com/Maz2580/geospark/blob/main/examples/benchmark_demo.ipynb

---

Subreddits: r/MachineLearning, r/gis, r/remotesensing, r/Python
