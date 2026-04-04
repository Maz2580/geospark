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
from geospark.tools.base import BaseTool


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
        """Get elevation for a point or set of points."""
        if query.geometry is None:
            return SpatialResult(errors=["Elevation requires a geometry"])

        coords = query.geometry.coordinates  # type: ignore
        lon, lat = coords[0], coords[1]

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    self.ELEVATION_API,
                    params={"locations": f"{lat},{lon}"},
                )
                response.raise_for_status()
                data = response.json()

            elevation = data["results"][0]["elevation"]

            return SpatialResult(
                features=[
                    SpatialFeature(
                        geometry={"type": "Point", "coordinates": [lon, lat]},
                        properties={
                            "elevation_m": elevation,
                            "latitude": lat,
                            "longitude": lon,
                            "elevation_source": "open-elevation-api",
                            "vertical_datum": "SRTM (EGM96 geoid)",
                            "vertical_datum_note": (
                                "Open Elevation API uses SRTM data with EGM96 geoid. "
                                "Values are approximate orthometric heights, not WGS84 ellipsoidal."
                            ),
                        },
                    )
                ],
                spatial_context=SpatialContext(
                    total_features=1,
                    summary=f"Elevation at ({lat:.4f}, {lon:.4f}): {elevation}m (SRTM/EGM96)",
                ),
                sources=["open-elevation-api"],
            )
        except Exception as e:
            return SpatialResult(errors=[f"Elevation query failed: {e}"])

    def _calculate_slope(self, query: SpatialQuery) -> SpatialResult:
        """Calculate slope from DEM data."""
        # TODO: Implement slope calculation from raster DEM
        return SpatialResult(
            spatial_context=SpatialContext(
                summary="Slope calculation (coming in Phase 1)",
            ),
        )

    def _viewshed(self, query: SpatialQuery) -> SpatialResult:
        """Calculate viewshed from an observation point."""
        # TODO: Implement viewshed analysis
        return SpatialResult(
            spatial_context=SpatialContext(
                summary="Viewshed analysis (coming in Phase 2)",
            ),
        )
