"""MCP server for terrain analysis — elevation, slope, aspect."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.mcp_servers.base import BaseMCPServer, geocode_place, merge_lookups, verification
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery


class TerrainServer(BaseMCPServer):
    """MCP server for terrain and elevation analysis."""

    server_name = "geospark-terrain"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "get_elevation",
            "description": (
                "Get the elevation (height above sea level in meters) of a place or coordinate. "
                "Use when the user asks about altitude, elevation, or terrain height. "
                "For a NAMED place (a mountain, a town) pass place as its name; the server "
                "geocodes it, so never type coordinates for a named place. "
                "Returns elevation in meters. "
                "Do NOT use for address lookups or spatial relationships."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you need elevation data.",
                    },
                    "place": {
                        "type": "string",
                        "description": "The place by NAME, geocoded on the server. Preferred.",
                    },
                    "latitude": {"type": "number", "description": "Latitude, only for coordinates the user "
                                 "gave or a tool returned."},
                    "longitude": {"type": "number", "description": "Longitude, only for coordinates the user "
                                  "gave or a tool returned."},
                },
                "required": ["explanation"],
            },
        },
    ]

    def __init__(self) -> None:
        self.engine = Engine(tools=["terrain"])

    def _get_handlers(self) -> dict[str, Any]:
        return {"get_elevation": self._handle_elevation}

    def _handle_elevation(self, args: dict[str, Any]) -> dict[str, Any]:
        place, lookups = None, []
        name = args.get("place")
        if isinstance(name, str) and name.strip():
            point, place, found = geocode_place(name.strip())
            if point is None:
                return {"result": None, "errors": [place["error"]],
                        "suggestion": "Add the region or country to the place name."}
            lon, lat = point["coordinates"][:2]
            lookups.append(found)
        elif "latitude" in args and "longitude" in args:
            lat, lon = args["latitude"], args["longitude"]
        else:
            return {"result": None, "errors": ["Give place (a name) or latitude and longitude."]}
        query = SpatialQuery(operation=SpatialOperation.ELEVATION, geometry=Point.from_latlon(lat, lon))
        result = self.engine.execute(query)
        if result.features:
            merge_lookups(result, lookups)
            return {
                "result": {**result.features[0].properties, **({"place": place} if place else {})},
                # Report the dataset that actually answered (Copernicus GLO-30 first,
                # Open Elevation as fallback), with its attribution, not a hard-coded name.
                "metadata": {
                    **verification(result),
                    "crs": "EPSG:4326",
                    "source": result.sources[0] if result.sources else "unknown",
                    **(
                        {"attribution": result.features[0].properties["attribution"]}
                        if "attribution" in result.features[0].properties
                        else {}
                    ),
                },
            }
        return {
            "result": None,
            "errors": result.errors or ["No elevation data available"],
            "suggestion": "Verify coordinates are on land.",
        }
