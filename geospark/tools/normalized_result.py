"""Normalized tool result shape — consistent output from all tools.

Every tool returns this shape so LLMs can interpret results without
custom parsing logic. Pattern from chat2geo/Arion analysis.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResultStatistics(BaseModel):
    """Statistical summary of numeric results."""

    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None
    count: int = 0
    percentiles: dict[str, float] = {}  # e.g., {"p25": 0.3, "p50": 0.5, "p75": 0.7}


class NormalizedResult(BaseModel):
    """Normalized result shape for all GeoSpark tools.

    Every tool should return this shape for consistent LLM interpretation.
    Fields:
        status: "success" or "error"
        tool: Tool name that produced this result
        data: The actual result data (tool-specific)
        bounds_wgs84: Bounding box in WGS84 [minx, miny, maxx, maxy]
        crs: Coordinate reference system
        statistics: Numeric statistics if applicable
        metadata: Additional context
        suggestion: Next analysis the LLM might consider
        errors: Error messages if any
    """

    status: str = "success"
    tool: str = ""
    data: dict[str, Any] = {}
    bounds_wgs84: list[float] | None = None  # [minx, miny, maxx, maxy]
    crs: str = "EPSG:4326"
    statistics: ResultStatistics | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    suggestion: str | None = None
    errors: list[str] = []

    @classmethod
    def success(
        cls,
        tool: str,
        data: dict[str, Any],
        bounds_wgs84: list[float] | None = None,
        statistics: ResultStatistics | None = None,
        metadata: dict[str, Any] | None = None,
        suggestion: str | None = None,
    ) -> NormalizedResult:
        """Create a successful result."""
        return cls(
            status="success",
            tool=tool,
            data=data,
            bounds_wgs84=bounds_wgs84,
            statistics=statistics,
            metadata=metadata or {},
            suggestion=suggestion,
        )

    @classmethod
    def error(
        cls,
        tool: str,
        message: str,
        suggestion: str | None = None,
    ) -> NormalizedResult:
        """Create an error result."""
        return cls(
            status="error",
            tool=tool,
            errors=[message],
            suggestion=suggestion or "Check parameters and try again.",
        )

    @property
    def is_success(self) -> bool:
        """Whether the result was successful."""
        return self.status == "success"

    def add_description(self, description: str) -> None:
        """Add an interpretive description to metadata."""
        self.metadata["description"] = description

    def add_data_source(self, source: str) -> None:
        """Add data source to metadata."""
        self.metadata["data_source"] = source
