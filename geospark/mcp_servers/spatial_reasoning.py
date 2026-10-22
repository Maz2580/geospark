"""MCP server for spatial reasoning — topology, distance, containment."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.mcp_servers.base import BaseMCPServer, verification
from geospark.protocol.provenance import enrich
from geospark.protocol.schema import (
    Point,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)


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
                "Calculate the geodesic distance in meters between two places or points. "
                "For NAMED places, pass place_a and place_b as names (e.g. 'Adelaide Oval'); "
                "the server geocodes them, so never type coordinates for a named place. "
                "Use point_a/point_b only for coordinates the user gave you or a tool returned. "
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
                    "place_a": {
                        "type": "string",
                        "description": "First place by NAME, geocoded on the server. Preferred.",
                    },
                    "place_b": {
                        "type": "string",
                        "description": "Second place by NAME, geocoded on the server. Preferred.",
                    },
                    "point_a": {
                        "type": "object",
                        "description": 'First point as GeoJSON {"type": "Point", "coordinates": [lon, lat]}; '
                                       "only for coordinates the user gave or a tool returned.",
                    },
                    "point_b": {
                        "type": "object",
                        "description": 'Second point as GeoJSON {"type": "Point", "coordinates": [lon, lat]}; '
                                       "only for coordinates the user gave or a tool returned.",
                    },
                },
                "required": ["explanation"],
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
        self._geocoder: Engine | None = None  # created on first use of a place name

    def _get_handlers(self) -> dict[str, Any]:
        return {
            "check_spatial_relationship": self._handle_relationship,
            "calculate_distance": self._handle_distance,
            "spatial_operation": self._handle_operation,
        }

    def _handle_relationship(self, args: dict[str, Any]) -> dict[str, Any]:
        holds = SpatialReasoner.check_relationship(
            args["geometry_a"], args["geometry_b"], args["relationship"]
        )
        checked = enrich(SpatialResult(), args["relationship"], [args["geometry_a"], args["geometry_b"]])
        return {
            "result": {"relationship": args["relationship"], "holds": holds},
            "metadata": {"method": "ground_truth_topology", "crs": "EPSG:4326", **verification(checked)},
        }

    def _geocode(self, name: str) -> SpatialResult:
        if self._geocoder is None:
            self._geocoder = Engine(tools=["geocoder"])
        return self._geocoder.execute(SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": name}))

    def _handle_distance(self, args: dict[str, Any]) -> dict[str, Any]:
        """Distance between two places. Named places are geocoded here, so the model never has to
        supply (and possibly invent) coordinates for them."""
        points: dict[str, dict[str, Any]] = {}
        places: list[dict[str, Any]] = []
        lookups: list[SpatialResult] = []
        for side in ("a", "b"):
            name, point = args.get(f"place_{side}"), args.get(f"point_{side}")
            if isinstance(name, str) and name.strip():
                found = self._geocode(name.strip())
                if not found.features:
                    reason = found.errors[0] if found.errors else f"No place called '{name}' was found."
                    return {"result": None, "errors": [reason],
                            "suggestion": "Add the city or country to the place name, or call geocode first."}
                best = found.features[0]
                points[side] = best.geometry if isinstance(best.geometry, dict) else best.geometry.model_dump()
                places.append({"query": name, "display_name": best.properties.get("display_name"),
                               "coordinates": points[side]["coordinates"]})
                lookups.append(found)
            elif isinstance(point, dict):
                points[side] = point
            else:
                return {"result": None, "errors": [f"Give place_{side} (a name) or point_{side} (GeoJSON)."],
                        "suggestion": "For named places pass place_a and place_b; the server geocodes them."}
        distance = SpatialReasoner.calculate_distance(points["a"], points["b"])
        values = {"distance_m": distance, "distance_km": distance / 1000}
        checked = enrich(
            SpatialResult(features=[SpatialFeature(geometry=points["a"], properties=values)]), "distance"
        )
        for found in lookups:  # where the places came from, and any ambiguity, travel with the distance
            checked.provenance = [*found.provenance, *checked.provenance]
            checked.warnings.extend(w for w in found.warnings if w not in checked.warnings)
        result: dict[str, Any] = dict(values)
        if places:
            result["places"] = places
        return {
            "result": result,
            "metadata": {"method": "geodesic_wgs84", "crs": "EPSG:4326", **verification(checked)},
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
            "metadata": {"crs": "EPSG:4326", "operation": args["operation"], **verification(result)},
        }
