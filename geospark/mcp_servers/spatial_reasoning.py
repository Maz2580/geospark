"""MCP server for spatial reasoning — topology, distance, containment."""
from __future__ import annotations

from typing import Any, ClassVar

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.mcp_servers.base import BaseMCPServer, geocode_place, merge_lookups, verification
from geospark.protocol.provenance import enrich, source_provenance
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
                "Check the topological relationship between two places or geometries exactly. "
                "Use when the user asks whether something is in, inside, contains, intersects, "
                "overlaps or touches something else. For NAMED places pass place_a and place_b as "
                "names: the server uses the outer place's boundary. 'Is A in B?' is place_a=A, "
                "place_b=B, relationship='within'. "
                "Do NOT use for distance calculations or address lookups."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "One sentence explaining WHY you are checking this relationship.",
                    },
                    "place_a": {
                        "type": "string",
                        "description": "First place by NAME, resolved on the server. Preferred.",
                    },
                    "place_b": {
                        "type": "string",
                        "description": "Second place by NAME, resolved on the server. Preferred.",
                    },
                    "geometry_a": {
                        "type": "object",
                        "description": "First geometry in GeoJSON format, if you have one (not for named places).",
                    },
                    "geometry_b": {
                        "type": "object",
                        "description": "Second geometry in GeoJSON format, if you have one (not for named places).",
                    },
                    "relationship": {
                        "type": "string",
                        "enum": [
                            "contains", "intersects", "within", "touches",
                            "crosses", "overlaps", "disjoint",
                        ],
                        "description": "The relationship of the first to the second (A within B, A contains B).",
                    },
                },
                "required": ["explanation", "relationship"],
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

    def _get_handlers(self) -> dict[str, Any]:
        return {
            "check_spatial_relationship": self._handle_relationship,
            "calculate_distance": self._handle_distance,
            "spatial_operation": self._handle_operation,
        }

    # A relationship that asks whether one thing lies inside the other: the outer one needs an area
    _CONTAINMENT: ClassVar[dict[str, str]] = {"within": "b", "contains": "a"}

    def _handle_relationship(self, args: dict[str, Any]) -> dict[str, Any]:
        """Named places are resolved here: the container to its boundary, the other to a point."""
        from geospark.agents import amenities

        relationship = str(args.get("relationship"))
        outer = self._CONTAINMENT.get(relationship)
        geometries: dict[str, dict[str, Any]] = {}
        lookups: list[SpatialResult] = []
        resolved: dict[str, dict[str, Any]] = {}
        for side in ([outer, "b" if outer == "a" else "a"] if outer else ["a", "b"]):  # the outer place first
            name, geometry = args.get(f"place_{side}"), args.get(f"geometry_{side}")
            if isinstance(name, str) and name.strip():
                name = name.strip()
                if outer is None or side == outer:
                    boundary = amenities.place_boundary(name)
                    if boundary is not None:
                        geometries[side] = boundary
                        resolved[side] = {"query": name, "used": "boundary (OpenStreetMap, simplified)"}
                        continue
                    if side == outer:
                        return {"result": None, "errors": [
                            f"'{name}' has no boundary in OpenStreetMap (it is a point there), so whether "
                            "something lies inside it can't be checked."]}
                point, place, found = geocode_place(name)
                if point is None:
                    return {"result": None, "errors": [place["error"]],
                            "suggestion": "Add the city or country to the place name."}
                geometries[side] = point
                resolved[side] = {**place, "used": "point"}
                lookups.append(found)
            elif isinstance(geometry, dict):
                geometries[side] = geometry
            else:
                return {"result": None, "errors": [f"Give place_{side} (a name) or geometry_{side} (GeoJSON)."]}
        places = [resolved[side] for side in ("a", "b") if side in resolved]
        if outer and geometries[outer].get("type") in ("Point", "MultiPoint"):
            return {"result": None, "errors": [
                "The outer geometry is a point, which has no area, so nothing can be inside it. Pass the "
                "places by name (place_a, place_b) and the server uses the outer place's boundary."]}
        holds = SpatialReasoner.check_relationship(geometries["a"], geometries["b"], relationship)
        checked = enrich(SpatialResult(), relationship, [geometries["a"], geometries["b"]])
        merge_lookups(checked, lookups)
        if any(p["used"].startswith("boundary") for p in places):
            checked.provenance.insert(0, source_provenance("openstreetmap-nominatim"))
        result: dict[str, Any] = {"relationship": relationship, "holds": holds}
        if places:
            result["places"] = places
        return {
            "result": result,
            "metadata": {"method": "ground_truth_topology", "crs": "EPSG:4326", **verification(checked)},
        }

    def _handle_distance(self, args: dict[str, Any]) -> dict[str, Any]:
        """Distance between two places. Named places are geocoded here, so the model never has to
        supply (and possibly invent) coordinates for them."""
        points: dict[str, dict[str, Any]] = {}
        places: list[dict[str, Any]] = []
        lookups: list[SpatialResult] = []
        for side in ("a", "b"):
            name, point = args.get(f"place_{side}"), args.get(f"point_{side}")
            if isinstance(name, str) and name.strip():
                geometry, place, found = geocode_place(name.strip())
                if geometry is None:
                    return {"result": None, "errors": [place["error"]],
                            "suggestion": "Add the city or country to the place name, or call geocode first."}
                points[side] = geometry
                places.append({**place, "query": name})
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
        merge_lookups(checked, lookups)  # where the places came from, and any ambiguity
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
