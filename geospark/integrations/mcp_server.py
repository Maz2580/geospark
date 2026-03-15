"""
GeoSpark MCP (Model Context Protocol) Server.

Exposes GeoSpark as an MCP server so any MCP-compatible AI assistant
(Claude, etc.) can use spatial reasoning as a tool.

This is the key integration point -- GeoSpark becomes the "spatial brain"
that any LLM can call through MCP.

Usage:
    python -m geospark.integrations.mcp_server
"""

from __future__ import annotations

from typing import Any

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import (
    Point,
    SpatialFilter,
    SpatialOperation,
    SpatialQuery,
)

# Tool definitions in MCP format
# Pattern: "What it does. When to use it. What it returns. Do NOT use for X."
# (Based on analysis of Manus, Cursor, Claude Code system prompts)
MCP_TOOLS = [
    {
        "name": "spatial_query",
        "description": (
            "Execute a spatial operation on geographic features (buffer, distance, area, centroid, "
            "find nearby). Use when the user asks about spatial measurements, proximity searches, "
            "or geometric analysis around a point. Returns a GeoJSON FeatureCollection with "
            "computed results and metadata. "
            "Do NOT use for address lookups (use geocode instead). "
            "Do NOT use for checking if geometries overlap or contain each other "
            "(use check_spatial_relationship instead)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "One sentence explaining WHY you are calling this tool and how it helps answer the user's question.",
                },
                "operation": {
                    "type": "string",
                    "description": "The spatial operation to perform",
                    "enum": [op.value for op in SpatialOperation],
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude of the center point (decimal degrees, e.g., 48.8584 for Paris)",
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude of the center point (decimal degrees, e.g., 2.2945 for Paris)",
                },
                "radius_m": {
                    "type": "number",
                    "description": "Radius in meters (required for find_within and buffer operations)",
                },
                "category": {
                    "type": "string",
                    "description": "Feature category filter (e.g., 'hospital', 'school', 'restaurant')",
                },
            },
            "required": ["explanation", "operation"],
        },
    },
    {
        "name": "check_spatial_relationship",
        "description": (
            "Check the topological relationship between two geometries with ground-truth accuracy. "
            "Use when the user asks whether geometries contain, intersect, overlap, or touch each other. "
            "Returns a boolean result with 100% accuracy (LLMs guess wrong ~80% of the time). "
            "Do NOT use for distance calculations (use spatial_query with operation 'distance'). "
            "Do NOT use for address lookups (use geocode instead)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "One sentence explaining WHY you are checking this relationship.",
                },
                "geometry_a": {
                    "type": "object",
                    "description": (
                        "First geometry in GeoJSON format. Example Point: "
                        '{\"type\": \"Point\", \"coordinates\": [2.2945, 48.8584]}. '
                        "Example Polygon: "
                        '{\"type\": \"Polygon\", \"coordinates\": [[[lon1,lat1],[lon2,lat2],...,[lon1,lat1]]]}'
                    ),
                },
                "geometry_b": {
                    "type": "object",
                    "description": "Second geometry in GeoJSON format (same format as geometry_a)",
                },
                "relationship": {
                    "type": "string",
                    "enum": ["contains", "intersects", "within", "touches", "crosses", "overlaps", "disjoint"],
                    "description": "The topological relationship to check between geometry_a and geometry_b",
                },
            },
            "required": ["explanation", "geometry_a", "geometry_b", "relationship"],
        },
    },
    {
        "name": "geocode",
        "description": (
            "Convert a place name or address to geographic coordinates (longitude, latitude). "
            "Use when the user mentions a location by name and you need its coordinates for "
            "spatial operations. Returns a GeoJSON Point with the location name, country, and "
            "confidence score. "
            "Do NOT use if the user already provided coordinates. "
            "Do NOT use for elevation data (use get_elevation instead)."
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
                    "description": "Address or place name to geocode (e.g., 'Eiffel Tower, Paris' or '1600 Pennsylvania Ave, Washington DC')",
                },
            },
            "required": ["explanation", "query"],
        },
    },
    {
        "name": "get_elevation",
        "description": (
            "Get the elevation (height above sea level in meters) at a geographic coordinate. "
            "Use when the user asks about altitude, elevation, or terrain height at a location. "
            "Returns elevation in meters with the data source. "
            "Do NOT use for finding coordinates of a place (use geocode instead). "
            "Do NOT use for spatial relationship checks (use check_spatial_relationship instead)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "One sentence explaining WHY you need elevation data at this location.",
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude in decimal degrees (e.g., 27.9881 for Mt Everest)",
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude in decimal degrees (e.g., 86.9250 for Mt Everest)",
                },
            },
            "required": ["explanation", "latitude", "longitude"],
        },
    },
]


class GeoSparkMCPHandler:
    """
    Handles MCP tool calls by routing to the GeoSpark engine.

    This class can be integrated into any MCP server implementation.
    """

    def __init__(self, tools: list[str] | None = None):
        self.engine = Engine(tools=tools or ["geocoder", "terrain"])

    def get_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions."""
        return MCP_TOOLS

    def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Handle an MCP tool call and return a structured result.

        All results follow the pattern:
            {"status": "success"|"error", "tool": name, "result": {...}, "metadata": {...}}
        Error results include a "suggestion" to guide the model on recovery.
        """
        # Strip the explanation field (used for reasoning, not execution)
        arguments = {k: v for k, v in arguments.items() if k != "explanation"}

        handlers = {
            "spatial_query": self._handle_spatial_query,
            "check_spatial_relationship": self._handle_relationship_check,
            "geocode": self._handle_geocode,
            "get_elevation": self._handle_elevation,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "UNKNOWN_TOOL",
                    "message": f"Unknown tool: {tool_name}",
                    "suggestion": f"Available tools: {list(handlers.keys())}. Check the tool name and try again.",
                },
            }

        try:
            result = handler(arguments)
            return {"status": "success", "tool": tool_name, **result}
        except ValueError as e:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": str(e),
                    "suggestion": "Check the parameter values and try again with valid inputs.",
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "EXECUTION_ERROR",
                    "message": str(e),
                    "suggestion": "An unexpected error occurred. Try with different parameters or report to the user.",
                },
            }

    def _handle_spatial_query(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a generic spatial query."""
        geometry = None
        if "latitude" in args and "longitude" in args:
            geometry = Point.from_latlon(args["latitude"], args["longitude"])

        filters = None
        if "category" in args:
            filters = SpatialFilter(category=args["category"])

        query = SpatialQuery(
            operation=SpatialOperation(args["operation"]),
            geometry=geometry,
            radius_m=args.get("radius_m"),
            filters=filters,
        )

        result = self.engine.execute(query)
        return {
            "result": {
                "features": [f.model_dump() for f in result.features],
                "summary": result.spatial_context.summary,
                "total_features": result.spatial_context.total_features,
            },
            "metadata": {
                "crs": "EPSG:4326",
                "operation": args["operation"],
                "execution_time_ms": result.execution_time_ms,
            },
            "errors": result.errors or None,
        }

    def _handle_relationship_check(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a spatial relationship check -- GeoSpark's killer feature."""
        result = SpatialReasoner.check_relationship(
            args["geometry_a"],
            args["geometry_b"],
            args["relationship"],
        )
        return {
            "result": {
                "relationship": args["relationship"],
                "holds": result,
            },
            "metadata": {
                "crs": "EPSG:4326",
                "method": "ground_truth_topology",
                "note": "100% accurate spatial reasoning via Shapely/GEOS, not an LLM guess.",
            },
        }

    def _handle_geocode(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle geocoding."""
        query = SpatialQuery(
            operation=SpatialOperation.GEOCODE,
            metadata={"query": args["query"]},
        )
        result = self.engine.execute(query)
        if not result.features:
            return {
                "result": {"features": [], "summary": "No results found"},
                "metadata": {"source": "Nominatim", "query": args["query"]},
                "suggestion": "Try a more specific location name or check spelling.",
            }
        return {
            "result": {
                "features": [f.model_dump() for f in result.features],
                "summary": result.spatial_context.summary,
            },
            "metadata": {"source": "Nominatim", "crs": "EPSG:4326"},
        }

    def _handle_elevation(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle elevation query."""
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
            "suggestion": "Verify the coordinates are valid and try again. Elevation data may not be available for ocean areas.",
        }
