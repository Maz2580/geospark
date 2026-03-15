"""MCP server for spatial reasoning — topology, distance, containment."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.mcp_servers.base import BaseMCPServer
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery


class SpatialReasoningServer(BaseMCPServer):
    """MCP server for ground-truth spatial reasoning.

    Provides topology checks, distance calculations, and geometric
    operations (buffer, centroid, area, convex hull).
    """

    server_name = "geospark-spatial-reasoning"

    tools: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "check_spatial_relationship",
            "description": (
                "Check the topological relationship between two geometries with "
                "ground-truth accuracy (100%). Use when the user asks whether "
                "geometries contain, intersect, overlap, or touch each other. "
                "Do NOT use for distance calculations or address lookups."
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
                        "description": "First geometry in GeoJSON format.",
                    },
                    "geometry_b": {
                        "type": "object",
                        "description": "Second geometry in GeoJSON format.",
                    },
                    "relationship": {
                        "type": "string",
                        "enum": [
                            "contains", "intersects", "within", "touches",
                            "crosses", "overlaps", "disjoint",
                        ],
                        "description": "The topological relationship to check.",
                    },
                },
                "required": ["explanation", "geometry_a", "geometry_b", "relationship"],
            },
        },
        {
            "name": "calculate_distance",
            "description": (
                "Calculate the geodesic distance between two points in meters. "
                "Use when the user asks how far apart two locations are. "
                "Returns exact distance on the WGS84 ellipsoid. "
                "Do NOT use for topology checks (use check_spatial_relationship)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you need this distance.",
                    },
                    "point_a": {
                        "type": "object",
                        "description": 'First point as GeoJSON: {"type": "Point", "coordinates": [lon, lat]}',
                    },
                    "point_b": {
                        "type": "object",
                        "description": 'Second point as GeoJSON: {"type": "Point", "coordinates": [lon, lat]}',
                    },
                },
                "required": ["explanation", "point_a", "point_b"],
            },
        },
        {
            "name": "spatial_operation",
            "description": (
                "Perform a spatial operation (buffer, centroid, area, convex hull). "
                "Use for geometric computations on a point or polygon. "
                "Returns the resulting geometry as GeoJSON. "
                "Do NOT use for topology checks or distance calculations."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you need this operation.",
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["buffer", "centroid", "area", "convex_hull"],
                        "description": "The spatial operation to perform.",
                    },
                    "latitude": {"type": "number", "description": "Latitude (decimal degrees)."},
                    "longitude": {"type": "number", "description": "Longitude (decimal degrees)."},
                    "radius_m": {"type": "number", "description": "Radius in meters (for buffer)."},
                },
                "required": ["explanation", "operation"],
            },
        },
    ]

    def __init__(self) -> None:
        self.engine = Engine()

    def _get_handlers(self) -> dict[str, Any]:
        return {
            "check_spatial_relationship": self._handle_relationship,
            "calculate_distance": self._handle_distance,
            "spatial_operation": self._handle_operation,
        }

    def _handle_relationship(self, args: dict[str, Any]) -> dict[str, Any]:
        result = SpatialReasoner.check_relationship(
            args["geometry_a"], args["geometry_b"], args["relationship"]
        )
        return {
            "result": {"relationship": args["relationship"], "holds": result},
            "metadata": {"method": "ground_truth_topology", "crs": "EPSG:4326"},
        }

    def _handle_distance(self, args: dict[str, Any]) -> dict[str, Any]:
        distance = SpatialReasoner.calculate_distance(args["point_a"], args["point_b"])
        return {
            "result": {"distance_m": distance, "distance_km": distance / 1000},
            "metadata": {"method": "geodesic_wgs84", "crs": "EPSG:4326"},
        }

    def _handle_operation(self, args: dict[str, Any]) -> dict[str, Any]:
        geometry = None
        if "latitude" in args and "longitude" in args:
            geometry = Point.from_latlon(args["latitude"], args["longitude"])
        query = SpatialQuery(
            operation=SpatialOperation(args["operation"]),
            geometry=geometry,
            radius_m=args.get("radius_m"),
        )
        result = self.engine.execute(query)
        return {
            "result": {
                "features": [f.model_dump() for f in result.features],
                "summary": result.spatial_context.summary,
            },
            "metadata": {"crs": "EPSG:4326", "operation": args["operation"]},
        }
