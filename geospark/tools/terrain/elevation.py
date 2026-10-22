"""
Elevation Tool.

Provides elevation data access and terrain analysis using open DEM sources.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from geospark.protocol.schema import (
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.tools.base import BaseTool, not_implemented
from geospark.tools.terrain import copernicus
from geospark.tools.terrain.vertical_datum import infer_datum


class ElevationTool(BaseTool):
    """Query elevation data and perform basic terrain analysis."""

    name = "terrain"
    description = "Query elevation, slope, and aspect for any location"
    supported_operations: ClassVar[list[str]] = [
        SpatialOperation.ELEVATION.value,
        SpatialOperation.SLOPE.value,
        SpatialOperation.VIEWSHED.value,
    ]

    # Open Elevation API (free, no key required)
    ELEVATION_API = "https://api.open-elevation.com/api/v1/lookup"

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute terrain query."""
        if query.operation == SpatialOperation.ELEVATION:
            return self._get_elevation(query)
        elif query.operation == SpatialOperation.SLOPE:
            return self._calculate_slope(query)
        elif query.operation == SpatialOperation.VIEWSHED:
            return self._viewshed(query)
        return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])

    def _get_elevation(self, query: SpatialQuery) -> SpatialResult:
        """Get elevation for a point.

        Reads Copernicus DEM GLO-30 (30 m) when rasterio is installed, and
        falls back to the Open Elevation API, which is much coarser: it read
        Wollumbin's summit about 200 m low. The source used is reported with
        every value.
        """
        if query.geometry is None:
            return SpatialResult(errors=["Elevation requires a geometry"])

        coords = query.geometry.coordinates  # type: ignore
        lon, lat = float(coords[0]), float(coords[1])  # type: ignore[arg-type]

        notes: list[str] = []
        if copernicus.available():
            try:
                height = copernicus.read_height(lat, lon)
                return self._elevation_result(
                    lat, lon, height, copernicus.SOURCE_ID, copernicus.ATTRIBUTION
                )
            except copernicus.NoLandTileError:
                notes.append(
                    "No Copernicus GLO-30 tile here (usually open sea); used Open Elevation."
                )
            except (RuntimeError, ValueError) as e:
                notes.append(f"Copernicus GLO-30 unavailable ({e}); used Open Elevation.")

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    self.ELEVATION_API,
                    params={"locations": f"{lat},{lon}"},
                )
                response.raise_for_status()
                data = response.json()
            elevation = data["results"][0]["elevation"]
        except Exception as e:
            return SpatialResult(errors=[f"Elevation query failed: {e}"])

        result = self._elevation_result(lat, lon, elevation, "open-elevation-api", None)
        if notes:
            result.features[0].properties["fallback_note"] = " ".join(notes)
        return result

    @staticmethod
    def _elevation_result(
        lat: float, lon: float, elevation: float, source: str, attribution: str | None
    ) -> SpatialResult:
        """Wrap one elevation value with its source and vertical datum."""
        datum = infer_datum(source)
        properties = {
            "elevation_m": elevation,
            "latitude": lat,
            "longitude": lon,
            "elevation_source": datum.source,
            "vertical_datum": datum.datum,
            "height_type": datum.height_type,
            "geoid_model": datum.geoid_model,
            "datum_confidence": datum.confidence,
            "datum_note": datum.note,
        }
        if attribution:
            properties["attribution"] = attribution
        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry={"type": "Point", "coordinates": [lon, lat]},
                    properties=properties,
                )
            ],
            spatial_context=SpatialContext(
                total_features=1,
                summary=f"Elevation at ({lat:.4f}, {lon:.4f}): {elevation}m ({datum.datum}, {datum.source})",
            ),
            sources=[source],
            confidence=None,
        )

    def _calculate_slope(self, query: SpatialQuery) -> SpatialResult:
        """Calculate slope from DEM data."""
        return not_implemented("Slope calculation")

    def _viewshed(self, query: SpatialQuery) -> SpatialResult:
        """Calculate viewshed from an observation point."""
        return not_implemented("Viewshed analysis")
