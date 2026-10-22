"""
Pixel-Level Change Detection Tool.

Detects changes between satellite images from different time periods.
"""

from __future__ import annotations

from typing import ClassVar

from geospark.protocol.schema import (
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.tools.base import BaseTool, not_implemented


class PixelChangeTool(BaseTool):
    """Detect pixel-level changes between temporal satellite images."""

    name = "change_detection"
    description = "Detect changes between satellite images from different time periods"
    supported_operations: ClassVar[list[str]] = [SpatialOperation.CHANGE_DETECTION.value]

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute change detection."""
        return not_implemented("Change detection")
