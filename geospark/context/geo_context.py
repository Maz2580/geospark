"""GeoContext data models — tiered spatial context with hierarchical URIs."""
from __future__ import annotations

import enum
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ContextTier(str, enum.Enum):
    """Loading tier for a context — controls what gets pulled into memory.

    L0: abstract — 1-2 sentence summary, always loaded for planning
    L1: overview — structured outline with key fields, loaded for context
    L2: full — complete data, loaded only for detailed analysis
    """

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class ContextRelation(BaseModel):
    """A typed link between two contexts."""

    source_uri: str
    target_uri: str
    relation_type: str = "related"  # related, parent, child, references, derived_from
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HotnessStats(BaseModel):
    """Computed hotness score and components for a context."""

    uri: str
    access_count: int = 0
    age_days: float = 0.0
    frequency_component: float = 0.0  # sigmoid(log1p(access_count))
    recency_component: float = 0.0  # exp(-decay * age_days)
    score: float = 0.0  # combined score in [0, 1]


class GeoContext(BaseModel):
    """A geospatial context record with tiered content and metadata.

    The URI follows the pattern: geospark://<category>/<name>[/<subpath>]
    Examples:
    - geospark://missions/melbourne_flood_2024
    - geospark://datasets/modis_fire_2026_04
    - geospark://analysis/air_quality_delhi_2026_04_09
    """

    # Identity
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    uri: str  # geospark://<category>/<name>[/<subpath>]
    category: str  # missions, datasets, analysis_history, etc.
    name: str  # short human-readable name

    # Tiered content
    abstract: str = ""  # L0: 1-2 sentence summary
    overview: dict[str, Any] = Field(default_factory=dict)  # L1: structured outline
    full_data: dict[str, Any] = Field(default_factory=dict)  # L2: complete data

    # Hierarchy
    parent_uri: str | None = None  # Parent context URI, None for root
    child_uris: list[str] = Field(default_factory=list)

    # Spatial and temporal metadata
    bounds_wgs84: list[float] | None = None  # [min_lon, min_lat, max_lon, max_lat]
    temporal_start: datetime | None = None
    temporal_end: datetime | None = None

    # Tracking
    tags: list[str] = Field(default_factory=list)
    access_count: int = 0
    last_accessed: datetime | None = None
    is_archived: bool = False

    # Provenance
    source: str = ""  # Where this context came from (tool, user, agent, flow)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        """Record an access — updates count and timestamp."""
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc)

    def compute_hotness(
        self,
        decay_rate: float = 0.1,
        now: datetime | None = None,
    ) -> HotnessStats:
        """Compute hotness score: sigmoid(log1p(count)) * exp(-decay * age_days).

        Args:
            decay_rate: exponential decay rate per day (default 0.1 = half-life ~7 days)
            now: reference time for age calculation (defaults to current UTC)

        Returns:
            HotnessStats with component and combined scores in [0, 1]
        """
        now = now or datetime.now(timezone.utc)
        ref_time = self.last_accessed or self.created_at
        age_days = max(0.0, (now - ref_time).total_seconds() / 86400)

        # Frequency: sigmoid(log1p(count)). For count=0, returns 0.5 (neutral),
        # approaching 1.0 as count grows. log1p dampens high counts.
        log_count = math.log1p(self.access_count)
        frequency = 1.0 / (1.0 + math.exp(-log_count))

        # Recency: exponential decay from last access/creation
        recency = math.exp(-decay_rate * age_days)

        # Combined: product means both matter; a brand-new context has
        # score = 0.5 * 1.0 = 0.5, a hot recent one approaches 1.0.
        score = frequency * recency

        return HotnessStats(
            uri=self.uri,
            access_count=self.access_count,
            age_days=round(age_days, 3),
            frequency_component=round(frequency, 4),
            recency_component=round(recency, 4),
            score=round(score, 4),
        )

    def intersects_bbox(self, bbox: list[float]) -> bool:
        """Check if this context's bounds intersect a bounding box.

        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]

        Returns:
            True if bounds intersect or self has no bounds (returns True for unknown).
        """
        if self.bounds_wgs84 is None:
            return True  # No bounds = match anything
        a_min_lon, a_min_lat, a_max_lon, a_max_lat = self.bounds_wgs84
        b_min_lon, b_min_lat, b_max_lon, b_max_lat = bbox
        return not (
            a_max_lon < b_min_lon
            or a_min_lon > b_max_lon
            or a_max_lat < b_min_lat
            or a_min_lat > b_max_lat
        )

    def within_temporal_range(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> bool:
        """Check if this context's temporal range overlaps a query range.

        Returns True if no temporal metadata (unknown = match).
        """
        if self.temporal_start is None and self.temporal_end is None:
            return True  # No temporal data = match anything

        ctx_start = self.temporal_start or self.temporal_end
        ctx_end = self.temporal_end or self.temporal_start

        if start is not None and ctx_end is not None and ctx_end < start:
            return False
        return not (end is not None and ctx_start is not None and ctx_start > end)

    def get_tier(self, tier: ContextTier) -> Any:
        """Get content at a specific tier.

        L0 returns the abstract string, L1 returns the overview dict,
        L2 returns the full_data dict.
        """
        if tier == ContextTier.L0:
            return self.abstract
        if tier == ContextTier.L1:
            return self.overview
        return self.full_data

    def to_prompt_summary(self, tier: ContextTier = ContextTier.L0) -> str:
        """Convert to a compact string suitable for LLM prompts.

        L0 returns just the abstract, L1 adds key/value overview,
        L2 adds the full data dump.
        """
        header = f"[{self.uri}] {self.name}"
        if tier == ContextTier.L0:
            return f"{header}: {self.abstract}"

        lines = [f"{header}", f"Abstract: {self.abstract}"]
        if tier == ContextTier.L1 and self.overview:
            lines.append("Overview:")
            for k, v in self.overview.items():
                lines.append(f"  {k}: {v}")
        elif tier == ContextTier.L2:
            if self.overview:
                lines.append("Overview:")
                for k, v in self.overview.items():
                    lines.append(f"  {k}: {v}")
            if self.full_data:
                lines.append("Full data:")
                for k, v in self.full_data.items():
                    v_str = str(v)
                    if len(v_str) > 200:
                        v_str = v_str[:197] + "..."
                    lines.append(f"  {k}: {v_str}")
        return "\n".join(lines)
