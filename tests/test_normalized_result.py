"""Tests for normalized tool result shape."""
from __future__ import annotations

from geospark.tools.normalized_result import NormalizedResult, ResultStatistics


class TestNormalizedResult:
    def test_success(self) -> None:
        result = NormalizedResult.success(
            tool="geocode",
            data={"name": "Eiffel Tower", "coordinates": [2.2945, 48.8584]},
            bounds_wgs84=[2.2945, 48.8584, 2.2945, 48.8584],
        )
        assert result.is_success
        assert result.tool == "geocode"
        assert result.crs == "EPSG:4326"

    def test_error(self) -> None:
        result = NormalizedResult.error(
            tool="geocode",
            message="Location not found",
            suggestion="Try a more specific name.",
        )
        assert not result.is_success
        assert "Location not found" in result.errors

    def test_with_statistics(self) -> None:
        stats = ResultStatistics(
            min=0.1, max=0.9, mean=0.5, std=0.2, count=100,
            percentiles={"p25": 0.3, "p50": 0.5, "p75": 0.7},
        )
        result = NormalizedResult.success(
            tool="ndvi",
            data={"index": "NDVI"},
            statistics=stats,
        )
        assert result.statistics is not None
        assert result.statistics.mean == 0.5

    def test_add_description(self) -> None:
        result = NormalizedResult.success(tool="ndvi", data={})
        result.add_description("NDVI ranges -1 to 1. Values above 0.3 indicate healthy vegetation.")
        assert "description" in result.metadata

    def test_add_data_source(self) -> None:
        result = NormalizedResult.success(tool="elevation", data={})
        result.add_data_source("SRTM 30m")
        assert result.metadata["data_source"] == "SRTM 30m"
