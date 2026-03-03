"""
Pixel-Level Change Detection Tool.

Detects changes between satellite images from different time periods.
"""

from __future__ import annotations

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialOperation,
)
from geospark.tools.base import BaseTool


class PixelChangeTool(BaseTool):
    """Detect pixel-level changes between temporal satellite images."""

    name = "change_detection"
    description = "Detect changes between satellite images from different time periods"
    supported_operations = [SpatialOperation.CHANGE_DETECTION.value]

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute change detection."""
        # TODO: Implement change detection using rasterio
        # This will compare two temporal images and produce a change map
        return SpatialResult(
            spatial_context=SpatialContext(
                summary="Change detection (full implementation coming in Phase 1). "
                "Will compare satellite imagery across time periods to identify "
                "land use changes, new construction, deforestation, flooding, etc.",
            ),
        )
