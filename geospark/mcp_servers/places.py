"""MCP server for what is around a place: nearby amenities and the weather.

Without these, a model asked "how many hospitals are within 1 km of Federation Square?" had no
tool that could answer, and answered about a buffer's area instead; asked about the weather, it
said it couldn't look it up.
"""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.mcp_servers.base import BaseMCPServer, geocode_place, merge_lookups, verification
from geospark.protocol.schema import SpatialResult

MAX_RADIUS_M = 5000
NEAREST_PER_TYPE = 10

_PLACE = {"type": "string", "description": "The place by NAME, geocoded on the server. Preferred."}
_LAT = {"type": "number", "description": "Latitude, only for coordinates the user gave or a tool returned."}
_LON = {"type": "number", "description": "Longitude, only for coordinates the user gave or a tool returned."}


class PlacesServer(BaseMCPServer):
    """Nearby amenities (OpenStreetMap, Overture Maps as fallback) and weather (Open-Meteo)."""

    server_name = "geospark-places"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "find_nearby_places",
            "description": (
                "Find and count amenities of given types near a place, from OpenStreetMap: "
                "hospital, school, pharmacy, cafe, restaurant, supermarket, bank, library, police, "
                "park, bus_stop and other OpenStreetMap amenity values. Use for 'how many X within "
                "N km of Y', 'nearest X to Y', 'X near Y'. Returns counts and the nearest of each type "
                "with distances. For a NAMED place pass place as its name. "
                "Do NOT use for distances between two named places (use calculate_distance)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place": _PLACE,
                    "latitude": _LAT,
                    "longitude": _LON,
                    "types": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Amenity types, singular, e.g. ['hospital'] or ['school', 'pharmacy'].",
                    },
                    "radius_m": {"type": "number", "description": f"Search radius in metres (default 1000, "
                                                                  f"at most {MAX_RADIUS_M})."},
                },
                "required": ["explanation", "types"],
            },
        },
        {
            "name": "get_weather",
            "description": (
                "Current weather and a daily forecast for a place (Open-Meteo). Use for temperature, "
                "rain, wind or forecast questions. For a NAMED place pass place as its name. "
                "Do NOT use for elevation or air quality."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place": _PLACE,
                    "latitude": _LAT,
                    "longitude": _LON,
                    "forecast_days": {"type": "integer", "description": "Days of forecast, 1-7 (default 3)."},
                },
                "required": ["explanation"],
            },
        },
    ]

    def _get_handlers(self) -> dict[str, Any]:
        return {"find_nearby_places": self._handle_nearby, "get_weather": self._handle_weather}

    @staticmethod
    def _locate(args: dict[str, Any]) -> tuple[float, float, dict[str, Any] | None, list[SpatialResult], str | None]:
        """(lat, lon, the place matched, lookups, error)."""
        name = args.get("place")
        if isinstance(name, str) and name.strip():
            point, place, found = geocode_place(name.strip())
            if point is None:
                return 0.0, 0.0, None, [], place["error"]
            lon, lat = point["coordinates"][:2]
            return lat, lon, place, [found], None
        lat, lon = args.get("latitude"), args.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon), None, [], None
        return 0.0, 0.0, None, [], "Give place (a name) or latitude and longitude."

    def _handle_nearby(self, args: dict[str, Any]) -> dict[str, Any]:
        from geospark.agents import amenities

        raw = args.get("types") or []
        types = [raw] if isinstance(raw, str) else [str(t) for t in raw]
        types = list(dict.fromkeys(_singular(t) for t in types if str(t).strip()))
        if not types:
            return {"result": None, "errors": ["Give at least one amenity type, e.g. types=['hospital']."]}
        radius = float(args.get("radius_m") or 1000)
        if not 0 < radius <= MAX_RADIUS_M:
            return {"result": None, "errors": [f"radius_m must be between 1 and {MAX_RADIUS_M} metres."]}
        lat, lon, place, lookups, error = self._locate(args)
        if error:
            return {"result": None, "errors": [error]}
        try:
            lookup = amenities.find_amenities(lat, lon, radius, types)
        except amenities.AmenityLookupError as e:
            return {"result": None, "errors": [str(e)]}
        center = {"type": "Point", "coordinates": [lon, lat]}
        counts: dict[str, int] = {}
        nearest: dict[str, list[dict[str, Any]]] = {}
        for kind, entities in lookup.by_type.items():
            found: list[dict[str, Any]] = []
            for ent in entities:
                distance = SpatialReasoner.calculate_distance(center, ent.geometry)
                if distance <= lookup.radius_m:
                    found.append({"name": ent.name, "distance_m": round(distance),
                                  "coordinates": ent.geometry.get("coordinates")})
            found.sort(key=lambda x: float(x["distance_m"]))
            counts[kind] = len(found)
            nearest[kind] = found[:NEAREST_PER_TYPE]
        checked = SpatialResult(provenance=list(lookup.provenance), warnings=list(lookup.warnings))
        if lookup.unavailable:
            checked.warnings.append(f"Not retrieved (unknown, not zero): {', '.join(lookup.unavailable)}.")
        merge_lookups(checked, lookups)
        result: dict[str, Any] = {"radius_m": lookup.radius_m, "counts": counts, "nearest": nearest,
                                  "source": lookup.source, "not_retrieved": lookup.unavailable}
        if place:
            result["place"] = place
        return {"result": result, "metadata": {"crs": "EPSG:4326", **verification(checked)}}

    def _handle_weather(self, args: dict[str, Any]) -> dict[str, Any]:
        from geospark.data_channels.weather import WeatherChannel
        from geospark.utils.aio import run_sync

        lat, lon, place, lookups, error = self._locate(args)
        if error:
            return {"result": None, "errors": [error]}
        days = min(max(int(args.get("forecast_days") or 3), 1), 7)
        data = run_sync(WeatherChannel().search(lat=lat, lon=lon, filters={"forecast_days": days}))
        if data.errors and not data.features:
            return {"result": None, "errors": [f"Weather unavailable: {data.errors[0]}"]}
        checked = SpatialResult(provenance=list(data.provenance), warnings=list(data.errors))
        merge_lookups(checked, lookups)
        result: dict[str, Any] = {
            "current": next((f for f in data.features if f.get("type") == "current_weather"), None),
            "forecast": [f for f in data.features if f.get("type") == "daily_forecast"],
        }
        if place:
            result["place"] = place
        return {"result": result, "metadata": {"crs": "EPSG:4326", **verification(checked)}}


# Everyday words for OpenStreetMap values ("gym" is leisure=fitness_centre, "doctor" amenity=doctors)
_SYNONYMS = {
    "gym": "fitness_centre", "doctor": "doctors", "gp": "doctors", "coffee": "cafe", "coffee_shop": "cafe",
    "chemist": "pharmacy", "drugstore": "pharmacy", "grocery": "supermarket", "petrol_station": "fuel",
    "gas_station": "fuel", "train_station": "station", "police_station": "police", "post_office": "post_office",
}


def _singular(word: str) -> str:
    """'Hospitals' -> 'hospital', 'pharmacies' -> 'pharmacy', 'gyms' -> 'fitness_centre'."""
    w = str(word).strip().lower().replace(" ", "_").replace("-", "_")
    if w in _SYNONYMS or w == "doctors":
        return _SYNONYMS.get(w, w)
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith(("ches", "shes", "sses")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    return _SYNONYMS.get(w, w)
