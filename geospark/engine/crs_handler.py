"""
CRS (Coordinate Reference System) Handler.

Handles the #1 source of errors in geospatial data: coordinate system
mismatches. Provides automatic detection, transformation, and validation.
"""

from __future__ import annotations

from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

from geospark.protocol.schema import Geometry


class CRSHandler:
    """
    Handles coordinate reference system operations.

    CRS confusion is the most common source of geospatial errors.
    This handler provides:
    - Automatic CRS detection from data
    - Transformation between any two CRS
    - Validation that coordinates are in expected ranges
    - Smart defaults (EPSG:4326 for geographic, UTM for local)
    """

    # Cache transformers for performance
    _transformer_cache: dict[tuple[str, str], Transformer] = {}

    def get_transformer(self, from_crs: str, to_crs: str) -> Transformer:
        """Get a cached transformer between two CRS."""
        key = (from_crs, to_crs)
        if key not in self._transformer_cache:
            self._transformer_cache[key] = Transformer.from_crs(
                CRS(from_crs), CRS(to_crs), always_xy=True
            )
        return self._transformer_cache[key]

    def transform_geometry(
        self, geometry: Geometry, from_crs: str, to_crs: str
    ) -> Geometry:
        """Transform a GSP geometry from one CRS to another."""
        geom_dict = geometry.model_dump()
        shapely_geom = shape(geom_dict)

        transformer = self.get_transformer(from_crs, to_crs)
        transformed = transform(transformer.transform, shapely_geom)

        # Reconstruct the GSP geometry from the transformed shapely geometry
        result_dict = mapping(transformed)
        return type(geometry).model_validate(result_dict)

    def transform_coords(
        self,
        x: float,
        y: float,
        from_crs: str = "EPSG:4326",
        to_crs: str = "EPSG:3857",
    ) -> tuple[float, float]:
        """Transform a single coordinate pair."""
        transformer = self.get_transformer(from_crs, to_crs)
        return transformer.transform(x, y)

    def validate_coordinates(
        self, lon: float, lat: float, crs: str = "EPSG:4326"
    ) -> bool:
        """
        Validate that coordinates are within expected bounds for a CRS.

        Returns True if valid, False otherwise.
        """
        if crs == "EPSG:4326":
            return -180 <= lon <= 180 and -90 <= lat <= 90
        # For other CRS, check against the CRS bounds
        crs_obj = CRS(crs)
        bounds = crs_obj.area_of_use
        if bounds:
            return (
                bounds.west <= lon <= bounds.east
                and bounds.south <= lat <= bounds.north
            )
        return True  # Cannot validate unknown CRS bounds

    def suggest_utm_zone(self, lon: float, lat: float) -> str:
        """
        Suggest the appropriate UTM zone for a given location.

        Useful for switching from geographic to projected CRS for
        accurate distance/area calculations.
        """
        zone_number = int((lon + 180) / 6) + 1
        hemisphere = "north" if lat >= 0 else "south"
        epsg = 32600 + zone_number if hemisphere == "north" else 32700 + zone_number
        return f"EPSG:{epsg}"

    def get_crs_info(self, crs: str) -> dict[str, Any]:
        """Get human-readable information about a CRS."""
        crs_obj = CRS(crs)
        return {
            "code": crs,
            "name": crs_obj.name,
            "type": "geographic" if crs_obj.is_geographic else "projected",
            "units": str(crs_obj.axis_info[0].unit_name) if crs_obj.axis_info else "unknown",
            "area_of_use": str(crs_obj.area_of_use) if crs_obj.area_of_use else None,
        }
