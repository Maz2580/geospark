"""GeoSpark Engine - The spatial reasoning core."""

from geospark.engine.aggregator import SpatialAggregator, ZonalStats
from geospark.engine.cache import SpatialCache
from geospark.engine.core import Engine
from geospark.engine.planner import PlannedStep, QueryPlanner
from geospark.engine.temporal_engine import (
    ChangeResult,
    TemporalComparison,
    TemporalEngine,
)

__all__ = [
    "Engine",
    "QueryPlanner",
    "PlannedStep",
    "TemporalEngine",
    "TemporalComparison",
    "ChangeResult",
    "SpatialAggregator",
    "ZonalStats",
    "SpatialCache",
]
