"""
NDVI Tool.

Calculates Normalized Difference Vegetation Index from satellite imagery.
Uses STAC API to discover Sentinel-2 scenes and provides NDVI computation
stubs for when raster data is available.
"""

from __future__ import annotations

from typing import Any

import httpx

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
)
from geospark.tools.base import BaseTool


class NDVITool(BaseTool):
    """Calculate NDVI from Sentinel-2 imagery.

    NDVI (Normalized Difference Vegetation Index) measures vegetation
    health using the formula: (NIR - Red) / (NIR + Red).
    Sentinel-2 Band 8 = NIR (842 nm), Band 4 = Red (665 nm).
    """

    name = "ndvi"
    description = (
        "Calculate vegetation index (NDVI) from satellite imagery. "
        "Use when assessing vegetation health, crop monitoring, or "
        "land cover analysis. Returns scene metadata and NDVI stats. "
        "Do NOT use for water or urban indices."
    )
    supported_operations = [
        SpatialOperation.NDVI.value,
        SpatialOperation.BAND_MATH.value,
    ]

    STAC_API = "https://earth-search.aws.element84.com/v1"
    COLLECTION = "sentinel-2-l2a"

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute NDVI query.

        Args:
            query: Spatial query with geometry and optional temporal filter.

        Returns:
            SpatialResult with available scenes and NDVI metadata.
        """
        if query.operation not in (SpatialOperation.NDVI, SpatialOperation.BAND_MATH):
            return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])
        return self._search_and_prepare(query)

    def _search_and_prepare(self, query: SpatialQuery) -> SpatialResult:
        """Search STAC for imagery and return NDVI-ready metadata."""
        search_body = self._build_stac_search(query)

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{self.STAC_API}/search",
                    json=search_body,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return SpatialResult(errors=[f"STAC search failed: {e}"])

        stac_features = data.get("features", [])
        features = []
        for item in stac_features:
            props = item.get("properties", {})
            assets = item.get("assets", {})
            features.append(
                SpatialFeature(
                    id=item.get("id"),
                    geometry=item.get("geometry", {}),
                    properties={
                        "datetime": props.get("datetime", ""),
                        "cloud_cover": props.get("eo:cloud_cover"),
                        "platform": props.get("platform", ""),
                        "nir_band": "B08",
                        "red_band": "B04",
                        "ndvi_formula": "(B08 - B04) / (B08 + B04)",
                        "has_nir": "nir" in assets or "B08" in assets,
                        "has_red": "red" in assets or "B04" in assets,
                    },
                )
            )

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=(
                    f"Found {len(features)} Sentinel-2 scenes for NDVI analysis. "
                    f"NDVI = (NIR[B08] - Red[B04]) / (NIR[B08] + Red[B04])"
                ),
            ),
            sources=["element84-earth-search", "sentinel-2-l2a"],
        )

    def _build_stac_search(self, query: SpatialQuery) -> dict[str, Any]:
        """Build a STAC API search request body."""
        body: dict[str, Any] = {
            "collections": [self.COLLECTION],
            "limit": min(query.limit, 10),
        }
        if query.geometry:
            body["intersects"] = query.geometry.model_dump()
        elif query.bbox:
            body["bbox"] = list(query.bbox.to_tuple())
        if query.filters and query.filters.temporal:
            parts = []
            if query.filters.temporal.after:
                parts.append(query.filters.temporal.after.isoformat())
            else:
                parts.append("..")
            if query.filters.temporal.before:
                parts.append(query.filters.temporal.before.isoformat())
            else:
                parts.append("..")
            body["datetime"] = "/".join(parts)
        return body

    @staticmethod
    def _calculate_ndvi_from_arrays(nir: Any, red: Any) -> Any:
        """Calculate NDVI from numpy arrays.

        Args:
            nir: numpy array of NIR band values (Band 8).
            red: numpy array of Red band values (Band 4).

        Returns:
            numpy array of NDVI values in range [-1, 1].
        """
        import numpy as np

        nir = nir.astype(np.float64)
        red = red.astype(np.float64)
        denominator = nir + red
        ndvi = np.where(denominator == 0, 0.0, (nir - red) / denominator)
        return np.clip(ndvi, -1.0, 1.0)
