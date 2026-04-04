"""
Weather data channel — Open-Meteo API (free, no API key required).

Provides current weather, hourly/daily forecasts, and historical data
for any location on Earth. Uses the Open-Meteo open-source weather API.

Tier 0: Free, no authentication, no rate limits for reasonable usage.
Source: https://open-meteo.com/
"""

from __future__ import annotations

from typing import Any

import httpx

from geospark.data_channels.base import ChannelResult, ChannelStatus
from geospark.mcp_servers.launcher import MCPServerLauncher


class WeatherChannel:
    """Weather data via Open-Meteo API."""

    name = "weather"
    description = "Current weather, forecasts, and historical data for any location (Open-Meteo, free)"
    tier = 0

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

    def check(self) -> ChannelStatus:
        """Check Open-Meteo API availability."""
        try:
            resp = httpx.get(
                self.FORECAST_URL,
                params={"latitude": 0, "longitude": 0, "current": "temperature_2m"},
                timeout=10,
            )
            if resp.status_code == 200:
                return ChannelStatus(
                    name=self.name, status="ok", message="Open-Meteo API reachable", tier=self.tier
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
        """Get weather data for a location.

        Args:
            location: Place name (will be geocoded). E.g., "Melbourne, Australia"
            lat/lon: Direct coordinates (skip geocoding).
            start_date/end_date: For historical data (format: YYYY-MM-DD).
            filters: Optional overrides:
                - forecast_days: int (default 3)
                - variables: list of weather variables
                - hourly: bool (include hourly data, default False)
        """
        filters = filters or {}

        # Resolve coordinates
        if lat is not None and lon is not None:
            resolved_lat, resolved_lon = lat, lon
            location_name = f"({lat}, {lon})"
        elif location:
            resolved_lat, resolved_lon, location_name = await self._geocode(location)
            if resolved_lat is None:
                return ChannelResult(
                    channel=self.name,
                    query={"location": location},
                    errors=[f"Could not geocode: {location}"],
                )
        elif bbox:
            # Use center of bbox
            resolved_lat = (bbox[0] + bbox[2]) / 2
            resolved_lon = (bbox[1] + bbox[3]) / 2
            location_name = f"bbox center ({resolved_lat:.4f}, {resolved_lon:.4f})"
        else:
            return ChannelResult(
                channel=self.name,
                errors=["Provide location, lat/lon, or bbox"],
            )

        # Build API request
        forecast_days = filters.get("forecast_days", 3)
        include_hourly = filters.get("hourly", False)

        params: dict[str, Any] = {
            "latitude": resolved_lat,
            "longitude": resolved_lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code",
            "forecast_days": forecast_days,
            "timezone": "auto",
        }

        if include_hourly:
            params["hourly"] = "temperature_2m,precipitation,wind_speed_10m,relative_humidity_2m"

        if start_date and end_date:
            params["start_date"] = start_date
            params["end_date"] = end_date

        # Call API
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.FORECAST_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return ChannelResult(
                channel=self.name,
                query={"location": location_name, "lat": resolved_lat, "lon": resolved_lon},
                errors=[f"Weather API error: {e}"],
            )

        # Build features
        features = []

        # Current conditions
        current = data.get("current", {})
        if current:
            features.append({
                "type": "current_weather",
                "location": location_name,
                "coordinates": [resolved_lon, resolved_lat],
                "temperature_c": current.get("temperature_2m"),
                "feels_like_c": current.get("apparent_temperature"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_direction_deg": current.get("wind_direction_10m"),
                "weather_code": current.get("weather_code"),
                "weather_description": self._weather_code_to_text(current.get("weather_code")),
                "time": current.get("time"),
            })

        # Daily forecast
        daily = data.get("daily", {})
        if daily and "time" in daily:
            for i, date in enumerate(daily["time"]):
                features.append({
                    "type": "daily_forecast",
                    "date": date,
                    "location": location_name,
                    "coordinates": [resolved_lon, resolved_lat],
                    "temp_max_c": daily.get("temperature_2m_max", [None])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                    "temp_min_c": daily.get("temperature_2m_min", [None])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
                    "precipitation_mm": daily.get("precipitation_sum", [None])[i] if i < len(daily.get("precipitation_sum", [])) else None,
                    "wind_max_kmh": daily.get("wind_speed_10m_max", [None])[i] if i < len(daily.get("wind_speed_10m_max", [])) else None,
                    "weather_code": daily.get("weather_code", [None])[i] if i < len(daily.get("weather_code", [])) else None,
                })

        return ChannelResult(
            channel=self.name,
            query={"location": location_name, "lat": resolved_lat, "lon": resolved_lon, "forecast_days": forecast_days},
            features=features,
            metadata={
                "timezone": data.get("timezone", ""),
                "elevation_m": data.get("elevation"),
                "source": "Open-Meteo (open-meteo.com)",
                "api": "free, no key required",
            },
            source="open-meteo",
            total_results=len(features),
        )

    async def _geocode(self, location: str) -> tuple[float | None, float | None, str]:
        """Geocode a location name using Open-Meteo's geocoding API."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    self.GEOCODING_URL,
                    params={"name": location, "count": 1},
                )
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            if not results:
                # Fallback to GeoSpark's geocoder
                return await self._geocode_fallback(location)

            r = results[0]
            name = f"{r.get('name', location)}, {r.get('country', '')}"
            return r["latitude"], r["longitude"], name.strip(", ")
        except Exception:
            return await self._geocode_fallback(location)

    async def _geocode_fallback(self, location: str) -> tuple[float | None, float | None, str]:
        """Fallback geocoding via GeoSpark's Nominatim geocoder."""
        try:
            launcher = MCPServerLauncher()
            result = launcher.handle_tool_call("geocode", {
                "explanation": f"Geocoding {location} for weather data",
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
    def _weather_code_to_text(code: int | None) -> str:
        """Convert WMO weather code to human-readable text."""
        if code is None:
            return "Unknown"
        codes = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            77: "Snow grains",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            85: "Slight snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
        }
        return codes.get(code, f"Code {code}")
