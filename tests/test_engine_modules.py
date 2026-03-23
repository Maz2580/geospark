"""Tests for Phase 2F engine modules: Planner, Temporal, Aggregator, Cache."""

import time
from datetime import datetime

import pytest

from geospark.engine.aggregator import SpatialAggregator
from geospark.engine.cache import SpatialCache
from geospark.engine.planner import PlannedStep, QueryPlanner
from geospark.engine.temporal_engine import (
    ChangeResult,
    TemporalComparison,
    TemporalEngine,
)
from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery

# ---------------------------------------------------------------------------
# QueryPlanner
# ---------------------------------------------------------------------------


class TestQueryPlanner:
    def test_plan_single_step(self):
        """A simple query produces a single PlannedStep."""
        planner = QueryPlanner()
        query = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(51.5074, -0.1278),
            radius_m=1000,
        )
        steps = planner.plan(query)
        assert len(steps) == 1
        assert steps[0].operation == SpatialOperation.BUFFER
        assert steps[0].depends_on == []

    def test_plan_chain(self):
        """A query with chain metadata produces multiple linked steps."""
        planner = QueryPlanner()
        query = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(51.5074, -0.1278),
            metadata={
                "chain": [
                    {"operation": "buffer"},
                    {"operation": "centroid"},
                    {"operation": "area"},
                ]
            },
        )
        steps = planner.plan(query)
        assert len(steps) == 3
        assert steps[0].depends_on == []
        assert steps[1].depends_on == [steps[0].id]
        assert steps[2].depends_on == [steps[1].id]

    def test_optimize_dedup(self):
        """Optimize removes consecutive duplicate operations."""
        planner = QueryPlanner()
        query = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(0, 0),
        )
        steps = [
            PlannedStep(operation=SpatialOperation.BUFFER, query=query),
            PlannedStep(operation=SpatialOperation.BUFFER, query=query),
            PlannedStep(operation=SpatialOperation.CENTROID, query=query),
        ]
        optimized = planner.optimize(steps)
        ops = [s.operation for s in optimized]
        assert ops == [SpatialOperation.BUFFER, SpatialOperation.CENTROID]

    def test_optimize_single_step(self):
        """Optimize on a single step returns it unchanged."""
        planner = QueryPlanner()
        query = SpatialQuery(
            operation=SpatialOperation.AREA,
            geometry=Point.from_latlon(0, 0),
        )
        steps = [PlannedStep(operation=SpatialOperation.AREA, query=query)]
        assert planner.optimize(steps) == steps

    def test_planned_step_has_id(self):
        """Every PlannedStep gets a unique ID."""
        query = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(0, 0),
        )
        a = PlannedStep(operation=SpatialOperation.BUFFER, query=query)
        b = PlannedStep(operation=SpatialOperation.BUFFER, query=query)
        assert a.id != b.id


# ---------------------------------------------------------------------------
# TemporalEngine
# ---------------------------------------------------------------------------


class TestTemporalEngine:
    def test_compare_periods(self):
        """compare_periods returns a valid TemporalComparison."""
        engine = TemporalEngine()
        geom = {"type": "Point", "coordinates": [0, 0]}
        result = engine.compare_periods(
            geom,
            (datetime(2020, 1, 1), datetime(2020, 6, 30)),
            (datetime(2023, 1, 1), datetime(2023, 6, 30)),
        )
        assert isinstance(result, TemporalComparison)
        assert result.change_detected is True
        assert result.metrics["duration_a_days"] == 181
        assert result.metrics["geometry_type"] == "Point"

    def test_compare_identical_periods(self):
        """Identical periods report no change."""
        engine = TemporalEngine()
        geom = {"type": "Point", "coordinates": [10, 20]}
        period = (datetime(2022, 1, 1), datetime(2022, 12, 31))
        result = engine.compare_periods(geom, period, period)
        assert result.change_detected is False

    def test_detect_change(self):
        """detect_change returns a ChangeResult with expected change types."""
        engine = TemporalEngine()
        geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        result = engine.detect_change(geom, datetime(2020, 1, 1), datetime(2021, 1, 1))
        assert isinstance(result, ChangeResult)
        assert result.change_count > 0  # Long window identifies potential changes
        assert "366 days" in result.summary  # 2020 is a leap year
        assert all("type" in c for c in result.changes)

    def test_temporal_filter(self):
        """temporal_filter keeps only features within the window."""
        engine = TemporalEngine()
        features = [
            {"geometry": {"type": "Point", "coordinates": [0, 0]},
             "properties": {"timestamp": "2022-06-15T00:00:00"}},
            {"geometry": {"type": "Point", "coordinates": [1, 1]},
             "properties": {"timestamp": "2023-03-01T00:00:00"}},
            {"geometry": {"type": "Point", "coordinates": [2, 2]},
             "properties": {"timestamp": "2021-01-01T00:00:00"}},
        ]
        filtered = engine.temporal_filter(
            features, datetime(2022, 1, 1), datetime(2022, 12, 31)
        )
        assert len(filtered) == 1
        assert filtered[0]["geometry"]["coordinates"] == [0, 0]

    def test_temporal_filter_datetime_values(self):
        """temporal_filter works with datetime objects in properties."""
        engine = TemporalEngine()
        features = [
            {"geometry": {"type": "Point", "coordinates": [5, 5]},
             "properties": {"timestamp": datetime(2022, 7, 1)}},
        ]
        filtered = engine.temporal_filter(
            features, datetime(2022, 1, 1), datetime(2022, 12, 31)
        )
        assert len(filtered) == 1

    def test_temporal_filter_no_timestamp(self):
        """Features without a timestamp are excluded."""
        engine = TemporalEngine()
        features = [
            {"geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
        ]
        filtered = engine.temporal_filter(
            features, datetime(2020, 1, 1), datetime(2025, 1, 1)
        )
        assert len(filtered) == 0


# ---------------------------------------------------------------------------
# SpatialAggregator
# ---------------------------------------------------------------------------


class TestSpatialAggregator:
    def test_zonal_stats_basic(self):
        """Zonal stats on known values produce correct results."""
        agg = SpatialAggregator()
        geom = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        stats = agg.zonal_stats(geom, [1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats.min == 1.0
        assert stats.max == 5.0
        assert stats.mean == 3.0
        assert stats.count == 5
        assert abs(stats.std - 1.4142135623730951) < 1e-6
        assert "p50" in stats.percentiles
        assert stats.percentiles["p50"] == 3.0

    def test_zonal_stats_single_value(self):
        """Zonal stats with one value."""
        agg = SpatialAggregator()
        geom = {"type": "Point", "coordinates": [0, 0]}
        stats = agg.zonal_stats(geom, [42.0])
        assert stats.min == 42.0
        assert stats.max == 42.0
        assert stats.mean == 42.0
        assert stats.std == 0.0
        assert stats.count == 1

    def test_zonal_stats_empty_raises(self):
        """Empty values list raises ValueError."""
        agg = SpatialAggregator()
        with pytest.raises(ValueError, match="empty"):
            agg.zonal_stats({"type": "Point", "coordinates": [0, 0]}, [])

    def test_spatial_join_intersects(self):
        """Spatial join finds intersecting features."""
        agg = SpatialAggregator()
        poly = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
            "properties": {"name": "zone"},
        }
        point_inside = {
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"id": "A"},
        }
        point_outside = {
            "geometry": {"type": "Point", "coordinates": [10, 10]},
            "properties": {"id": "B"},
        }
        joined = agg.spatial_join([point_inside, point_outside], [poly], "intersects")
        assert len(joined) == 1
        assert joined[0]["properties"]["id"] == "A"
        assert joined[0]["properties"]["name"] == "zone"

    def test_spatial_join_invalid_predicate(self):
        """Invalid predicate raises ValueError."""
        agg = SpatialAggregator()
        with pytest.raises(ValueError, match="Unsupported predicate"):
            agg.spatial_join([], [], predicate="near")

    def test_aggregate_by_hex_import_error(self):
        """aggregate_by_hex raises ImportError when h3 is not installed."""
        agg = SpatialAggregator()
        # h3 may or may not be installed; if not, expect ImportError
        try:
            import h3  # noqa: F401
            pytest.skip("h3 is installed; cannot test ImportError path")
        except ImportError:
            with pytest.raises(ImportError, match="h3"):
                agg.aggregate_by_hex([{"geometry": {"type": "Point", "coordinates": [0, 0]}}])


# ---------------------------------------------------------------------------
# SpatialCache
# ---------------------------------------------------------------------------


class TestSpatialCache:
    def test_set_and_get(self):
        """Values can be stored and retrieved."""
        cache = SpatialCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_key(self):
        """Missing keys return None."""
        cache = SpatialCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiration(self):
        """Expired entries return None."""
        cache = SpatialCache()
        cache.set("ephemeral", "data", ttl=0)
        # Sleep just enough for time.time() to advance past expiry
        time.sleep(0.01)
        assert cache.get("ephemeral") is None

    def test_lru_eviction(self):
        """LRU eviction removes oldest entries."""
        cache = SpatialCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_stats(self):
        """Stats track hits and misses."""
        cache = SpatialCache()
        cache.set("x", 10)
        cache.get("x")       # hit
        cache.get("missing")  # miss

        s = cache.stats()
        assert s["hits"] == 1
        assert s["misses"] == 1
        assert s["size"] == 1

    def test_make_key_deterministic(self):
        """Same query always produces the same key."""
        cache = SpatialCache()
        query = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(51.5074, -0.1278),
            radius_m=1000,
        )
        key1 = cache.make_key(query)
        key2 = cache.make_key(query)
        assert key1 == key2
        assert len(key1) == 16

    def test_make_key_varies_with_query(self):
        """Different queries produce different keys."""
        cache = SpatialCache()
        q1 = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(0, 0),
            radius_m=1000,
        )
        q2 = SpatialQuery(
            operation=SpatialOperation.CENTROID,
            geometry=Point.from_latlon(0, 0),
        )
        assert cache.make_key(q1) != cache.make_key(q2)

    def test_invalidate(self):
        """Invalidate removes matching keys."""
        cache = SpatialCache()
        cache.set("geo_buffer_001", "a")
        cache.set("geo_buffer_002", "b")
        cache.set("geo_distance_001", "c")
        removed = cache.invalidate(r"geo_buffer")
        assert removed == 2
        assert cache.get("geo_buffer_001") is None
        assert cache.get("geo_distance_001") == "c"

    def test_overwrite_existing(self):
        """Setting an existing key updates the value."""
        cache = SpatialCache()
        cache.set("k", "old")
        cache.set("k", "new")
        assert cache.get("k") == "new"
        assert cache.stats()["size"] == 1
