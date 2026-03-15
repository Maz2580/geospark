"""
OSRM Route Tool.

Calculates driving routes between points using the OSRM (Open Source
Routing Machine) public demo server.
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


class OSRMRouteTool(BaseTool):
    """Calculate routes between two points using OSRM.

    Uses the public OSRM demo server for driving directions.
    Requires origin and destination coordinates in query metadata.
    """

    name = "router"
    description = (
        "Calculate driving routes between two points. Use when you need "
        "distance, duration, or turn-by-turn directions. Returns route "
        "geometry, distance (meters), and duration (seconds). "
        "Do NOT use for non-driving modes (walking, cycling)."
    )
    supported_operations = [
        SpatialOperation.ROUTE.value,
        SpatialOperation.ISOCHRONE.value,
    ]

    BASE_URL = "https://router.project-osrm.org"

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute routing query.

        Args:
            query: Spatial query with origin/destination in metadata.
                Expected metadata keys:
                - origin: [lon, lat]
                - destination: [lon, lat]

        Returns:
            SpatialResult with route geometry and stats.
        """
        if query.operation == SpatialOperation.ROUTE:
            return self._calculate_route(query)
        elif query.operation == SpatialOperation.ISOCHRONE:
            return self._isochrone_stub(query)
        return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])

    def _calculate_route(self, query: SpatialQuery) -> SpatialResult:
        """Calculate a route between origin and destination."""
        origin, destination, error = self._extract_points(query)
        if error:
            return SpatialResult(errors=[error])

        url = self._build_route_url(origin, destination)
        try:
            with httpx.Client(timeout=15) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            return SpatialResult(errors=[f"OSRM routing failed: {e}"])

        return self._parse_route_response(data, origin, destination)

    def _extract_points(
        self, query: SpatialQuery
    ) -> tuple[list[float] | None, list[float] | None, str | None]:
        """Extract origin and destination from query metadata.

        Args:
            query: Spatial query.

        Returns:
            Tuple of (origin, destination, error_message).
        """
        if not query.metadata:
            return None, None, "Route requires metadata with 'origin' and 'destination'"
        origin = query.metadata.get("origin")
        destination = query.metadata.get("destination")
        if not origin or not destination:
            return None, None, "Route requires 'origin' [lon,lat] and 'destination' [lon,lat] in metadata"
        return origin, destination, None

    def _build_route_url(
        self, origin: list[float], destination: list[float]
    ) -> str:
        """Build OSRM route API URL.

        Args:
            origin: [longitude, latitude] of start point.
            destination: [longitude, latitude] of end point.

        Returns:
            Fully-formed OSRM route URL.
        """
        coords = f"{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
        return (
            f"{self.BASE_URL}/route/v1/driving/{coords}"
            f"?overview=full&geometries=geojson&steps=true"
        )

    def _parse_route_response(
        self,
        data: dict[str, Any],
        origin: list[float],
        destination: list[float],
    ) -> SpatialResult:
        """Parse OSRM response into SpatialResult.

        Args:
            data: Raw OSRM JSON response.
            origin: Origin coordinates.
            destination: Destination coordinates.

        Returns:
            Parsed SpatialResult with route feature.
        """
        if data.get("code") != "Ok" or not data.get("routes"):
            msg = data.get("message", "No route found")
            return SpatialResult(errors=[f"OSRM error: {msg}"])

        route = data["routes"][0]
        geometry = route.get("geometry", {})
        distance_m = route.get("distance", 0)
        duration_s = route.get("duration", 0)

        # Extract step summaries
        steps = []
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                steps.append({
                    "instruction": step.get("maneuver", {}).get("type", ""),
                    "name": step.get("name", ""),
                    "distance_m": step.get("distance", 0),
                    "duration_s": step.get("duration", 0),
                })

        feature = SpatialFeature(
            geometry=geometry,
            properties={
                "distance_m": distance_m,
                "distance_km": round(distance_m / 1000, 2),
                "duration_s": duration_s,
                "duration_min": round(duration_s / 60, 1),
                "origin": origin,
                "destination": destination,
                "steps_count": len(steps),
                "steps": steps[:20],  # Cap to avoid huge payloads
            },
        )

        return SpatialResult(
            features=[feature],
            spatial_context=SpatialContext(
                total_features=1,
                summary=(
                    f"Route: {round(distance_m / 1000, 1)} km, "
                    f"{round(duration_s / 60, 1)} min, {len(steps)} steps"
                ),
            ),
            sources=["osrm-public-demo"],
        )

    def _isochrone_stub(self, query: SpatialQuery) -> SpatialResult:
        """Isochrone analysis placeholder."""
        return SpatialResult(
            spatial_context=SpatialContext(
                summary="Isochrone analysis (coming in Phase 2B). "
                "Will calculate reachable area from a point within a time limit.",
            ),
        )
