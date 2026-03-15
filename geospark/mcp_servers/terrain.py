"""MCP server for terrain analysis — elevation, slope, aspect."""
from __future__ import annotations

from typing import Any

from geospark.engine.core import Engine
from geospark.mcp_servers.base import BaseMCPServer
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery


class TerrainServer(BaseMCPServer):
    """MCP server for terrain and elevation analysis."""

    server_name = "geospark-terrain"

    tools = [
        {
            "name": "get_elevation",
            "description": (
                "Get the elevation (height above sea level in meters) at a coordinate. "
                "Use when the user asks about altitude, elevation, or terrain height. "
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
                    "latitude": {"type": "number", "description": "Latitude (decimal degrees)."},
                    "longitude": {"type": "number", "description": "Longitude (decimal degrees)."},
                },
                "required": ["explanation", "latitude", "longitude"],
            },
        },
    ]

    def __init__(self) -> None:
        self.engine = Engine(tools=["terrain"])

    def _get_handlers(self) -> dict[str, Any]:
        return {"get_elevation": self._handle_elevation}

    def _handle_elevation(self, args: dict[str, Any]) -> dict[str, Any]:
        query = SpatialQuery(
            operation=SpatialOperation.ELEVATION,
            geometry=Point.from_latlon(args["latitude"], args["longitude"]),
        )
        result = self.engine.execute(query)
        if result.features:
            return {
                "result": result.features[0].properties,
                "metadata": {"crs": "EPSG:4326", "source": "open-elevation"},
            }
        return {
            "result": None,
            "errors": result.errors or ["No elevation data available"],
            "suggestion": "Verify coordinates are on land.",
        }
