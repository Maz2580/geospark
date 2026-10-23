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

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field

from geospark.agents.amenities import find_amenities
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.protocol.provenance import Provenance, engine_provenance, source_provenance
from geospark.runs import in_context
from geospark.utils.aio import run_sync

# The local model usually writes the summary in well under this; if it is
# busy, the report uses its plain summary rather than keep the caller waiting.
NARRATIVE_TIMEOUT_S = 30


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
    # False when the lookup failed, so "available" says nothing either way
    checked: bool = True


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
    # What could not be looked up, e.g. "nearby services", "weather"
    data_gaps: list[str] = Field(default_factory=list)
    # Things a reader should know about the data, e.g. which source answered for nearby places
    caveats: list[str] = Field(default_factory=list)
    # How many of each service were found within the radius (all of them, not only those listed)
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    radius_m: float = 0.0
    admin_area: str = ""
    summary: str = ""
    duration_s: float = 0.0
    provenance: list[Provenance] = Field(
        default_factory=list, description="Every data source this report is built on, with licence and attribution"
    )

    def to_geojson(self) -> dict[str, Any]:
        """The report as a GeoJSON FeatureCollection: the location plus each nearby amenity.

        Opens directly in QGIS: a point for the place (address, elevation, weather, air
        quality), and a point per amenity with its type and distance in metres.
        """
        from geospark.protocol.schema import (
            SpatialContext,
            SpatialFeature,
            SpatialResult,
            feature_collection,
        )

        features: list[SpatialFeature] = []
        if len(self.coordinates) >= 2:
            place: dict[str, Any] = {"kind": "location", "name": self.address or self.query,
                                     "elevation_m": self.elevation_m}
            if self.weather:
                place.update({f"weather_{k}": v for k, v in self.weather.model_dump().items()})
            if self.air_quality:
                place.update({f"air_{k}": v for k, v in self.air_quality.model_dump().items()})
            features.append(SpatialFeature(geometry={"type": "Point", "coordinates": self.coordinates[:2]},
                                           properties=place))
        for item in self.nearby:
            if len(item.coordinates) >= 2:
                features.append(SpatialFeature(
                    geometry={"type": "Point", "coordinates": item.coordinates[:2]},
                    properties={"kind": "amenity", "name": item.name, "amenity_type": item.amenity_type,
                                "distance_m": item.distance_m},
                ))
        result = SpatialResult(
            features=features,
            spatial_context=SpatialContext(summary=self.summary, total_features=len(features),
                                           units={"distance_m": "metre", "elevation_m": "metre"}),
            provenance=self.provenance,
            warnings=[f"No data: {gap}" for gap in self.data_gaps] + self.caveats,
        )
        return feature_collection(result, extra={"query": self.query, "radius_m": self.radius_m})


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
        report = LocationReport(query=location, radius_m=radius_m)
        check_services = services or DEFAULT_SERVICES
        used_sources: list[str] = ["openstreetmap-nominatim"]  # geocoding, below

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

        # Steps 2-3: elevation, weather, air quality and nearby amenities are
        # independent, so they are fetched at the same time. Amenities (the
        # public Overpass servers) usually take longest.
        with ThreadPoolExecutor(max_workers=4) as pool:
            elev_job = pool.submit(in_context(self._launcher.handle_tool_call), "get_elevation", {
                "explanation": f"Elevation at {location}",
                "latitude": lat,
                "longitude": lon,
            })
            weather_job = pool.submit(in_context(self._fetch_weather), lat, lon)
            air_job = pool.submit(in_context(self._fetch_air_quality), lat, lon)
            amenities_job = pool.submit(in_context(find_amenities), lat, lon, radius_m, check_services, self._overpass)

            elev = elev_job.result()
            if elev.get("status") == "success" and elev.get("result"):
                report.elevation_m = elev["result"].get("elevation_m")
                elevation_source = (elev.get("metadata") or {}).get("source")
                if elevation_source:
                    used_sources.append(elevation_source)
            # Weather is Tier 0 (no key); air quality is skipped without OPENAQ_API_KEY
            report.weather = weather_job.result()
            report.air_quality = air_job.result()

            # A failed lookup must not be reported as "no services nearby"
            amenities_checked = True
            amenity_provenance: list[Provenance] = []
            not_retrieved: set[str] = set()
            try:
                lookup = amenities_job.result()
                by_type = lookup.by_type
                amenity_provenance = lookup.provenance
                report.caveats.extend(lookup.warnings)
                not_retrieved = set(lookup.unavailable)
                report.data_gaps.extend(f"nearby {svc} (OpenStreetMap unavailable, no reliable fallback)"
                                        for svc in lookup.unavailable)
            except Exception:
                by_type = {}
                amenities_checked = False
                report.data_gaps.append("nearby services")

        all_nearby: list[NearbyItem] = []

        for svc, entities in by_type.items():
            for ent in entities:
                dist = SpatialReasoner.calculate_distance(center, ent.geometry)
                if dist <= radius_m:
                    all_nearby.append(NearbyItem(
                        name=ent.name,
                        amenity_type=svc,
                        distance_m=round(dist),
                        coordinates=ent.geometry.get("coordinates", []),
                    ))

        if report.weather is None:
            report.data_gaps.append("weather")
        if report.air_quality is None:
            report.data_gaps.append("air quality" if os.getenv("OPENAQ_API_KEY")
                                    else "air quality (this server has no OpenAQ API key)")

        all_nearby.sort(key=lambda x: x.distance_m)
        for item in all_nearby:
            report.counts_by_type[item.amenity_type] = report.counts_by_type.get(item.amenity_type, 0) + 1
        # The nearest few of each type, so one common type (restaurants) can't crowd out the rest
        per_type: dict[str, int] = {}
        listed: list[NearbyItem] = []
        for item in all_nearby:
            if per_type.get(item.amenity_type, 0) < 10:
                per_type[item.amenity_type] = per_type.get(item.amenity_type, 0) + 1
                listed.append(item)
        report.nearby = listed

        # Step 4: Accessibility scoring (nearest of each type)
        for svc in check_services:
            svc_items = [n for n in all_nearby if n.amenity_type == svc]
            if not amenities_checked or svc in not_retrieved:
                report.accessibility.append(AccessibilityScore(
                    service=svc,
                    available=False,
                    checked=False,
                ))
            elif svc_items:
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

        # Which providers this report actually relied on (cite them when sharing it)
        if report.weather is not None:
            used_sources.append("open-meteo")
        if report.air_quality is not None:
            used_sources.append("openaq")
        seen: set[str] = set()
        for source in used_sources:
            if source not in seen:
                seen.add(source)
                report.provenance.append(source_provenance(source))
        report.provenance.extend(p for p in amenity_provenance if p.source not in seen)
        report.provenance.append(engine_provenance("distance"))

        # Step 5: Generate narrative summary
        report.summary = self._generate_narrative(report)
        report.duration_s = round(time.time() - start, 1)
        return report

    def _fetch_weather(self, lat: float, lon: float) -> WeatherSnapshot | None:
        """Fetch current weather via the weather data channel."""

        try:
            from geospark.data_channels.weather import WeatherChannel

            async def _run():
                ch = WeatherChannel()
                return await ch.search(lat=lat, lon=lon, filters={"forecast_days": 1})

            result = run_sync(_run())
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

        try:
            from geospark.data_channels.air_quality import AirQualityChannel

            async def _run():
                ch = AirQualityChannel()
                return await ch.search(lat=lat, lon=lon, filters={"limit": 1})

            result = run_sync(_run())
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

        amenity_counts = dict(report.counts_by_type)

        access_lines = []
        for a in report.accessibility:
            if not a.checked:
                continue
            if a.available:
                access_lines.append(f"  {a.service}: {a.nearest_name} ({a.distance_m}m)")
            else:
                access_lines.append(f"  {a.service}: none within search radius")
        amenities_known = "nearby services" not in report.data_gaps

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
            f"Search radius: {round(report.radius_m)}m\n"
            + (
                f"Total nearby amenities found: {sum(amenity_counts.values())}\n"
                f"By type: {json.dumps(amenity_counts)}\n"
                f"Accessibility (nearest of each service type):\n" + "\n".join(access_lines)
                if amenities_known
                else ""
            )
        )
        # Missing data is stated in fixed wording after the model's text, so it
        # can never be phrased as "there are no hospitals here".
        gap_note = ""
        if report.data_gaps:
            gap_note = (
                " Not included because the data could not be retrieved: "
                + ", ".join(report.data_gaps)
                + "."
            )

        prompt = f"""Write a 3-5 sentence spatial intelligence summary for this location.
Use ONLY the facts listed below and be specific with their numbers.
Do not add typical values, climate norms, general knowledge about the place, or anything else that is not listed.
Do not mention any topic that has no line below (for example weather, air quality, or nearby services).

{data}

Summary:"""

        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": 400},  # bounded: a 3-5 sentence summary
                },
                # Past this the plain summary below is used instead of waiting
                timeout=NARRATIVE_TIMEOUT_S,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip() + gap_note
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
            if "nearby services" not in report.data_gaps:
                parts.append(f"Found {len(report.nearby)} amenities within search radius.")
            accessible = [a for a in report.accessibility if a.available]
            if accessible:
                nearest = min(accessible, key=lambda a: a.distance_m)
                parts.append(
                    f"Nearest service: {nearest.service} "
                    f"({nearest.nearest_name}, {nearest.distance_m}m away)."
                )
            return " ".join(parts) + gap_note
