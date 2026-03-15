"""
Spatial Aggregator.

Provides zonal statistics, spatial joins, and hexagonal aggregation
for spatial feature collections.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field
from shapely.geometry import shape


class ZonalStats(BaseModel):
    """Zonal statistics for a set of values within a geometry."""

    min: float
    max: float
    mean: float
    std: float
    count: int
    percentiles: dict[str, float] = Field(default_factory=dict)


class SpatialAggregator:
    """
    Performs spatial aggregation operations.

    Capabilities:
    - Zonal statistics (min, max, mean, std, percentiles)
    - Spatial joins by predicate (intersects, contains, within)
    - Hexagonal aggregation via H3 (stub when h3 is not installed)

    Usage:
        agg = SpatialAggregator()
        stats = agg.zonal_stats(polygon_geojson, [1.0, 2.0, 3.0])
    """

    def zonal_stats(
        self,
        geometry: dict[str, Any],
        values: list[float],
    ) -> ZonalStats:
        """
        Compute statistics for values within a geometry.

        Args:
            geometry: GeoJSON geometry defining the zone.
            values: Numeric values to aggregate.

        Returns:
            ZonalStats with min, max, mean, std, count, and percentiles.

        Raises:
            ValueError: If values list is empty.
        """
        if not values:
            raise ValueError("Cannot compute zonal stats on empty values")

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        mean = sum(sorted_vals) / n
        variance = sum((v - mean) ** 2 for v in sorted_vals) / n
        std = math.sqrt(variance)

        percentiles = {}
        for p in (25, 50, 75):
            idx = (p / 100) * (n - 1)
            lo = math.floor(idx)
            hi = math.ceil(idx)
            if lo == hi:
                percentiles[f"p{p}"] = sorted_vals[lo]
            else:
                frac = idx - lo
                percentiles[f"p{p}"] = (
                    sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
                )

        return ZonalStats(
            min=sorted_vals[0],
            max=sorted_vals[-1],
            mean=mean,
            std=std,
            count=n,
            percentiles=percentiles,
        )

    def spatial_join(
        self,
        features_a: list[dict[str, Any]],
        features_b: list[dict[str, Any]],
        predicate: str = "intersects",
    ) -> list[dict[str, Any]]:
        """
        Join two feature lists by spatial relationship.

        For each feature in *features_a*, find all features in
        *features_b* that satisfy *predicate* and merge their
        properties.

        Args:
            features_a: Left-side GeoJSON features.
            features_b: Right-side GeoJSON features.
            predicate: Spatial predicate (intersects, contains, within).

        Returns:
            List of joined feature dicts with merged properties.
        """
        predicate_fn = {
            "intersects": lambda a, b: a.intersects(b),
            "contains": lambda a, b: a.contains(b),
            "within": lambda a, b: a.within(b),
        }.get(predicate)

        if predicate_fn is None:
            raise ValueError(f"Unsupported predicate: {predicate}")

        geoms_b = [(shape(f["geometry"]), f) for f in features_b]
        joined: list[dict[str, Any]] = []

        for feat_a in features_a:
            geom_a = shape(feat_a["geometry"])
            for geom_b, feat_b in geoms_b:
                if predicate_fn(geom_a, geom_b):
                    merged_props = {
                        **feat_a.get("properties", {}),
                        **feat_b.get("properties", {}),
                    }
                    joined.append({
                        "geometry": feat_a["geometry"],
                        "properties": merged_props,
                    })

        return joined

    def aggregate_by_hex(
        self,
        features: list[dict[str, Any]],
        resolution: int = 7,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Aggregate features into H3 hexagonal cells.

        Requires the optional ``h3`` package. Returns a dict mapping
        H3 cell IDs to the features that fall within each cell.

        Args:
            features: GeoJSON feature dicts with Point geometries.
            resolution: H3 resolution (0-15, default 7).

        Returns:
            Mapping of H3 cell ID to list of features.

        Raises:
            ImportError: If h3 is not installed.
        """
        try:
            import h3  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "h3 package required for hexagonal aggregation. "
                "Install with: pip install h3"
            ) from e

        cells: dict[str, list[dict[str, Any]]] = {}
        for feat in features:
            coords = feat.get("geometry", {}).get("coordinates")
            if coords and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                cell_id = h3.latlng_to_cell(lat, lon, resolution)
                cells.setdefault(cell_id, []).append(feat)

        return cells
