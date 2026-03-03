"""
Spatial Reasoning Engine.

Performs topology, distance, containment, and geometric operations
that LLMs fundamentally cannot do. This is the core value proposition
of GeoSpark -- giving AI models genuine spatial capabilities.
"""

from __future__ import annotations

from typing import Any

import shapely
from shapely.geometry import shape, mapping
from shapely import ops

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
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
        """Create a buffer around a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Buffer requires a geometry"])

        geom = shape(query.geometry.model_dump())
        radius = query.radius_m or 1000  # Default 1km

        # For geographic coordinates, convert meters to approximate degrees
        # TODO: Use pyproj for proper geodesic buffer
        radius_deg = radius / 111_320  # Rough meters-to-degrees at equator
        buffered = geom.buffer(radius_deg)

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(buffered),
                    properties={
                        "operation": "buffer",
                        "radius_m": radius,
                        "area_sq_m": buffered.area * (111_320 ** 2),  # Approximate
                    },
                )
            ],
            spatial_context=SpatialContext(
                total_features=1,
                summary=f"Buffer of {radius}m created",
            ),
        )

    def _distance(self, query: SpatialQuery) -> SpatialResult:
        """Calculate distance between geometries."""
        if query.geometry is None:
            return SpatialResult(errors=["Distance requires a geometry"])

        geom = shape(query.geometry.model_dump())

        # TODO: Accept second geometry from query metadata
        # For now, return the geometry with distance placeholder
        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom),
                    properties={"operation": "distance"},
                )
            ],
            spatial_context=SpatialContext(
                summary="Distance calculation (provide two geometries for comparison)",
            ),
        )

    def _area(self, query: SpatialQuery) -> SpatialResult:
        """Calculate area of a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Area requires a geometry"])

        geom = shape(query.geometry.model_dump())

        # Approximate area in square meters (for geographic coordinates)
        # TODO: Use pyproj for proper geodesic area calculation
        area_sq_deg = geom.area
        area_sq_m = area_sq_deg * (111_320 ** 2)  # Very rough approximation

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom),
                    properties={
                        "operation": "area",
                        "area_sq_m": area_sq_m,
                        "area_sq_km": area_sq_m / 1_000_000,
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"Area: ~{area_sq_m / 1_000_000:.2f} sq km",
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

        # TODO: Accept second geometry from query metadata for comparison
        geom = shape(query.geometry.model_dump())

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom),
                    properties={
                        "operation": query.operation.value,
                        "note": "Provide two geometries to check topology",
                    },
                )
            ],
            spatial_context=SpatialContext(
                summary=f"Topology check: {query.operation.value}",
            ),
        )

    def _geometric_operation(self, query: SpatialQuery) -> SpatialResult:
        """Perform geometric set operations (union, intersection, difference)."""
        if query.geometry is None:
            return SpatialResult(errors=[f"{query.operation.value} requires geometries"])

        return SpatialResult(
            spatial_context=SpatialContext(
                summary=f"Geometric operation: {query.operation.value} (requires two geometries)",
            ),
        )

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
