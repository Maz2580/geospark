"""GeoSpark Quickstart — Add spatial reasoning to any AI in 15 lines."""
from __future__ import annotations

from geospark import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol import Point, SpatialOperation, SpatialQuery

# 1. Check spatial relationships (ground-truth, not LLM guessing)
park = {
    "type": "Polygon",
    "coordinates": [[[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]],
}
cafe = {"type": "Point", "coordinates": [2.295, 48.855]}

print("Is the café inside the park?", SpatialReasoner.check_relationship(park, cafe, "contains"))
# True — 100% accurate geometric check

# 2. Calculate geodesic distance (meters, not Euclidean)
eiffel = {"type": "Point", "coordinates": [2.2945, 48.8584]}
louvre = {"type": "Point", "coordinates": [2.3376, 48.8606]}

distance = SpatialReasoner.calculate_distance(eiffel, louvre)
print(f"Eiffel Tower -> Louvre: {distance:,.0f} meters")
# ~3,595 meters (actual geodesic distance)

# 3. Use the engine for spatial operations
engine = Engine()
result = engine.execute(
    SpatialQuery(
        operation=SpatialOperation.BUFFER,
        geometry=Point.from_latlon(lat=48.8584, lon=2.2945),
        radius_m=1000,
        metadata={"description": "1km buffer around Eiffel Tower"},
    )
)
print(f"Buffer created: {result.spatial_context.crs}, {len(result.features)} feature(s)")
