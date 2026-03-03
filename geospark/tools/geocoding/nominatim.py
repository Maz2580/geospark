"""
Nominatim Geocoder Tool.

Uses OpenStreetMap's Nominatim service for geocoding and reverse geocoding.
"""

from __future__ import annotations

import httpx

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
)
from geospark.tools.base import BaseTool


class NominatimGeocoder(BaseTool):
    """Geocoding and reverse geocoding using OpenStreetMap Nominatim."""

    name = "geocoder"
    description = "Convert addresses to coordinates and coordinates to addresses"
    supported_operations = [
        SpatialOperation.GEOCODE.value,
        SpatialOperation.REVERSE_GEOCODE.value,
    ]

    BASE_URL = "https://nominatim.openstreetmap.org"
    HEADERS = {"User-Agent": "GeoSpark/0.1 (https://github.com/geospark/geospark)"}

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute geocoding operation."""
        if query.operation == SpatialOperation.GEOCODE:
            return self._geocode(query)
        elif query.operation == SpatialOperation.REVERSE_GEOCODE:
            return self._reverse_geocode(query)
        return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])

    def _geocode(self, query: SpatialQuery) -> SpatialResult:
        """Forward geocode: address/place name → coordinates."""
        search_text = (
            query.metadata.get("query", "") if query.metadata else ""
        )
        if not search_text:
            return SpatialResult(errors=["Geocode requires metadata.query"])

        with httpx.Client(timeout=10) as client:
            response = client.get(
                f"{self.BASE_URL}/search",
                params={
                    "q": search_text,
                    "format": "geojson",
                    "limit": query.limit,
                },
                headers=self.HEADERS,
            )
            response.raise_for_status()
            data = response.json()

        features = [
            SpatialFeature(
                geometry=f["geometry"],
                properties={
                    "display_name": f["properties"].get("display_name", ""),
                    "type": f["properties"].get("type", ""),
                    "importance": f["properties"].get("importance", 0),
                },
            )
            for f in data.get("features", [])
        ]

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Found {len(features)} results for '{search_text}'",
            ),
            sources=["openstreetmap-nominatim"],
        )

    def _reverse_geocode(self, query: SpatialQuery) -> SpatialResult:
        """Reverse geocode: coordinates → address/place name."""
        if query.geometry is None:
            return SpatialResult(errors=["Reverse geocode requires a point geometry"])

        coords = query.geometry.coordinates  # type: ignore
        lon, lat = coords[0], coords[1]

        with httpx.Client(timeout=10) as client:
            response = client.get(
                f"{self.BASE_URL}/reverse",
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "geojson",
                },
                headers=self.HEADERS,
            )
            response.raise_for_status()
            data = response.json()

        features = []
        if "features" in data:
            for f in data["features"]:
                features.append(
                    SpatialFeature(
                        geometry=f["geometry"],
                        properties=f.get("properties", {}),
                    )
                )

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Reverse geocoded ({lat}, {lon})",
            ),
            sources=["openstreetmap-nominatim"],
        )
