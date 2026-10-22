"""MCP server for terrain analysis — elevation, slope, aspect."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.mcp_servers.base import BaseMCPServer, verification
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery


class TerrainServer(BaseMCPServer):
    """MCP server for terrain and elevation analysis."""

    server_name = "geospark-terrain"

    tools: ClassVar[list[dict[str, Any]]] = [
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
