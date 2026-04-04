"""
STAC Client Tool.

Accesses satellite imagery through SpatioTemporal Asset Catalog (STAC) APIs.
Supports Sentinel-2, Landsat, and other STAC-compliant data sources.

STAC API version: 1.0.0 (via pystac-client).
Temporal filtering uses ISO 8601 datetime strings.
"""

from __future__ import annotations

from typing import ClassVar

from geospark.protocol.schema import (
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.tools.base import BaseTool


class STACTool(BaseTool):
    """Access satellite imagery via STAC APIs."""

    name = "satellite"
    description = "Browse and query satellite imagery from Sentinel-2, Landsat, and other sources"
    supported_operations: ClassVar[list[str]] = [
        SpatialOperation.SATELLITE_VIEW.value,
        SpatialOperation.BAND_MATH.value,
    ]

    # Default STAC endpoints
    STAC_ENDPOINTS: ClassVar[dict[str, str]] = {
        "element84": "https://earth-search.aws.element84.com/v1",
        "planetary_computer": "https://planetarycomputer.microsoft.com/api/stac/v1",
    }

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute satellite data query."""
        if query.operation == SpatialOperation.SATELLITE_VIEW:
            return self._search_imagery(query)
        elif query.operation == SpatialOperation.BAND_MATH:
            return self._band_math(query)
        return SpatialResult(errors=[f"Unsupported operation: {query.operation}"])

    def _search_imagery(self, query: SpatialQuery) -> SpatialResult:
        """Search for satellite imagery matching spatial and temporal criteria."""
        try:
            from pystac_client import Client
        except ImportError:
            return SpatialResult(
                errors=["pystac-client required: pip install geospark[satellite]"]
            )

        # Build search parameters
        search_params: dict = {}

        if query.bbox:
            search_params["bbox"] = list(query.bbox.to_tuple())
        elif query.geometry:
            geom_dict = query.geometry.model_dump()
            search_params["intersects"] = geom_dict

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
            search_params["datetime"] = "/".join(parts)

        search_params["max_items"] = query.limit
        search_params["collections"] = ["sentinel-2-l2a"]  # Default collection

        # Search STAC catalog
        client = Client.open(self.STAC_ENDPOINTS["element84"])
        search = client.search(**search_params)

        features = []
        for item in search.items():
            features.append(
                SpatialFeature(
                    id=item.id,
                    geometry=item.geometry,
                    properties={
                        "datetime": str(item.datetime),
                        "collection": item.collection_id,
                        "cloud_cover": item.properties.get("eo:cloud_cover"),
                        "platform": item.properties.get("platform", ""),
                        "assets": list(item.assets.keys()),
                    },
                )
            )

        if not features:
            return SpatialResult(
                spatial_context=SpatialContext(
                    total_features=0,
                    summary="No satellite scenes found matching the search criteria",
                ),
                sources=["element84-earth-search"],
            )

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=f"Found {len(features)} satellite scenes",
            ),
            sources=["element84-earth-search"],
        )

    def _band_math(self, query: SpatialQuery) -> SpatialResult:
        """Calculate spectral indices (NDVI, NDWI, etc.)."""
        # TODO: Implement band math calculations
        return SpatialResult(
            spatial_context=SpatialContext(
                summary="Band math calculation (coming in Phase 1)",
            ),
        )
