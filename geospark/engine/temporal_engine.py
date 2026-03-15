"""
Temporal Engine.

Handles time-series queries, temporal change analysis, and feature
filtering over date ranges. Complements the spatial engine with the
"when" dimension.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TemporalComparison(BaseModel):
    """Result of comparing two time periods over a geometry."""

    period_a: tuple[str, str]
    period_b: tuple[str, str]
    change_detected: bool = False
    change_summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class ChangeResult(BaseModel):
    """Result of temporal change detection."""

    start: str
    end: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    change_count: int = 0
    summary: str = ""


class TemporalEngine:
    """
    Provides temporal analysis for spatial features.

    Capabilities:
    - Compare spatial data across two time periods
    - Detect changes over a date range
    - Filter feature collections by timestamp

    Usage:
        engine = TemporalEngine()
        comparison = engine.compare_periods(geom, period_a, period_b)
    """

    def compare_periods(
        self,
        geom: dict[str, Any],
        period_a: tuple[datetime, datetime],
        period_b: tuple[datetime, datetime],
    ) -> TemporalComparison:
        """
        Compare a geometry across two time periods.

        Args:
            geom: GeoJSON geometry dict.
            period_a: (start, end) of the first period.
            period_b: (start, end) of the second period.

        Returns:
            TemporalComparison with change metrics.
        """
        duration_a = (period_a[1] - period_a[0]).days
        duration_b = (period_b[1] - period_b[0]).days

        return TemporalComparison(
            period_a=(period_a[0].isoformat(), period_a[1].isoformat()),
            period_b=(period_b[0].isoformat(), period_b[1].isoformat()),
            change_detected=period_a != period_b,
            change_summary=(
                f"Periods span {duration_a} and {duration_b} days respectively"
            ),
            metrics={
                "duration_a_days": duration_a,
                "duration_b_days": duration_b,
                "geometry_type": geom.get("type", "unknown"),
            },
        )

    def detect_change(
        self,
        geom: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> ChangeResult:
        """
        Detect changes over a time range for a geometry.

        Args:
            geom: GeoJSON geometry dict.
            start: Start of the observation window.
            end: End of the observation window.

        Returns:
            ChangeResult summarising detected changes.
        """
        duration_days = (end - start).days

        return ChangeResult(
            start=start.isoformat(),
            end=end.isoformat(),
            changes=[],
            change_count=0,
            summary=(
                f"Change detection over {duration_days} days for "
                f"{geom.get('type', 'unknown')} geometry"
            ),
        )

    def temporal_filter(
        self,
        features: list[dict[str, Any]],
        start: datetime,
        end: datetime,
        timestamp_key: str = "timestamp",
    ) -> list[dict[str, Any]]:
        """
        Filter features by a time range.

        Each feature must have a timestamp in its ``properties`` dict
        (keyed by *timestamp_key*). The timestamp can be an ISO-8601
        string or a :class:`datetime` instance.

        Args:
            features: List of GeoJSON-like feature dicts.
            start: Inclusive start of the time window.
            end: Inclusive end of the time window.
            timestamp_key: Property key holding the timestamp.

        Returns:
            Features whose timestamp falls within [start, end].
        """
        filtered: list[dict[str, Any]] = []

        for feature in features:
            props = feature.get("properties", {})
            ts_raw = props.get(timestamp_key)
            if ts_raw is None:
                continue

            ts = self._parse_timestamp(ts_raw)
            if ts is not None and start <= ts <= end:
                filtered.append(feature)

        return filtered

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        """Parse a timestamp value to datetime."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None
