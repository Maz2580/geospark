"""
Air Quality data channel — OpenAQ API (free, no API key required).

Provides real-time and historical air quality measurements from
government monitoring stations worldwide. Covers PM2.5, PM10, NO2,
O3, SO2, CO, and other pollutants.

Tier 0: Free, no authentication required.
Source: https://openaq.org/
"""

from __future__ import annotations

import asyncio
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

        locations = data.get("results", [])
        # OpenAQ v3: /locations lists stations and their sensors; current values come from
        # /locations/{id}/latest, keyed by sensor id. Fetch those in parallel.
        latest_by_location = await self._latest_for(locations)

        features = []
        for result in locations:
            coords = result.get("coordinates") or {}
            sensors = {
                s.get("id"): (s.get("parameter") or {}) for s in result.get("sensors", [])
            }
            measurements = {}
            for reading in latest_by_location.get(result.get("id"), []):
                parameter = sensors.get(reading.get("sensorsId"))
                if not parameter or not parameter.get("name"):
                    continue
                measurements[parameter["name"]] = {
                    "value": reading.get("value"),
                    "unit": parameter.get("units", ""),
                    "last_updated": (reading.get("datetime") or {}).get("utc", ""),
                }

            # Calculate AQI category for PM2.5 if available
            aqi_category = None
            pm25 = measurements.get("pm25", {}).get("value")
            if pm25 is not None:
                aqi_category = self._pm25_category(pm25)

            country = result.get("country") or {}
            features.append({
                "type": "air_quality_station",
                "station_name": result.get("name") or "Unknown station",
                "coordinates": [coords.get("longitude"), coords.get("latitude")],
                "country": country.get("name", "") if isinstance(country, dict) else country,
                "city": result.get("locality") or "",
                "provider": (result.get("provider") or {}).get("name", ""),
                "measurements": measurements,
                "aqi_category": aqi_category,
                "distance_m": result.get("distance"),
                # Each station's data licence and required attribution, passed through
                "licenses": [
                    {
                        "name": lic.get("name", ""),
                        "attribution": (lic.get("attribution") or {}).get("name", ""),
                        "url": (lic.get("attribution") or {}).get("url", ""),
                    }
                    for lic in result.get("licenses") or []
                ],
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
                "api": "OpenAQ v3, free API key required",
                "stations_found": len(features),
            },
            source="openaq",
            total_results=len(features),
        )

    async def _latest_for(self, locations: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
        """Latest readings for each location id (``/v3/locations/{id}/latest``).

        A station whose request fails just has no readings; it doesn't fail the search.
        """
        ids = [loc.get("id") for loc in locations if loc.get("id") is not None]
        if not ids:
            return {}

        async def fetch(client: httpx.AsyncClient, location_id: Any) -> tuple[Any, list[dict[str, Any]]]:
            try:
                resp = await client.get(
                    f"{self.API_URL}/locations/{location_id}/latest",
                    headers={"X-API-Key": self._api_key},
                )
                resp.raise_for_status()
                return location_id, resp.json().get("results", [])
            except Exception:
                return location_id, []

        async with httpx.AsyncClient(timeout=15) as client:
            pairs = await asyncio.gather(*(fetch(client, i) for i in ids))
        return dict(pairs)

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
