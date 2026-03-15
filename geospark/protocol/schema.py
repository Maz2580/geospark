"""
GSP (GeoSpark Protocol) schema definitions.

These Pydantic models define the standard format for spatial queries and results.
Every interaction with GeoSpark goes through these schemas, ensuring type safety,
validation, and automatic documentation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# --- Geometry Types ---


class GeometryType(str, Enum):
    POINT = "Point"
    LINESTRING = "LineString"
    POLYGON = "Polygon"
    MULTI_POINT = "MultiPoint"
    MULTI_LINESTRING = "MultiLineString"
    MULTI_POLYGON = "MultiPolygon"


class Point(BaseModel):
    """A geographic point (longitude, latitude)."""

    type: GeometryType = GeometryType.POINT
    coordinates: tuple[float, float] = Field(
        ..., description="(longitude, latitude) in EPSG:4326"
    )

    @classmethod
    def from_latlon(cls, lat: float, lon: float) -> Point:
        """Create a Point from latitude, longitude (human-friendly order)."""
        return cls(coordinates=(lon, lat))


class LineString(BaseModel):
    type: GeometryType = GeometryType.LINESTRING
    coordinates: list[tuple[float, float]]


class Polygon(BaseModel):
    type: GeometryType = GeometryType.POLYGON
    coordinates: list[list[tuple[float, float]]]


class MultiPoint(BaseModel):
    type: GeometryType = GeometryType.MULTI_POINT
    coordinates: list[tuple[float, float]]


class MultiPolygon(BaseModel):
    type: GeometryType = GeometryType.MULTI_POLYGON
    coordinates: list[list[list[tuple[float, float]]]]


Geometry = Point | LineString | Polygon | MultiPoint | MultiPolygon


class BBox(BaseModel):
    """Bounding box: (min_lon, min_lat, max_lon, max_lat)."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)


# --- Filters ---


class TemporalFilter(BaseModel):
    """Filter by time range."""

    after: datetime | None = None
    before: datetime | None = None
    at: datetime | None = None


class SpatialFilter(BaseModel):
    """Filters for spatial queries."""

    category: str | None = Field(None, description="Feature category (e.g., 'hospital', 'road')")
    tags: dict[str, str] | None = Field(None, description="Key-value tag filters")
    temporal: TemporalFilter | None = None
    properties: dict[str, Any] | None = Field(None, description="Property-based filters")


# --- Operations ---


class SpatialOperation(str, Enum):
    """Supported spatial operations."""

    # Discovery
    FIND_WITHIN = "find_within"
    FIND_NEAREST = "find_nearest"
    FIND_INTERSECTING = "find_intersecting"

    # Topology
    CONTAINS = "contains"
    INTERSECTS = "intersects"
    TOUCHES = "touches"
    CROSSES = "crosses"
    OVERLAPS = "overlaps"
    WITHIN = "within"
    DISJOINT = "disjoint"

    # Measurement
    DISTANCE = "distance"
    AREA = "area"
    LENGTH = "length"

    # Transformation
    BUFFER = "buffer"
    UNION = "union"
    INTERSECTION = "intersection"
    DIFFERENCE = "difference"
    CONVEX_HULL = "convex_hull"
    CENTROID = "centroid"

    # Analysis
    SPATIAL_JOIN = "spatial_join"
    ZONAL_STATS = "zonal_stats"
    AGGREGATE = "aggregate"

    # Geocoding
    GEOCODE = "geocode"
    REVERSE_GEOCODE = "reverse_geocode"

    # Satellite / Raster
    SATELLITE_VIEW = "satellite_view"
    BAND_MATH = "band_math"
    CHANGE_DETECTION = "change_detection"

    # Spectral Indices
    NDVI = "ndvi"
    EVI = "evi"
    SAVI = "savi"
    NDWI = "ndwi"
    MNDWI = "mndwi"
    NDBI = "ndbi"

    # Terrain
    ELEVATION = "elevation"
    SLOPE = "slope"
    VIEWSHED = "viewshed"

    # Routing
    ROUTE = "route"
    ISOCHRONE = "isochrone"


# --- Query & Result ---


class SpatialQuery(BaseModel):
    """A GeoSpark Protocol query."""

    operation: SpatialOperation
    geometry: Geometry | None = None
    bbox: BBox | None = None
    radius_m: float | None = Field(None, description="Search radius in meters")
    filters: SpatialFilter | None = None
    limit: int = Field(100, description="Maximum number of results")
    return_fields: list[str] | None = Field(
        None, description="Specific fields to return"
    )
    crs: str = Field("EPSG:4326", description="Coordinate reference system")
    metadata: dict[str, Any] | None = None


class SpatialFeature(BaseModel):
    """A single spatial feature in a result."""

    geometry: dict[str, Any]  # GeoJSON geometry
    properties: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class SpatialContext(BaseModel):
    """Spatial context information about a result."""

    crs: str = "EPSG:4326"
    bbox: BBox | None = None
    total_features: int = 0
    topology: dict[str, Any] | None = None
    summary: str | None = None


class SpatialResult(BaseModel):
    """A GeoSpark Protocol result."""

    features: list[SpatialFeature] = Field(default_factory=list)
    spatial_context: SpatialContext = Field(default_factory=SpatialContext)
    confidence: float | None = Field(None, ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    execution_time_ms: float | None = None
    errors: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.features) == 0

    def to_geojson(self) -> dict[str, Any]:
        """Convert result to GeoJSON FeatureCollection."""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": f.geometry,
                    "properties": f.properties,
                    "id": f.id,
                }
                for f in self.features
            ],
        }
