"""MCP server for geocoding — address to coordinates and reverse."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.mcp_servers.base import BaseMCPServer
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery


class GeocodingServer(BaseMCPServer):
    """MCP server for geocoding operations.

    Converts addresses to coordinates and coordinates to addresses.
    """

    server_name = "geospark-geocoding"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "geocode",
            "description": (
                "Convert a place name or address to geographic coordinates. "
                "Use when the user mentions a location by name and you need its coordinates. "
                "Returns coordinates, display name, and confidence score. "
                "Do NOT use if coordinates are already provided."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you need to geocode this location.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Address or place name (e.g., 'Eiffel Tower, Paris').",
                    },
                },
                "required": ["explanation", "query"],
            },
        },
        {
            "name": "reverse_geocode",
            "description": (
                "Convert coordinates to an address or place name. "
                "Use when you have coordinates and need to know what location they represent. "
                "Returns the nearest address and place details."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you need the address for these coordinates.",
                    },
                    "latitude": {"type": "number", "description": "Latitude (decimal degrees)."},
                    "longitude": {"type": "number", "description": "Longitude (decimal degrees)."},
                },
                "required": ["explanation", "latitude", "longitude"],
            },
        },
    ]

    def __init__(self) -> None:
        self.engine = Engine(tools=["geocoder"])

    def _get_handlers(self) -> dict[str, Any]:
        return {
            "geocode": self._handle_geocode,
            "reverse_geocode": self._handle_reverse_geocode,
        }

    def _handle_geocode(self, args: dict[str, Any]) -> dict[str, Any]:
        query = SpatialQuery(
            operation=SpatialOperation.GEOCODE,
            metadata={"query": args["query"]},
        )
        result = self.engine.execute(query)
        if not result.features:
            return {
                "result": {"features": []},
                "metadata": {"source": "Nominatim"},
                "suggestion": "Try a more specific location name.",
            }
        return {
            "result": {
                "features": [f.model_dump() for f in result.features],
                "summary": result.spatial_context.summary,
            },
            "metadata": {"source": "Nominatim", "crs": "EPSG:4326"},
        }

    def _handle_reverse_geocode(self, args: dict[str, Any]) -> dict[str, Any]:
        query = SpatialQuery(
            operation=SpatialOperation.REVERSE_GEOCODE,
            geometry=Point.from_latlon(args["latitude"], args["longitude"]),
        )
        result = self.engine.execute(query)
        if not result.features:
            return {
                "result": {"address": None},
                "metadata": {"source": "Nominatim"},
                "suggestion": "Coordinates may be in an unmapped area.",
            }
        return {
            "result": {
                "features": [f.model_dump() for f in result.features],
                "summary": result.spatial_context.summary,
            },
            "metadata": {"source": "Nominatim", "crs": "EPSG:4326"},
        }
