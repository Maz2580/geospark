# Show HN: GeoSpark -- Give any AI model spatial reasoning (LLMs fail 80% of spatial tasks)

I built GeoSpark because I kept watching LLMs confidently get spatial questions wrong.

Ask GPT-4: "Is the Louvre inside the 7th arrondissement?" It guesses. Ask it to compute the distance between two coordinates? It hallucinates a number.

I benchmarked this systematically (GeoSpark Bench v0.1, 236 questions):
- Topological reasoning: LLMs score 30%, GeoSpark scores 100%
- Distance computation: LLMs score 0% on coordinate-based tasks, GeoSpark scores 100%
- The only thing LLMs are decent at (84%) is proximity from world knowledge ("is Paris near Lyon?") -- but they still can't compute exact distances.

GeoSpark fixes this with a protocol + engine that gives any AI model ground-truth spatial computation:

- **Topology**: contains, intersects, within, touches -- 100% accurate via computational geometry (Shapely/GEOS)
- **Distance**: geodesic calculations on WGS84 ellipsoid -- exact meters, not guesses
- **CRS**: automatic coordinate reference system detection and transformation
- **Tools**: geocoding (Nominatim), satellite imagery (STAC), terrain/elevation

It works as a Python library, MCP server (for Claude/ChatGPT), REST API, or CLI.

```python
from geospark.engine.spatial_reasoner import SpatialReasoner

# Ground-truth, not guessing
SpatialReasoner.check_relationship(polygon, point, "contains")  # True
SpatialReasoner.calculate_distance(point_a, point_b)  # 3,595 meters
```

Zero cost during development: uses OpenRouter free models + Supabase free tier.

Tech stack: Python, Pydantic, Shapely, pyproj, FastAPI, httpx. Apache 2.0.

GitHub: https://github.com/Maz2580/geospark
Benchmark demo: https://github.com/Maz2580/geospark/blob/main/examples/benchmark_demo.ipynb
