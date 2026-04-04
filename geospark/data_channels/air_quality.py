"""
Air Quality data channel — OpenAQ API (free, no API key required).

Provides real-time and historical air quality measurements from
government monitoring stations worldwide. Covers PM2.5, PM10, NO2,
O3, SO2, CO, and other pollutants.

Tier 0: Free, no authentication required.
Source: https://openaq.org/
"""

from __future__ import annotations

from typing import Any

import httpx

from geospark.data_channels.base import ChannelResult, ChannelStatus
from geospark.mcp_servers.launcher import MCPServerLauncher


class AirQualityChannel:
    """Air quality data via OpenAQ API."""

    name = "air-quality"
    description = "Real-time air quality from government stations worldwide (OpenAQ, free API key)"
    tier = 1  # OpenAQ v3 requires free API key registration

    API_URL = "https://api.openaq.org/v3"

    def __init__(self) -> None:
        import os

        self._api_key = os.getenv("OPENAQ_API_KEY", "")

    def check(self) -> ChannelStatus:
        """Check OpenAQ API availability and configuration."""
        if not self._api_key:
            return ChannelStatus(
                name=self.name,
                status="unconfigured",
                message="Set OPENAQ_API_KEY env var (free at https://openaq.org/register)",
                tier=self.tier,
            )
        try:
            resp = httpx.get(
                f"{self.API_URL}/locations",
                params={"limit": 1},
                headers={"X-API-Key": self._api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                return ChannelStatus(
                    name=self.name, status="ok", message="OpenAQ API reachable", tier=self.tier
                )
            return ChannelStatus(
                name=self.name, status="warn", message=f"API returned {resp.status_code}", tier=self.tier
            )
        except Exception as e:
            return ChannelStatus(
                name=self.name, status="error", message=str(e), tier=self.tier
            )

    async def search(
        self,
        location: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ChannelResult:
        """Get air quality data for a location.

        Args:
            location: Place name (will be geocoded).
            lat/lon: Direct coordinates.
            filters: Optional:
                - radius_m: search radius (default 25000)
                - parameter: specific pollutant (pm25, pm10, no2, o3, so2, co)
                - limit: max stations (default 10)
        """
        filters = filters or {}
        radius = filters.get("radius_m", 25000)
        limit = filters.get("limit", 10)

        # Resolve coordinates
        if lat is not None and lon is not None:
            resolved_lat, resolved_lon = lat, lon
            location_name = f"({lat}, {lon})"
        elif location:
            resolved_lat, resolved_lon, location_name = await self._geocode(location)
            if resolved_lat is None:
                return ChannelResult(
                    channel=self.name, query={"location": location},
                    errors=[f"Could not geocode: {location}"],
                )
        elif bbox:
            resolved_lat = (bbox[0] + bbox[2]) / 2
            resolved_lon = (bbox[1] + bbox[3]) / 2
            location_name = "bbox center"
        else:
            return ChannelResult(channel=self.name, errors=["Provide location, lat/lon, or bbox"])

        if not self._api_key:
            return ChannelResult(
                channel=self.name,
                query={"location": location_name},
                errors=["OPENAQ_API_KEY not set. Register free at https://openaq.org/register"],
            )

        # Query OpenAQ v3 for nearby stations with latest measurements
        params: dict[str, Any] = {
            "coordinates": f"{resolved_lat},{resolved_lon}",
            "radius": radius,
            "limit": limit,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.API_URL}/locations",
                    params=params,
                    headers={"X-API-Key": self._api_key},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return ChannelResult(
                channel=self.name,
                query={"location": location_name, "lat": resolved_lat, "lon": resolved_lon},
                errors=[f"OpenAQ API error: {e}"],
            )

        features = []
        for result in data.get("results", []):
            station_name = result.get("location", "Unknown station")
            coords = result.get("coordinates", {})

            measurements = {}
            for m in result.get("measurements", []):
                param_name = m.get("parameter", "")
                measurements[param_name] = {
                    "value": m.get("value"),
                    "unit": m.get("unit", ""),
                    "last_updated": m.get("lastUpdated", ""),
                }

            # Calculate AQI category for PM2.5 if available
            aqi_category = None
            pm25 = measurements.get("pm25", {}).get("value")
            if pm25 is not None:
                aqi_category = self._pm25_category(pm25)

            features.append({
                "type": "air_quality_station",
                "station_name": station_name,
                "coordinates": [coords.get("longitude"), coords.get("latitude")],
                "country": result.get("country", ""),
                "city": result.get("city", ""),
                "measurements": measurements,
                "aqi_category": aqi_category,
                "distance_m": result.get("distance"),
            })

        if not features:
            return ChannelResult(
                channel=self.name,
                query={"location": location_name, "lat": resolved_lat, "lon": resolved_lon, "radius_m": radius},
                metadata={"source": "OpenAQ (openaq.org)", "note": "No monitoring stations found within search radius"},
                source="openaq",
                total_results=0,
            )

        return ChannelResult(
            channel=self.name,
            query={"location": location_name, "lat": resolved_lat, "lon": resolved_lon, "radius_m": radius},
            features=features,
            metadata={
                "source": "OpenAQ (openaq.org)",
                "api": "free, no key required",
                "stations_found": len(features),
            },
            source="openaq",
            total_results=len(features),
        )

    async def _geocode(self, location: str) -> tuple[float | None, float | None, str]:
        """Geocode via GeoSpark's Nominatim geocoder."""
        try:
            launcher = MCPServerLauncher()
            result = launcher.handle_tool_call("geocode", {
                "explanation": f"Geocoding {location} for air quality data",
                "query": location,
            })
            if result.get("status") == "success":
                features = result.get("result", {}).get("features", [])
                if features:
                    coords = features[0].get("geometry", {}).get("coordinates", [])
                    name = features[0].get("properties", {}).get("display_name", location)
                    return coords[1], coords[0], name
        except Exception:
            pass
        return None, None, location

    @staticmethod
    def _pm25_category(value: float) -> str:
        """Categorize PM2.5 level (WHO guidelines)."""
        if value <= 12:
            return "Good"
        if value <= 35.4:
            return "Moderate"
        if value <= 55.4:
            return "Unhealthy for Sensitive Groups"
        if value <= 150.4:
            return "Unhealthy"
        if value <= 250.4:
            return "Very Unhealthy"
        return "Hazardous"
