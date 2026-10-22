"""
Spatial Reasoning Engine.

Performs topology, distance, containment, and geometric operations
that LLMs fundamentally cannot do. This is the core value proposition
of GeoSpark -- giving AI models genuine spatial capabilities.

Coordinate assumptions:
    - All geometries are assumed WGS84 (EPSG:4326) unless CRS is specified.
    - Distances use pyproj Geod on the WGS84 ellipsoid (geodesic, not planar).
    - Areas use pyproj geometry_area_perimeter (geodesic on WGS84).
    - Buffers are computed in a local azimuthal equidistant projection (exact for points).
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

    @staticmethod
    def validate_geometry(geom: Any, role: str = "geometry", geographic: bool = True) -> Any:
        """Parse a GeoJSON geometry and refuse anything that would give a wrong answer.

        Raises ``ValueError`` (with an explanation a caller or an LLM can act on) for
        malformed or empty geometries, coordinates outside lon/lat range (and says when they
        look like [lat, lon] order), and invalid geometries such as self-intersecting polygons.
        Returns the Shapely geometry.
        """
        try:
            parsed = shape(geom)
        except Exception as e:  # malformed GeoJSON raises KeyError/TypeError/GEOS errors
            raise ValueError(f"The {role} is not valid GeoJSON ({type(e).__name__}: {e}).") from e
        if parsed.is_empty:
            raise ValueError(f"The {role} is empty.")
        if geographic:
            minx, miny, maxx, maxy = parsed.bounds
            if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
                swapped = minx >= -90 and maxx <= 90 and miny >= -180 and maxy <= 180
                hint = (
                    " The values look like [latitude, longitude]; GeoJSON coordinates are "
                    "[longitude, latitude]."
                    if swapped
                    else ""
                )
                raise ValueError(
                    f"The {role} has coordinates outside longitude [-180, 180] / latitude [-90, 90].{hint}"
                )
        if not parsed.is_valid:
            from shapely.validation import explain_validity

            raise ValueError(
                f"The {role} is not a valid geometry ({explain_validity(parsed)}). Computing on it "
                "would give a wrong answer; repair it first (for example with shapely.make_valid)."
            )
        return parsed

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute a spatial reasoning operation.

        Inputs are validated first (an invalid input gives a ``cannot_answer`` result with the
        reason), and every answer is enriched with provenance, units and quality flags.
        """
        from geospark.protocol.provenance import enrich

        inputs: list[dict[str, Any]] = []
        geographic = query.crs in ("EPSG:4326", "OGC:CRS84")
        try:
            if query.geometry is not None:
                inputs.append(query.geometry.model_dump())
                self.validate_geometry(inputs[-1], "geometry", geographic)
            geom_b = (query.metadata or {}).get("geometry_b")
            if geom_b is not None:
                inputs.append(geom_b)
                self.validate_geometry(geom_b, "second geometry (geometry_b)", geographic)
        except ValueError as e:
            return SpatialResult(errors=[str(e)])

        result = self._dispatch(query)
        return enrich(result, query.operation.value, inputs)

    def _dispatch(self, query: SpatialQuery) -> SpatialResult:
        """Route a validated query to its handler."""
        handlers = {
            SpatialOperation.BUFFER: self._buffer,
            SpatialOperation.DISTANCE: self._distance,
            SpatialOperation.AREA: self._area,
            SpatialOperation.LENGTH: self._length,
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

    @staticmethod
    def geodesic_buffer(geom: Any, radius_m: float) -> Any:
        """Buffer a WGS84 geometry by ``radius_m`` metres, keeping its shape.

        The geometry is projected into an azimuthal equidistant CRS centred on it (distances
        from the centre are exact, and nearly exact for anything local), buffered there,
        and projected back. Buffering a point gives a geodesic circle; buffering a polygon
        or line grows its real outline instead of drawing a circle round its centroid.
        ``radius_m=0`` returns the geometry unchanged; a negative radius shrinks polygons.
        Not suited to geometries spanning thousands of km or crossing the antimeridian.
        """
        if radius_m == 0:
            return geom
        from pyproj import CRS, Transformer

        center = geom.centroid
        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m +no_defs"
        )
        from geospark.engine.crs_handler import reproject

        to_local = Transformer.from_crs("EPSG:4326", local, always_xy=True)
        to_wgs84 = Transformer.from_crs(local, "EPSG:4326", always_xy=True)
        return reproject(reproject(geom, to_local).buffer(radius_m, quad_segs=16), to_wgs84)

    def _buffer(self, query: SpatialQuery) -> SpatialResult:
        """Create a geodesic buffer around a geometry."""
        if query.geometry is None:
            return SpatialResult(errors=["Buffer requires a geometry"])

        geom = shape(query.geometry.model_dump())
        radius = 1000.0 if query.radius_m is None else float(query.radius_m)  # Default 1 km

        buffered = self.geodesic_buffer(geom, radius)

        # Geodesic area
        geod = Geod(ellps="WGS84")
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

    def _length(self, query: SpatialQuery) -> SpatialResult:
        """Geodesic length of a line (or the perimeter of a polygon) on WGS84."""
        if query.geometry is None:
            return SpatialResult(errors=["Length requires a geometry"])

        geom = shape(query.geometry.model_dump())
        length_m = Geod(ellps="WGS84").geometry_length(geom)

        return SpatialResult(
            features=[
                SpatialFeature(
                    geometry=mapping(geom),
                    properties={
                        "operation": "length",
                        "length_m": round(length_m, 2),
                        "length_km": round(length_m / 1000, 4),
                        "length_method": "geodesic (WGS84 ellipsoid)",
                    },
                )
            ],
            spatial_context=SpatialContext(
                crs="EPSG:4326",
                total_features=1,
                summary=f"Geodesic length: {length_m / 1000:.3f} km",
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

        Raises:
            ValueError: if either geometry is malformed, out of range or invalid.
        """
        a = SpatialReasoner.validate_geometry(geom_a, "first geometry")
        b = SpatialReasoner.validate_geometry(geom_b, "second geometry")

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
        return float(abs(distance_m))

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

        Raises:
            ValueError: if either geometry is malformed, out of range or invalid, or the
                relationship is unknown.
        """
        a = SpatialReasoner.validate_geometry(geom_a, "first geometry")
        b = SpatialReasoner.validate_geometry(geom_b, "second geometry")

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

        return bool(check_fn(b))
