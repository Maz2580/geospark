"""MCP server for the Sun and what terrain hides (see geospark.sun and geospark.visibility)."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark import sun, visibility
from geospark.mcp_servers.base import BaseMCPServer, geocode_place

_PLACE = {"type": "string", "description": "The place by NAME, geocoded on the server. Preferred."}
_LAT = {"type": "number", "description": "Latitude, only for coordinates the user gave or a tool returned."}
_LON = {"type": "number", "description": "Longitude, only for coordinates the user gave or a tool returned."}
_TZ = {"type": "string", "description": "IANA time zone of the place, e.g. 'Australia/Melbourne'."}


def _where(args: dict[str, Any], prefix: str = "") -> tuple[float, float, dict[str, Any] | None]:
    """(lat, lon, place) from a place name or coordinates in args; a name's caveats ride on the place."""
    name = args.get(f"place{prefix}")
    if isinstance(name, str) and name.strip():
        point, place, found = geocode_place(name.strip())
        if point is None:
            raise ValueError(place["error"] + " Add the region or country to the place name.")
        lon, lat = point["coordinates"][:2]
        return float(lat), float(lon), {**place, "warnings": list(getattr(found, "warnings", []) or [])}
    lat, lon = args.get(f"latitude{prefix}"), args.get(f"longitude{prefix}")
    if lat is None or lon is None:
        raise ValueError(f"Give place{prefix} (a name) or latitude{prefix} and longitude{prefix}.")
    return float(lat), float(lon), None


def _wrap(out: dict[str, Any], units: dict[str, str], places: list[dict[str, Any] | None]) -> dict[str, Any]:
    result = {k: v for k, v in out.items() if k not in ("provenance", "warnings")}
    named = [p for p in places if p]
    caveats = [w for p in named for w in p.pop("warnings", [])]
    if named:
        result["places"] = named
    return {"result": result, "metadata": {"status": "ok", "provenance": out["provenance"],
                                           "warnings": caveats + out["warnings"], "units": units}}


class SunTerrainServer(BaseMCPServer):
    """Sun position, sunrise and shadows; terrain horizons and lines of sight on the Copernicus DEM."""

    server_name = "geospark-sun-terrain"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "sun_position",
            "description": (
                "The Sun's elevation and azimuth (degrees from true north) at a place and time, and the length "
                "and direction of the shadow of a vertical object (pass object_height_m). Use for sun angle, "
                "shadow length or which way a shadow falls. Do NOT estimate sun angles yourself. "
                "Do NOT use for sunrise or sunset times (use sun_times)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place": _PLACE, "latitude": _LAT, "longitude": _LON,
                    "time": {"type": "string", "description": "ISO 8601 local time, e.g. '2026-06-21T12:00:00'; "
                                                              "with tz, or with a UTC offset (+10:00)."},
                    "tz": _TZ,
                    "object_height_m": {"type": "number", "description": "Height of a vertical object, for its shadow."},
                },
                "required": ["explanation", "time"],
            },
        },
        {
            "name": "sun_times",
            "description": (
                "Sunrise, solar noon, sunset and day length at a place on a date (flat horizon). With "
                "terrain=true, also the hours of direct sun once surrounding hills are counted (slower). Use for "
                "daylight, day length, or how much sun a site gets. "
                "Do NOT use for the sun's angle at a time (use sun_position)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place": _PLACE, "latitude": _LAT, "longitude": _LON,
                    "date": {"type": "string", "description": "Local date, YYYY-MM-DD."},
                    "tz": _TZ,
                    "terrain": {"type": "boolean", "description": "Count hours of sun above the terrain horizon."},
                },
                "required": ["explanation", "date"],
            },
        },
        {
            "name": "terrain_horizon",
            "description": (
                "The skyline that terrain makes around a place: the horizon's elevation angle in each direction "
                "and how far away the blocking terrain is (30 m DEM, curvature and refraction). Use for solar "
                "panel shading, sunlight in a valley, or how high the hills rise around a site. "
                "Do NOT use for whether two specific places see each other (use line_of_sight)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place": _PLACE, "latitude": _LAT, "longitude": _LON,
                    "observer_height_m": {"type": "number", "description": "Eye or sensor height above ground (default 1.5)."},
                    "step_deg": {"type": "number", "description": "Azimuth spacing in degrees, dividing 360 (default 5)."},
                },
                "required": ["explanation"],
            },
        },
        {
            "name": "line_of_sight",
            "description": (
                "Whether place A can see place B over the terrain (30 m DEM, curvature and refraction): visible "
                "or blocked, the minimum clearance and where it is. With frequency_mhz, the first Fresnel zone "
                "clearance of a radio link. Use for radio links, visibility of a tower or lookout, or "
                "intervisibility in planning. Give heights above ground for masts or buildings. "
                "Do NOT use for distances (use calculate_distance)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "place_a": _PLACE, "latitude_a": _LAT, "longitude_a": _LON,
                    "place_b": _PLACE, "latitude_b": _LAT, "longitude_b": _LON,
                    "height_a_m": {"type": "number", "description": "Height above ground at A (default 1.5)."},
                    "height_b_m": {"type": "number", "description": "Height above ground at B (default 1.5)."},
                    "frequency_mhz": {"type": "number", "description": "Radio frequency, for Fresnel clearance."},
                },
                "required": ["explanation"],
            },
        },
    ]

    def _get_handlers(self) -> dict[str, Any]:
        return {"sun_position": self._handle_position, "sun_times": self._handle_times,
                "terrain_horizon": self._handle_horizon, "line_of_sight": self._handle_los}

    def _handle_position(self, args: dict[str, Any]) -> dict[str, Any]:
        lat, lon, place = _where(args)
        height = args.get("object_height_m")
        out = (sun.shadow(lat, lon, args["time"], float(height), args.get("tz")) if height
               else sun.sun_position(lat, lon, args["time"], args.get("tz")))
        return _wrap(out, {"elevation_deg": "degree", "azimuth_deg": "degree", "shadow_length_m": "metre"}, [place])

    def _handle_times(self, args: dict[str, Any]) -> dict[str, Any]:
        lat, lon, place = _where(args)
        out = sun.sun_times(lat, lon, args["date"], args.get("tz"))
        if args.get("terrain"):
            lit = sun.sunlight_hours(lat, lon, args["date"], args.get("tz"))
            out.update({k: lit[k] for k in ("terrain_hours", "first_direct_sun", "last_direct_sun")})
            out["provenance"] += lit["provenance"][1:]
            out["warnings"] += lit["warnings"]
        return _wrap(out, {"day_length_h": "hour", "terrain_hours": "hour"}, [place])

    def _handle_horizon(self, args: dict[str, Any]) -> dict[str, Any]:
        lat, lon, place = _where(args)
        out = visibility.horizon(lat, lon, float(args.get("observer_height_m", 1.5)), step_deg=float(args.get("step_deg", 5)))
        return _wrap(out, {"horizon_elevation_deg": "degree", "obstruction_distance_m": "metre"}, [place])

    def _handle_los(self, args: dict[str, Any]) -> dict[str, Any]:
        lat_a, lon_a, place_a = _where(args, "_a")
        lat_b, lon_b, place_b = _where(args, "_b")
        freq = args.get("frequency_mhz")
        out = visibility.line_of_sight(lat_a, lon_a, lat_b, lon_b, float(args.get("height_a_m", 1.5)),
                                       float(args.get("height_b_m", 1.5)), float(freq) if freq else None)
        return _wrap(out, {"distance_m": "metre", "min_clearance_m": "metre"}, [place_a, place_b])
