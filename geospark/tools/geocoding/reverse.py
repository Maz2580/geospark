"""
Reverse Geocoder Tool.

Converts coordinates (longitude, latitude) to human-readable addresses
using OpenStreetMap's Nominatim service.
"""

from __future__ import annotations

from typing import Any

import httpx

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
)
from geospark.tools.base import BaseTool


class ReverseGeocoder(BaseTool):
    """Convert coordinates to addresses using Nominatim reverse geocoding.

    Takes a Point geometry and returns the nearest address with
    structured address components (house number, street, city, etc.).
    """

    name = "reverse_geocoder"
    description = (
        "Convert coordinates to a street address. Use when you have "
        "lon/lat and need a human-readable location. Returns address "
        "components. Do NOT use for address-to-coordinate lookups."
    )
    supported_operations = [SpatialOperation.REVERSE_GEOCODE.value]

    BASE_URL = "https://nominatim.openstreetmap.org/reverse"
    HEADERS = {"User-Agent": "GeoSpark/0.1 (https://github.com/geospark/geospark)"}

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute reverse geocoding.

        Args:
            query: Spatial query with a Point geometry.

        Returns:
            SpatialResult with address features.
        """
        if query.operation != SpatialOperation.REVERSE_GEOCODE:
            return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])
        if query.geometry is None:
            return SpatialResult(errors=["Reverse geocode requires a Point geometry"])

        coords = query.geometry.coordinates  # type: ignore
        lon, lat = coords[0], coords[1]
        params = self._build_params(lat, lon, query)

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(
                    self.BASE_URL,
                    params=params,
                    headers=self.HEADERS,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            return SpatialResult(errors=[f"Reverse geocoding failed: {e}"])

        return self._parse_response(data, lat, lon)

    def _build_params(
        self, lat: float, lon: float, query: SpatialQuery
    ) -> dict[str, Any]:
        """Build Nominatim reverse geocoding request parameters.

        Args:
            lat: Latitude of the point.
            lon: Longitude of the point.
            query: Original spatial query for extra options.

        Returns:
            Dictionary of query parameters.
        """
        params: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "format": "geojson",
            "addressdetails": 1,
        }
        # Allow zoom level override via metadata
        if query.metadata and "zoom" in query.metadata:
            params["zoom"] = query.metadata["zoom"]
        return params

    def _parse_response(
        self, data: dict[str, Any], lat: float, lon: float
    ) -> SpatialResult:
        """Parse Nominatim GeoJSON response into SpatialResult.

        Args:
            data: Raw GeoJSON response from Nominatim.
            lat: Query latitude.
            lon: Query longitude.

        Returns:
            Parsed SpatialResult.
        """
        features = []
        if "features" in data:
            for f in data["features"]:
                props = f.get("properties", {})
                address = props.get("address", {})
                features.append(
                    SpatialFeature(
                        geometry=f.get("geometry", {}),
                        properties={
                            "display_name": props.get("display_name", ""),
                            "address": address,
                            "type": props.get("type", ""),
                            "category": props.get("category", ""),
                            "place_id": props.get("place_id"),
                        },
                    )
                )

        display = features[0].properties["display_name"] if features else "unknown"
        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Reverse geocoded ({lat:.6f}, {lon:.6f}): {display}",
            ),
            sources=["openstreetmap-nominatim"],
        )
