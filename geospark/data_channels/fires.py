"""
Active Fire data channel — NASA FIRMS (free, no API key for basic access).

Provides near-real-time active fire detections from MODIS and VIIRS
satellite instruments. Global coverage, updated every few hours.

Tier 0: Free CSV endpoint (no key for last 24h/48h data).
Source: https://firms.modaps.eosdis.nasa.gov/
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from geospark.data_channels.base import ChannelResult, ChannelStatus
from geospark.mcp_servers.launcher import MCPServerLauncher


class FiresChannel:
    """Active fire detections via NASA FIRMS."""

    name = "fires"
    description = "Near-real-time active fire detections from NASA MODIS/VIIRS (free API key)"
    tier = 1  # FIRMS API requires free MAP_KEY registration

    FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    def __init__(self) -> None:
        import os

        self._map_key = os.getenv("FIRMS_MAP_KEY", "")

    def check(self) -> ChannelStatus:
        """Check NASA FIRMS availability and configuration."""
        if not self._map_key:
            return ChannelStatus(
                name=self.name,
                status="unconfigured",
                message="Set FIRMS_MAP_KEY env var (free at https://firms.modaps.eosdis.nasa.gov/api/area/)",
                tier=self.tier,
            )
        try:
            resp = httpx.head(
                "https://firms.modaps.eosdis.nasa.gov/",
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code < 400:
                return ChannelStatus(
                    name=self.name, status="ok", message="NASA FIRMS reachable (key configured)", tier=self.tier
                )
            return ChannelStatus(
                name=self.name, status="warn", message=f"FIRMS returned {resp.status_code}", tier=self.tier
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
        """Search for active fire detections.

        Args:
            location: Place name (geocoded, then 1-degree bbox around it).
            bbox: Bounding box (min_lat, min_lon, max_lat, max_lon).
            lat/lon: Center point (1-degree bbox created around it).
            filters: Optional:
                - days: lookback days (1 or 2, default 1)
                - confidence: minimum confidence (default 50)
                - source: "modis" or "viirs" (default "modis")
        """
        filters = filters or {}
        days = min(filters.get("days", 1), 2)  # Free tier: max 2 days
        min_confidence = filters.get("confidence", 50)
        source = filters.get("source", "modis")

        # Resolve bbox
        if bbox:
            min_lat, min_lon, max_lat, max_lon = bbox
        elif lat is not None and lon is not None:
            min_lat, min_lon = lat - 0.5, lon - 0.5
            max_lat, max_lon = lat + 0.5, lon + 0.5
            location = location or f"({lat}, {lon})"
        elif location:
            # Check well-known regions first (natural features that don't geocode well)
            known = self._known_region(location)
            if known:
                min_lat, min_lon, max_lat, max_lon = known
            else:
                geo_lat, geo_lon, location_name = await self._geocode(location)
                if geo_lat is None:
                    return ChannelResult(
                        channel=self.name, query={"location": location},
                        errors=[f"Could not geocode: {location}. Try using lat/lon or bbox instead."],
                    )
                min_lat, min_lon = geo_lat - 0.5, geo_lon - 0.5
                max_lat, max_lon = geo_lat + 0.5, geo_lon + 0.5
                location = location_name
        else:
            return ChannelResult(channel=self.name, errors=["Provide location, lat/lon, or bbox"])

        if not self._map_key:
            return ChannelResult(
                channel=self.name,
                query={"location": location},
                errors=["FIRMS_MAP_KEY not set. Register free at https://firms.modaps.eosdis.nasa.gov/api/area/"],
            )

        # FIRMS area query: MAP_KEY/source/bbox/days
        area_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

        source_id = "MODIS_NRT" if source == "modis" else "VIIRS_SNPP_NRT"
        url = f"{self.FIRMS_AREA_URL}/csv/{self._map_key}/{source_id}/{area_str}/{days}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                if resp.status_code == 401:
                    # API key required for this area size, try smaller
                    return ChannelResult(
                        channel=self.name,
                        query={"location": location, "bbox": [min_lat, min_lon, max_lat, max_lon]},
                        errors=["Area too large for free tier. Use a smaller bbox or provide a FIRMS API key."],
                        metadata={"register_at": "https://firms.modaps.eosdis.nasa.gov/api/area/"},
                    )
                resp.raise_for_status()
                csv_text = resp.text
        except Exception as e:
            return ChannelResult(
                channel=self.name,
                query={"location": location, "bbox": [min_lat, min_lon, max_lat, max_lon]},
                errors=[f"FIRMS API error: {e}"],
            )

        # Parse CSV
        features = []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            for row in reader:
                try:
                    confidence = float(row.get("confidence", 0))
                except (ValueError, TypeError):
                    confidence = 0

                if confidence < min_confidence:
                    continue

                try:
                    fire_lat = float(row.get("latitude", 0))
                    fire_lon = float(row.get("longitude", 0))
                except (ValueError, TypeError):
                    continue

                features.append({
                    "type": "active_fire",
                    "coordinates": [fire_lon, fire_lat],
                    "brightness": row.get("brightness"),
                    "confidence": confidence,
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "satellite": row.get("satellite", source.upper()),
                    "frp": row.get("frp"),  # Fire Radiative Power
                    "daynight": row.get("daynight", ""),
                })
        except Exception:
            # CSV might be empty or malformed
            pass

        if not features:
            return ChannelResult(
                channel=self.name,
                query={"location": location, "bbox": [min_lat, min_lon, max_lat, max_lon], "days": days},
                metadata={
                    "source": "NASA FIRMS",
                    "note": f"No active fires detected in this area in the last {days} day(s)",
                },
                source="nasa-firms",
                total_results=0,
            )

        # Sort by confidence descending
        features.sort(key=lambda f: float(f.get("confidence", 0)), reverse=True)

        return ChannelResult(
            channel=self.name,
            query={"location": location, "bbox": [min_lat, min_lon, max_lat, max_lon], "days": days},
            features=features,
            metadata={
                "source": "NASA FIRMS (MODIS/VIIRS)",
                "api": "free CSV endpoint",
                "fires_detected": len(features),
                "period": f"last {days} day(s)",
                "min_confidence": min_confidence,
            },
            source="nasa-firms",
            total_results=len(features),
        )

    @staticmethod
    def _known_region(location: str) -> tuple[float, float, float, float] | None:
        """Return bbox for well-known regions that don't geocode well."""
        regions: dict[str, tuple[float, float, float, float]] = {
            "amazon": (-5.0, -65.0, 0.0, -55.0),
            "amazon rainforest": (-5.0, -65.0, 0.0, -55.0),
            "sahara": (20.0, -5.0, 30.0, 10.0),
            "sahel": (10.0, -10.0, 15.0, 10.0),
            "siberia": (55.0, 80.0, 65.0, 100.0),
            "borneo": (-2.0, 109.0, 2.0, 117.0),
            "california": (34.0, -122.0, 40.0, -117.0),
            "australia bushfire": (-38.0, 145.0, -30.0, 152.0),
            "congo": (-5.0, 15.0, 5.0, 30.0),
        }
        key = location.lower().strip()
        for name, bbox in regions.items():
            if name in key or key in name:
                return bbox
        return None

    async def _geocode(self, location: str) -> tuple[float | None, float | None, str]:
        """Geocode via GeoSpark's geocoder."""
        try:
            launcher = MCPServerLauncher()
            result = launcher.handle_tool_call("geocode", {
                "explanation": f"Geocoding {location} for fire data",
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
