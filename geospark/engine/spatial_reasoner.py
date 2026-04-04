"""
Spatial Reasoning Engine.

Performs topology, distance, containment, and geometric operations
that LLMs fundamentally cannot do. This is the core value proposition
of GeoSpark -- giving AI models genuine spatial capabilities.

Coordinate assumptions:
    - All geometries are assumed WGS84 (EPSG:4326) unless CRS is specified.
    - Distances use pyproj Geod on the WGS84 ellipsoid (geodesic, not planar).
    - Areas use pyproj geometry_area_perimeter (geodesic on WGS84).
    - Buffers use 64-point geodesic sampling via Geod.fwd().
    - Topology checks use Shapely (planar predicates on projected coordinates).

Limitations:
    - Antimeridian (±180° longitude) crossing is not explicitly handled.
      Geometries that span the antimeridian may produce incorrect results.
    - Topology checks are planar (Shapely), not geodesic. For global-scale
      geometries, results may differ from true spherical topology.
"""

from __future__ import annotations

from typing import Any

from pyproj import Geod
from shapely import ops
from shapely.geometry import mapping, shape

from geospark.protocol.schema import (
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)


class SpatialReasoner:
    """
    Performs spatial reasoning operations that LLMs cannot.

    Key capabilities:
    - Topological relations (contains, intersects, touches, etc.)
    - Distance calculations (geodesic, Euclidean)
    - Geometric operations (buffer, union, intersection, etc.)
    - Spatial aggregation (zonal stats, spatial joins)
    """

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute a spatial reasoning operation."""
        handlers = {
            SpatialOperation.BUFFER: self._buffer,
            SpatialOperation.DISTANCE: self._distance,
            SpatialOperation.AREA: self._area,
            SpatialOperation.CENTROID: self._centroid,
            SpatialOperation.CONVEX_HULL: self._convex_hull,
            SpatialOperation.CONTAINS: self._topology_check,
            SpatialOperation.INTERSECTS: self._topology_check,
            SpatialOperation.WITHIN: self._topology_check,
            SpatialOperation.TOUCHES: self._topology_check,
            SpatialOperation.CROSSES: self._topology_check,
            SpatialOperation.OVERLAPS: self._topology_check,
            SpatialOperation.DISJOINT: self._topology_check,
            SpatialOperation.UNION: self._geometric_operation,
            SpatialOperation.INTERSECTION: self._geometric_operation,
            SpatialOperation.DIFFERENCE: self._geometric_operation,
        }

        handler = handlers.get(query.operation)
        if handler is None:
            return SpatialResult(
                errors=[f"Unsupported reasoning operation: {query.operation}"]
            )

        return handler(query)

    def _buffer(self, query: SpatialQuery) -> SpatialResult:
        """Create a geodesic buffer around a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Buffer requires a geometry"])

        geom = shape(query.geometry.model_dump())
        radius = query.radius_m or 1000  # Default 1km

        # Geodesic buffer: sample 64 points at exact distance from centroid
        geod = Geod(ellps="WGS84")
        center = geom.centroid
        n_points = 64
        coords = []
        for i in range(n_points):
            az = 360.0 * i / n_points
            lon, lat, _ = geod.fwd(center.x, center.y, az, radius)
            coords.append((lon, lat))
        coords.append(coords[0])  # Close the ring

        from shapely.geometry import Polygon as ShapelyPolygon

        buffered = ShapelyPolygon(coords)

        # Geodesic area
        area_sq_m, _ = geod.geometry_area_perimeter(buffered)
        area_sq_m = abs(area_sq_m)

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(buffered),
                    properties={
                        "operation": "buffer",
                        "radius_m": radius,
                        "area_sq_m": round(area_sq_m, 2),
                    },
                )
            ],
            spatial_context=SpatialContext(
                total_features=1,
                summary=f"Geodesic buffer of {radius}m created ({area_sq_m / 1_000_000:.3f} sq km)",
            ),
        )

    def _distance(self, query: SpatialQuery) -> SpatialResult:
        """Calculate geodesic distance between two geometries."""
        if query.geometry is None:
            return SpatialResult(errors=["Distance requires a geometry"])

        geom_b_raw = (query.metadata or {}).get("geometry_b")
        if geom_b_raw is None:
            return SpatialResult(errors=[
                "Distance requires two geometries. Pass the second via metadata.geometry_b"
            ])

        geom_a = shape(query.geometry.model_dump())
        geom_b = shape(geom_b_raw)

        distance_m = self.calculate_distance(
            mapping(geom_a), mapping(geom_b)
        )

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom_a),
                    properties={
                        "operation": "distance",
                        "distance_m": distance_m,
                        "distance_km": distance_m / 1000,
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"Geodesic distance: {distance_m:,.1f} m ({distance_m / 1000:,.2f} km)",
            ),
        )

    def _area(self, query: SpatialQuery) -> SpatialResult:
        """Calculate geodesic area of a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Area requires a geometry"])

        geom = shape(query.geometry.model_dump())

        # Geodesic area using pyproj
        geod = Geod(ellps="WGS84")
        area_sq_m, perimeter_m = geod.geometry_area_perimeter(geom)
        area_sq_m = abs(area_sq_m)

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom),
                    properties={
                        "operation": "area",
                        "area_sq_m": round(area_sq_m, 2),
                        "area_sq_km": round(area_sq_m / 1_000_000, 4),
                        "perimeter_m": round(perimeter_m, 2),
                        "area_method": "geodesic (WGS84 ellipsoid)",
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"Geodesic area: {area_sq_m / 1_000_000:.4f} sq km, perimeter: {perimeter_m:,.1f} m",
            ),
        )

    def _centroid(self, query: SpatialQuery) -> SpatialResult:
        """Calculate centroid of a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Centroid requires a geometry"])

        geom = shape(query.geometry.model_dump())
        centroid = geom.centroid

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(centroid),
                    properties={"operation": "centroid"},
                )
            ],
            spatial_context=SpatialContext(
                summary=f"Centroid at ({centroid.x:.6f}, {centroid.y:.6f})",
            ),
        )

    def _convex_hull(self, query: SpatialQuery) -> SpatialResult:
        """Calculate convex hull of a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Convex hull requires a geometry"])

        geom = shape(query.geometry.model_dump())
        hull = geom.convex_hull

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(hull),
                    properties={"operation": "convex_hull"},
                )
            ],
            spatial_context=SpatialContext(
                summary="Convex hull computed",
            ),
        )

    def _topology_check(self, query: SpatialQuery) -> SpatialResult:
        """
        Check topological relationships between geometries.

        This is where GeoSpark provides the most value -- LLMs fail at
        topological reasoning 42-80% of the time. GeoSpark provides
        ground-truth spatial relationship evaluation.
        """
        if query.geometry is None:
            return SpatialResult(errors=["Topology check requires a geometry"])

        geom_a = shape(query.geometry.model_dump())
        geom_b_raw = (query.metadata or {}).get("geometry_b")

        if geom_b_raw is None:
            return SpatialResult(
                features=[
                    SpatialFeature(
                        geometry=mapping(geom_a),
                        properties={
                            "operation": query.operation.value,
                            "note": "Pass second geometry via metadata.geometry_b for comparison",
                        },
                    )
                ],
                spatial_context=SpatialContext(
                    summary=f"Topology check: {query.operation.value} — needs geometry_b",
                ),
            )

        geom_b = shape(geom_b_raw)
        result = self.check_relationship(
            mapping(geom_a), mapping(geom_b), query.operation.value
        )

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom_a),
                    properties={
                        "operation": query.operation.value,
                        "result": result,
                        "geometry_b": mapping(geom_b),
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"{query.operation.value}: {result}",
            ),
        )

    def _geometric_operation(self, query: SpatialQuery) -> SpatialResult:
        """Perform geometric set operations (union, intersection, difference)."""
        if query.geometry is None:
            return SpatialResult(errors=[f"{query.operation.value} requires geometries"])

        geom_a = shape(query.geometry.model_dump())
        geom_b_raw = (query.metadata or {}).get("geometry_b")

        if geom_b_raw is None:
            return SpatialResult(
                errors=[
                    f"{query.operation.value} requires two geometries. "
                    "Pass the second via metadata.geometry_b"
                ]
            )

        geom_b = shape(geom_b_raw)
        op_map = {
            SpatialOperation.UNION: geom_a.union,
            SpatialOperation.INTERSECTION: geom_a.intersection,
            SpatialOperation.DIFFERENCE: geom_a.difference,
        }
        op_fn = op_map.get(query.operation)
        if op_fn is None:
            return SpatialResult(errors=[f"Unsupported geometric operation: {query.operation.value}"])

        result_geom = op_fn(geom_b)

        geod = Geod(ellps="WGS84")
        area_sq_m = 0.0
        if not result_geom.is_empty and result_geom.geom_type in ("Polygon", "MultiPolygon"):
            area_sq_m = abs(geod.geometry_area_perimeter(result_geom)[0])

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(result_geom),
                    properties={
                        "operation": query.operation.value,
                        "area_sq_m": round(area_sq_m, 2),
                        "is_empty": result_geom.is_empty,
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"{query.operation.value}: result is {result_geom.geom_type}"
                f"{' (empty)' if result_geom.is_empty else ''}",
            ),
        )

    @staticmethod
    def calculate_distance(
        geom_a: dict[str, Any],
        geom_b: dict[str, Any],
    ) -> float:
        """
        Calculate geodesic distance between two geometries in meters.

        Uses pyproj Geod (WGS84 ellipsoid) for accurate great-circle distance.
        For non-point geometries, uses nearest points on the geometry boundaries.

        Args:
            geom_a: GeoJSON geometry dict
            geom_b: GeoJSON geometry dict

        Returns:
            Distance in meters (geodesic, not planar)
        """
        a = shape(geom_a)
        b = shape(geom_b)

        # Get representative points for distance calculation
        # For points, use directly; for polygons/lines, use nearest points
        if a.geom_type == "Point" and b.geom_type == "Point":
            lon1, lat1 = a.x, a.y
            lon2, lat2 = b.x, b.y
        else:
            nearest = ops.nearest_points(a, b)
            lon1, lat1 = nearest[0].x, nearest[0].y
            lon2, lat2 = nearest[1].x, nearest[1].y

        geod = Geod(ellps="WGS84")
        _, _, distance_m = geod.inv(lon1, lat1, lon2, lat2)
        return abs(distance_m)

    @staticmethod
    def check_relationship(
        geom_a: dict[str, Any],
        geom_b: dict[str, Any],
        relationship: str,
    ) -> bool:
        """
        Check if a specific topological relationship holds between two geometries.

        This is the core spatial reasoning function that LLMs cannot replicate.

        Args:
            geom_a: GeoJSON geometry dict
            geom_b: GeoJSON geometry dict
            relationship: One of 'contains', 'intersects', 'within', 'touches',
                         'crosses', 'overlaps', 'disjoint'

        Returns:
            True if the relationship holds, False otherwise
        """
        a = shape(geom_a)
        b = shape(geom_b)

        checks = {
            "contains": a.contains,
            "intersects": a.intersects,
            "within": a.within,
            "touches": a.touches,
            "crosses": a.crosses,
            "overlaps": a.overlaps,
            "disjoint": a.disjoint,
        }

        check_fn = checks.get(relationship)
        if check_fn is None:
            raise ValueError(f"Unknown relationship: {relationship}")

        return check_fn(b)
