"""
Temporal Engine.

Handles time-series queries, temporal change analysis, and feature
filtering over date ranges. Complements the spatial engine with the
"when" dimension.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

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

        Computes overlap, gap, and duration metrics between periods.

        Args:
            geom: GeoJSON geometry dict.
            period_a: (start, end) of the first period.
            period_b: (start, end) of the second period.

        Returns:
            TemporalComparison with change metrics.
        """
        duration_a = (period_a[1] - period_a[0]).days
        duration_b = (period_b[1] - period_b[0]).days

        # Calculate overlap and gap
        overlap_start = max(period_a[0], period_b[0])
        overlap_end = min(period_a[1], period_b[1])
        overlap_days = max(0, (overlap_end - overlap_start).days)

        gap_days = 0
        if overlap_days == 0:
            earlier_end = min(period_a[1], period_b[1])
            later_start = max(period_a[0], period_b[0])
            gap_days = (later_start - earlier_end).days

        # Temporal separation suggests potential change
        change_detected = gap_days > 0 or (overlap_days == 0 and period_a != period_b)

        parts = []
        if overlap_days > 0:
            parts.append(f"{overlap_days}-day overlap")
        if gap_days > 0:
            parts.append(f"{gap_days}-day gap between periods")
        parts.append(f"durations: {duration_a}d vs {duration_b}d")

        return TemporalComparison(
            period_a=(period_a[0].isoformat(), period_a[1].isoformat()),
            period_b=(period_b[0].isoformat(), period_b[1].isoformat()),
            change_detected=change_detected,
            change_summary="; ".join(parts),
            metrics={
                "duration_a_days": duration_a,
                "duration_b_days": duration_b,
                "overlap_days": overlap_days,
                "gap_days": gap_days,
                "duration_ratio": round(duration_b / duration_a, 2) if duration_a else 0,
                "geometry_type": geom.get("type", "unknown"),
            },
        )

    # Expected change types by observation window length
    _CHANGE_CATEGORIES: ClassVar[dict[str, list[dict[str, str]]]] = {
        "short": [
            {"type": "construction_activity", "likelihood": "high"},
            {"type": "vegetation_phenology", "likelihood": "medium"},
            {"type": "weather_event_damage", "likelihood": "low"},
        ],
        "medium": [
            {"type": "seasonal_vegetation_change", "likelihood": "high"},
            {"type": "construction_progress", "likelihood": "high"},
            {"type": "agricultural_crop_cycle", "likelihood": "medium"},
            {"type": "water_level_change", "likelihood": "medium"},
        ],
        "long": [
            {"type": "land_use_change", "likelihood": "high"},
            {"type": "urban_growth", "likelihood": "high"},
            {"type": "deforestation", "likelihood": "medium"},
            {"type": "coastline_erosion", "likelihood": "medium"},
            {"type": "infrastructure_development", "likelihood": "medium"},
        ],
    }

    def detect_change(
        self,
        geom: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> ChangeResult:
        """
        Detect expected change types over a time range for a geometry.

        Categorises the observation window and identifies likely change
        types based on duration and geometry type.

        Args:
            geom: GeoJSON geometry dict.
            start: Start of the observation window.
            end: End of the observation window.

        Returns:
            ChangeResult with expected change types and analysis metadata.
        """
        duration_days = (end - start).days

        if duration_days < 30:
            category = "short"
        elif duration_days < 180:
            category = "medium"
        else:
            category = "long"

        changes = [
            {**c, "observation_window": category, "duration_days": duration_days}
            for c in self._CHANGE_CATEGORIES[category]
        ]

        return ChangeResult(
            start=start.isoformat(),
            end=end.isoformat(),
            changes=changes,
            change_count=len(changes),
            summary=(
                f"{category.capitalize()} observation window ({duration_days} days) "
                f"for {geom.get('type', 'unknown')} geometry — "
                f"{len(changes)} potential change types identified"
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

    def compute_trends(
        self,
        values: list[dict[str, Any]],
        timestamp_key: str = "timestamp",
        value_key: str = "value",
    ) -> dict[str, Any]:
        """
        Compute trend statistics from timestamped values.

        Sorts by timestamp, computes min/max/mean, and determines
        trend direction via simple linear slope.

        Args:
            values: List of dicts with timestamp and value keys.
            timestamp_key: Key for the timestamp in each dict.
            value_key: Key for the numeric value in each dict.

        Returns:
            Dict with statistics and trend direction.
        """
        if not values:
            return {"error": "No values provided", "count": 0}

        # Parse and sort by timestamp
        parsed: list[tuple[datetime, float]] = []
        for entry in values:
            ts = self._parse_timestamp(entry.get(timestamp_key))
            val = entry.get(value_key)
            if ts is not None and val is not None:
                parsed.append((ts, float(val)))

        if not parsed:
            return {"error": "No valid timestamp-value pairs found", "count": 0}

        parsed.sort(key=lambda x: x[0])
        nums = [v for _, v in parsed]

        mean_val = sum(nums) / len(nums)
        min_val = min(nums)
        max_val = max(nums)

        # Trend direction: slope from first to last over time span
        time_span_days = (parsed[-1][0] - parsed[0][0]).days
        if time_span_days > 0 and len(nums) >= 2:
            slope = (nums[-1] - nums[0]) / time_span_days
            if abs(slope) < (max_val - min_val) * 0.01:
                direction = "stable"
            elif slope > 0:
                direction = "increasing"
            else:
                direction = "decreasing"
        else:
            slope = 0.0
            direction = "stable"

        return {
            "count": len(nums),
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "mean": round(mean_val, 4),
            "first": round(nums[0], 4),
            "last": round(nums[-1], 4),
            "slope_per_day": round(slope, 6),
            "direction": direction,
            "time_span_days": time_span_days,
            "start": parsed[0][0].isoformat(),
            "end": parsed[-1][0].isoformat(),
        }

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
