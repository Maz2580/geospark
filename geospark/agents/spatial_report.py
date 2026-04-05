"""
SpatialReport — Comprehensive location intelligence in one command.

Produces a spatial dossier for any location: coordinates, elevation,
nearby amenities, accessibility to key services, admin context, and
an LLM-generated narrative summary.

Usage:
    reporter = SpatialReport(engine)
    report = reporter.analyze("Federation Square, Melbourne")
    print(report.summary)
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher


class NearbyItem(BaseModel):
    """A single nearby amenity."""

    name: str
    amenity_type: str
    distance_m: float
    coordinates: list[float] = Field(default_factory=list)


class AccessibilityScore(BaseModel):
    """Distance to nearest instance of a service type."""

    service: str
    nearest_name: str = ""
    distance_m: float = -1
    available: bool = False


class WeatherSnapshot(BaseModel):
    """Current weather conditions at a location."""

    temperature_c: float | None = None
    feels_like_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_kmh: float | None = None
    precipitation_mm: float | None = None
    conditions: str = ""


class AirQualitySnapshot(BaseModel):
    """Air quality summary at a location."""

    station_name: str = ""
    distance_m: float | None = None
    pm25: float | None = None
    pm25_category: str = ""
    no2: float | None = None
    o3: float | None = None


class LocationReport(BaseModel):
    """Complete spatial intelligence report for a location."""

    query: str
    coordinates: list[float] = Field(default_factory=list)
    address: str = ""
    elevation_m: float | None = None
    weather: WeatherSnapshot | None = None
    air_quality: AirQualitySnapshot | None = None
    nearby: list[NearbyItem] = Field(default_factory=list)
    accessibility: list[AccessibilityScore] = Field(default_factory=list)
    admin_area: str = ""
    summary: str = ""
    duration_s: float = 0.0


# Services to check for accessibility scoring
DEFAULT_SERVICES = ["hospital", "school", "pharmacy", "restaurant", "bank", "police"]


class SpatialReport:
    """Generate comprehensive spatial intelligence reports.

    Combines geocoding, elevation, OSM data, and distance computation
    to produce a complete location dossier.
    """

    def __init__(
        self,
        engine: Engine | None = None,
        ollama_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.engine = engine or Engine(tools=["geocoder", "terrain"])
        self._launcher = MCPServerLauncher()
        self._overpass = OverpassLoader()

        import os

        self._ollama_url = ollama_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self._model = model or os.getenv("GEOSPARK_OLLAMA_MODEL", "qwen2.5:7b")

    def analyze(
        self,
        location: str,
        radius_m: float = 2000,
        services: list[str] | None = None,
    ) -> LocationReport:
        """Generate a spatial intelligence report for a location.

        Args:
            location: Place name or address to analyze.
            radius_m: Search radius for nearby amenities (default 2km).
            services: Service types for accessibility scoring.
                Defaults to hospitals, schools, pharmacies, restaurants, banks, police.

        Returns:
            LocationReport with all findings.
        """
        start = time.time()
        report = LocationReport(query=location)
        check_services = services or DEFAULT_SERVICES

        # Step 1: Geocode
        geo = self._launcher.handle_tool_call("geocode", {
            "explanation": f"Geocoding {location}",
            "query": location,
        })
        if geo.get("status") != "success":
            report.summary = f"Could not geocode: {location}"
            return report

        features = geo.get("result", {}).get("features", [])
        if not features:
            report.summary = f"No results for: {location}"
            return report

        coords = features[0].get("geometry", {}).get("coordinates", [])
        report.coordinates = coords
        report.address = features[0].get("properties", {}).get("display_name", location)

        if len(coords) < 2:
            report.summary = "Invalid coordinates returned"
            return report

        lon, lat = coords[0], coords[1]
        center = {"type": "Point", "coordinates": [lon, lat]}

        # Step 2: Elevation
        elev = self._launcher.handle_tool_call("get_elevation", {
            "explanation": f"Elevation at {location}",
            "latitude": lat,
            "longitude": lon,
        })
        if elev.get("status") == "success" and elev.get("result"):
            report.elevation_m = elev["result"].get("elevation_m")

        # Step 2b: Weather (Tier 0 — always available, no key needed)
        report.weather = self._fetch_weather(lat, lon)

        # Step 2c: Air quality (Tier 1 — graceful if OPENAQ_API_KEY not set)
        report.air_quality = self._fetch_air_quality(lat, lon)

        # Step 3: Nearby amenities (all service types)
        delta = radius_m / 111320
        bbox = (lat - delta, lon - delta, lat + delta, lon + delta)
        all_nearby: list[NearbyItem] = []

        for svc in check_services:
            try:
                entities = self._overpass.load_amenities(bbox, svc)
                for ent in entities:
                    dist = SpatialReasoner.calculate_distance(center, ent.geometry)
                    if dist <= radius_m:
                        all_nearby.append(NearbyItem(
                            name=ent.name,
                            amenity_type=svc,
                            distance_m=round(dist),
                            coordinates=ent.geometry.get("coordinates", []),
                        ))
            except Exception:
                continue

        all_nearby.sort(key=lambda x: x.distance_m)
        report.nearby = all_nearby[:50]  # Cap at 50

        # Step 4: Accessibility scoring (nearest of each type)
        for svc in check_services:
            svc_items = [n for n in all_nearby if n.amenity_type == svc]
            if svc_items:
                nearest = svc_items[0]
                report.accessibility.append(AccessibilityScore(
                    service=svc,
                    nearest_name=nearest.name,
                    distance_m=nearest.distance_m,
                    available=True,
                ))
            else:
                report.accessibility.append(AccessibilityScore(
                    service=svc,
                    available=False,
                ))

        # Step 5: Generate narrative summary
        report.summary = self._generate_narrative(report)
        report.duration_s = round(time.time() - start, 1)
        return report

    def _fetch_weather(self, lat: float, lon: float) -> WeatherSnapshot | None:
        """Fetch current weather via the weather data channel."""
        import asyncio

        try:
            from geospark.data_channels.weather import WeatherChannel

            async def _run():
                ch = WeatherChannel()
                return await ch.search(lat=lat, lon=lon, filters={"forecast_days": 1})

            result = asyncio.run(_run())
            if result.errors or result.is_empty:
                return None

            current = next(
                (f for f in result.features if f.get("type") == "current_weather"), None
            )
            if not current:
                return None

            return WeatherSnapshot(
                temperature_c=current.get("temperature_c"),
                feels_like_c=current.get("feels_like_c"),
                humidity_pct=current.get("humidity_pct"),
                wind_speed_kmh=current.get("wind_speed_kmh"),
                precipitation_mm=current.get("precipitation_mm"),
                conditions=current.get("weather_description", ""),
            )
        except Exception:
            return None

    def _fetch_air_quality(self, lat: float, lon: float) -> AirQualitySnapshot | None:
        """Fetch nearest air quality station via the air quality data channel."""
        import asyncio

        try:
            from geospark.data_channels.air_quality import AirQualityChannel

            async def _run():
                ch = AirQualityChannel()
                return await ch.search(lat=lat, lon=lon, filters={"limit": 1})

            result = asyncio.run(_run())
            if result.errors or result.is_empty:
                return None

            station = result.features[0]
            measurements = station.get("measurements", {})
            pm25_val = measurements.get("pm25", {}).get("value")
            return AirQualitySnapshot(
                station_name=station.get("station_name", ""),
                distance_m=station.get("distance_m"),
                pm25=pm25_val,
                pm25_category=station.get("aqi_category", ""),
                no2=measurements.get("no2", {}).get("value"),
                o3=measurements.get("o3", {}).get("value"),
            )
        except Exception:
            return None

    def _generate_narrative(self, report: LocationReport) -> str:
        """Generate an LLM narrative from the report data."""
        import json

        import httpx

        amenity_counts = {}
        for n in report.nearby:
            amenity_counts[n.amenity_type] = amenity_counts.get(n.amenity_type, 0) + 1

        access_lines = []
        for a in report.accessibility:
            if a.available:
                access_lines.append(f"  {a.service}: {a.nearest_name} ({a.distance_m}m)")
            else:
                access_lines.append(f"  {a.service}: none within search radius")

        weather_line = ""
        if report.weather:
            w = report.weather
            weather_line = (
                f"Weather: {w.conditions}, {w.temperature_c}°C "
                f"(feels like {w.feels_like_c}°C), "
                f"humidity {w.humidity_pct}%, wind {w.wind_speed_kmh} km/h, "
                f"precipitation {w.precipitation_mm} mm\n"
            )

        air_line = ""
        if report.air_quality:
            aq = report.air_quality
            parts = []
            if aq.pm25 is not None:
                parts.append(f"PM2.5: {aq.pm25} ({aq.pm25_category})")
            if aq.no2 is not None:
                parts.append(f"NO2: {aq.no2}")
            if aq.o3 is not None:
                parts.append(f"O3: {aq.o3}")
            if parts:
                air_line = f"Air quality ({aq.station_name}, {aq.distance_m}m away): {', '.join(parts)}\n"

        data = (
            f"Location: {report.address}\n"
            f"Coordinates: {report.coordinates}\n"
            f"Elevation: {report.elevation_m}m\n"
            f"{weather_line}"
            f"{air_line}"
            f"Search radius: {report.query} (analyzed within the search area)\n"
            f"Total nearby amenities found: {len(report.nearby)}\n"
            f"By type: {json.dumps(amenity_counts)}\n"
            f"Accessibility (nearest of each service type):\n" + "\n".join(access_lines)
        )

        prompt = f"""Write a 3-5 sentence spatial intelligence summary for this location.
Include key facts about accessibility, nearby services, terrain, weather conditions, and air quality where available.
Be specific with numbers.

{data}

Summary:"""

        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception:
            # Fallback
            parts = [f"Location: {report.address}."]
            if report.elevation_m is not None:
                parts.append(f"Elevation: {report.elevation_m}m.")
            if report.weather:
                parts.append(
                    f"Weather: {report.weather.conditions}, "
                    f"{report.weather.temperature_c}°C."
                )
            if report.air_quality and report.air_quality.pm25 is not None:
                parts.append(
                    f"Air quality: PM2.5 {report.air_quality.pm25} "
                    f"({report.air_quality.pm25_category})."
                )
            parts.append(f"Found {len(report.nearby)} amenities within search radius.")
            accessible = [a for a in report.accessibility if a.available]
            if accessible:
                nearest = min(accessible, key=lambda a: a.distance_m)
                parts.append(
                    f"Nearest service: {nearest.service} "
                    f"({nearest.nearest_name}, {nearest.distance_m}m away)."
                )
            return " ".join(parts)
