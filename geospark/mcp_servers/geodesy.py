"""MCP server for official coordinate and height transformations (see geospark.geodesy)."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark import geodesy
from geospark.mcp_servers.base import BaseMCPServer

_CRS = {"type": "string", "description": "A CRS as 'EPSG:code', e.g. EPSG:28355 (GDA94 / MGA zone 55), "
                                         "EPSG:7855 (GDA2020 / MGA zone 55), EPSG:4326 (WGS 84 lat/lon)."}


class GeodesyServer(BaseMCPServer):
    """Datum, projection, plate-motion and height conversions with official grids."""

    server_name = "geospark-geodesy"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "transform_coordinates",
            "description": (
                "Convert coordinates between coordinate reference systems exactly as the official "
                "transformation does (e.g. GDA94 to GDA2020, MGA zones, British National Grid via OSTN15, "
                "NAD27 to NAD83 via NADCON, ITRF2014 at an epoch to GDA2020). Uses national grids, never an "
                "approximation, and returns the method and its stated accuracy. Use whenever coordinates change "
                "datum, projection or zone. Geographic coordinates are "
                "[longitude, latitude]; projected ones [easting, northing]. "
                "Do NOT use for height datums (use convert_height) or distances."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "source_crs": _CRS,
                    "target_crs": _CRS,
                    "coordinates": {
                        "type": "array", "items": {"type": "array", "items": {"type": "number"}},
                        "description": "Points as [x, y] or [x, y, z]: [lon, lat] or [easting, northing].",
                    },
                    "epoch": {"type": "number", "description": "Decimal year of the coordinates, for ITRF/ATRF "
                                                               "frames (e.g. 2026.8). Omit for static datums."},
                },
                "required": ["explanation", "source_crs", "target_crs", "coordinates"],
            },
        },
        {
            "name": "convert_height",
            "description": (
                "Convert a height between the ellipsoid (what GNSS and drones measure) and a national height "
                "datum using the official geoid model: AHD (AUSGeoid2020), ODN (OSGM15), NZVD2016 "
                "(NZGeoid2016), NAVD88 (GEOID18), or the global EGM2008. Returns the height, the geoid "
                "separation, and the model's stated accuracy. Use for any GNSS, drone or design-level height. "
                "Do NOT estimate a geoid separation yourself. "
                "Do NOT use for horizontal coordinates (use transform_coordinates)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "One sentence explaining WHY."},
                    "latitude": {"type": "number", "description": "Latitude in degrees."},
                    "longitude": {"type": "number", "description": "Longitude in degrees."},
                    "height_m": {"type": "number", "description": "The height to convert, in metres."},
                    "from_reference": {"type": "string", "description": "'ellipsoidal' or AHD, ODN, NZVD2016, NAVD88, EGM2008."},
                    "to_reference": {"type": "string", "description": "'ellipsoidal' or AHD, ODN, NZVD2016, NAVD88, EGM2008."},
                },
                "required": ["explanation", "latitude", "longitude", "height_m", "from_reference", "to_reference"],
            },
        },
    ]

    def _get_handlers(self) -> dict[str, Any]:
        return {"transform_coordinates": self._handle_transform, "convert_height": self._handle_height}

    def _handle_transform(self, args: dict[str, Any]) -> dict[str, Any]:
        done = geodesy.transform(args["source_crs"], args["target_crs"], args["coordinates"], args.get("epoch"))
        out = done.as_dict()
        return {"result": {k: v for k, v in out.items() if k not in ("provenance", "warnings")},
                "metadata": {"status": "ok", "provenance": out["provenance"], "warnings": out["warnings"],
                             "units": {"coordinates": "degrees or metres, as the target CRS defines"}}}

    def _handle_height(self, args: dict[str, Any]) -> dict[str, Any]:
        out = geodesy.convert_height(float(args["latitude"]), float(args["longitude"]), float(args["height_m"]),
                                     str(args["from_reference"]), str(args["to_reference"]))
        return {"result": {k: v for k, v in out.items() if k not in ("provenance", "warnings")},
                "metadata": {"status": "ok", "provenance": out["provenance"], "warnings": out["warnings"],
                             "units": {"height_m": "metre", "separation_m": "metre"}}}
