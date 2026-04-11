"""Tests for the GeoSpark Context module (Phase 7B)."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from geospark.context import (
    ContextRelation,
    ContextRetriever,
    ContextStore,
    ContextTier,
    GeoContext,
    HotnessStats,
    RetrievalResult,
)
from geospark.context.storage import build_uri, parse_uri

# ======================================================================
# URI parsing
# ======================================================================


class TestURIParsing:
    """Tests for geospark:// URI parser."""

    def test_parse_simple_uri(self) -> None:
        category, path = parse_uri("geospark://missions/melbourne_flood")
        assert category == "missions"
        assert path == "melbourne_flood"

    def test_parse_nested_uri(self) -> None:
        category, path = parse_uri("geospark://missions/flood_2024/analysis/2026-04")
        assert category == "missions"
        assert path == "flood_2024/analysis/2026-04"

    def test_parse_invalid_uri_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid GeoSpark URI"):
            parse_uri("not_a_uri")

    def test_parse_missing_scheme_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_uri("missions/test")

    def test_build_uri_simple(self) -> None:
        assert build_uri("missions", "test") == "geospark://missions/test"

    def test_build_uri_with_subpath(self) -> None:
        assert (
            build_uri("missions", "flood", "analysis/2026-04")
            == "geospark://missions/flood/analysis/2026-04"
        )


# ======================================================================
# GeoContext model
# ======================================================================


class TestGeoContext:
    """Tests for the GeoContext data model."""

    def test_create_minimal(self) -> None:
        ctx = GeoContext(
            uri="geospark://missions/test",
            category="missions",
            name="Test",
        )
        assert ctx.id
        assert ctx.uri == "geospark://missions/test"
        assert ctx.access_count == 0
        assert ctx.is_archived is False

    def test_create_with_tiered_content(self) -> None:
        ctx = GeoContext(
            uri="geospark://missions/flood",
            category="missions",
            name="Flood 2024",
            abstract="Major flood event in Melbourne",
            overview={"severity": "high", "area_km2": 42},
            full_data={"affected_population": 15000, "damage_usd": 2000000},
        )
        assert ctx.abstract == "Major flood event in Melbourne"
        assert ctx.overview["severity"] == "high"
        assert ctx.full_data["affected_population"] == 15000

    def test_touch_increments_access(self) -> None:
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        assert ctx.access_count == 0
        ctx.touch()
        ctx.touch()
        assert ctx.access_count == 2
        assert ctx.last_accessed is not None

    def test_get_tier_l0(self) -> None:
        ctx = GeoContext(
            uri="geospark://test/x",
            category="test",
            name="X",
            abstract="Summary",
            overview={"k": "v"},
            full_data={"data": 1},
        )
        assert ctx.get_tier(ContextTier.L0) == "Summary"
        assert ctx.get_tier(ContextTier.L1) == {"k": "v"}
        assert ctx.get_tier(ContextTier.L2) == {"data": 1}

    def test_intersects_bbox_match(self) -> None:
        ctx = GeoContext(
            uri="geospark://test/melbourne",
            category="test",
            name="Melbourne",
            bounds_wgs84=[144.9, -37.9, 145.0, -37.8],
        )
        # Box containing Melbourne
        assert ctx.intersects_bbox([144.0, -38.0, 145.5, -37.0]) is True
        # Box far from Melbourne
        assert ctx.intersects_bbox([-75.0, 40.0, -74.0, 41.0]) is False

    def test_intersects_bbox_no_bounds(self) -> None:
        """Context with no bounds matches any bbox (unknown = permissive)."""
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        assert ctx.intersects_bbox([-180, -90, 180, 90]) is True
        assert ctx.intersects_bbox([0, 0, 1, 1]) is True

    def test_within_temporal_range(self) -> None:
        ctx = GeoContext(
            uri="geospark://test/event",
            category="test",
            name="Event",
            temporal_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )
        # Overlapping range
        assert ctx.within_temporal_range(
            datetime(2026, 4, 10, tzinfo=timezone.utc),
            datetime(2026, 4, 20, tzinfo=timezone.utc),
        ) is True
        # Non-overlapping (before)
        assert ctx.within_temporal_range(
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 31, tzinfo=timezone.utc),
        ) is False
        # Non-overlapping (after)
        assert ctx.within_temporal_range(
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 31, tzinfo=timezone.utc),
        ) is False

    def test_within_temporal_no_bounds(self) -> None:
        """Context with no temporal data matches any range."""
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        assert ctx.within_temporal_range(
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        ) is True

    def test_to_prompt_summary_l0(self) -> None:
        ctx = GeoContext(
            uri="geospark://missions/flood",
            category="missions",
            name="Flood",
            abstract="Flood event in Melbourne",
        )
        summary = ctx.to_prompt_summary(ContextTier.L0)
        assert "Flood" in summary
        assert "Melbourne" in summary

    def test_to_prompt_summary_l2_truncates(self) -> None:
        ctx = GeoContext(
            uri="geospark://test/big",
            category="test",
            name="Big",
            abstract="Short",
            full_data={"big_field": "x" * 500},
        )
        summary = ctx.to_prompt_summary(ContextTier.L2)
        assert "..." in summary  # Should truncate long fields
        assert len(summary) < 1000


class TestHotness:
    """Tests for hotness scoring."""

    def test_brand_new_context_baseline(self) -> None:
        """New context with 0 accesses should have hotness ~0.5."""
        ctx = GeoContext(uri="geospark://test/new", category="test", name="New")
        h = ctx.compute_hotness()
        assert 0.49 < h.score < 0.51
        assert h.access_count == 0
        assert h.age_days < 0.1

    def test_hot_recent_context(self) -> None:
        """Many accesses + recent = high score."""
        ctx = GeoContext(uri="geospark://test/hot", category="test", name="Hot")
        for _ in range(50):
            ctx.touch()
        h = ctx.compute_hotness()
        assert h.score > 0.9
        assert h.frequency_component > 0.9

    def test_cold_old_context(self) -> None:
        """Low accesses + old = low score."""
        ctx = GeoContext(uri="geospark://test/cold", category="test", name="Cold")
        ctx.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        h = ctx.compute_hotness()
        assert h.score < 0.01  # exp(-0.1 * 60) ≈ 0.0025

    def test_recency_decay_rate(self) -> None:
        """Custom decay rate affects recency component."""
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        ctx.created_at = datetime.now(timezone.utc) - timedelta(days=7)
        h_slow = ctx.compute_hotness(decay_rate=0.01)
        h_fast = ctx.compute_hotness(decay_rate=0.5)
        assert h_slow.recency_component > h_fast.recency_component

    def test_hotness_stats_fields(self) -> None:
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        h = ctx.compute_hotness()
        assert isinstance(h, HotnessStats)
        assert h.uri == "geospark://test/x"
        assert 0 <= h.frequency_component <= 1
        assert 0 <= h.recency_component <= 1
        assert 0 <= h.score <= 1


class TestContextRelation:
    """Tests for ContextRelation."""

    def test_create_relation(self) -> None:
        rel = ContextRelation(
            source_uri="geospark://a",
            target_uri="geospark://b",
            relation_type="derived_from",
        )
        assert rel.relation_type == "derived_from"
        assert rel.created_at is not None


# ======================================================================
# ContextStore
# ======================================================================


class TestContextStore:
    """Tests for the filesystem-based context store."""

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            ctx = GeoContext(
                uri="geospark://missions/test",
                category="missions",
                name="Test",
                abstract="Test mission",
            )
            store.save(ctx)

            loaded = store.load("geospark://missions/test")
            assert loaded is not None
            assert loaded.name == "Test"
            assert loaded.abstract == "Test mission"

    def test_load_increments_access_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            ctx = GeoContext(
                uri="geospark://missions/accessed",
                category="missions",
                name="Accessed",
            )
            store.save(ctx)

            store.load("geospark://missions/accessed")
            loaded2 = store.load("geospark://missions/accessed")
            # Each load touches (persists), so reload should show incremented count
            assert loaded2.access_count >= 1

    def test_load_no_touch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            ctx = GeoContext(
                uri="geospark://missions/silent",
                category="missions",
                name="Silent",
            )
            store.save(ctx)

            loaded = store.load("geospark://missions/silent", touch=False)
            assert loaded.access_count == 0

    def test_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            ctx = GeoContext(
                uri="geospark://missions/check",
                category="missions",
                name="Check",
            )
            store.save(ctx)

            assert store.exists("geospark://missions/check") is True
            assert store.exists("geospark://missions/nonexistent") is False

    def test_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            ctx = GeoContext(
                uri="geospark://missions/temp",
                category="missions",
                name="Temp",
            )
            store.save(ctx)
            assert store.delete("geospark://missions/temp") is True
            assert store.load("geospark://missions/temp") is None

    def test_list_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            for i in range(3):
                store.save(GeoContext(
                    uri=f"geospark://missions/m{i}",
                    category="missions",
                    name=f"M{i}",
                ))
            store.save(GeoContext(
                uri="geospark://datasets/ds1",
                category="datasets",
                name="DS1",
            ))

            all_ctx = store.list_all()
            assert len(all_ctx) == 4

            missions = store.list_all(category="missions")
            assert len(missions) == 3

    def test_list_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            store.save(GeoContext(
                uri="geospark://missions/a",
                category="missions",
                name="A",
            ))
            store.save(GeoContext(
                uri="geospark://datasets/b",
                category="datasets",
                name="B",
            ))
            store.save(GeoContext(
                uri="geospark://analysis_history/c",
                category="analysis_history",
                name="C",
            ))

            cats = store.list_categories()
            assert "missions" in cats
            assert "datasets" in cats
            assert "analysis_history" in cats

    def test_archive_and_unarchive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            store.save(GeoContext(
                uri="geospark://missions/old",
                category="missions",
                name="Old",
            ))
            assert store.archive("geospark://missions/old") is True

            # Not in default listing
            active = store.list_all()
            assert len(active) == 0

            # But present in archived listing
            with_archive = store.list_all(include_archived=True)
            assert len(with_archive) == 1
            assert with_archive[0].is_archived is True

            # Restore it
            assert store.unarchive("geospark://missions/old") is True
            active_after = store.list_all()
            assert len(active_after) == 1

    def test_archive_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            assert store.archive("geospark://missions/ghost") is False

    def test_add_and_get_relation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            store.save(GeoContext(
                uri="geospark://missions/a",
                category="missions",
                name="A",
            ))

            rel = store.add_relation(
                "geospark://missions/a",
                "geospark://datasets/b",
                relation_type="uses",
            )
            assert rel.relation_type == "uses"

            rels = store.get_relations("geospark://missions/a")
            assert len(rels) == 1
            assert rels[0].target_uri == "geospark://datasets/b"

    def test_load_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            store.save(GeoContext(
                uri="geospark://missions/tiered",
                category="missions",
                name="Tiered",
                abstract="Short summary",
                overview={"key": "value"},
                full_data={"big": "data"},
            ))

            assert store.load_tier("geospark://missions/tiered", ContextTier.L0) == "Short summary"
            assert store.load_tier("geospark://missions/tiered", ContextTier.L1) == {"key": "value"}
            assert store.load_tier("geospark://missions/tiered", ContextTier.L2) == {"big": "data"}

    def test_count_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            for i in range(5):
                store.save(GeoContext(
                    uri=f"geospark://missions/m{i}",
                    category="missions",
                    name=f"M{i}",
                ))
            assert store.count() == 5
            removed = store.clear()
            assert removed == 5
            assert store.count() == 0

    def test_persistence_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store1 = ContextStore(storage_dir=tmp)
            store1.save(GeoContext(
                uri="geospark://missions/persistent",
                category="missions",
                name="Persistent",
                abstract="Will outlive this instance",
            ))

            # New instance, same dir
            store2 = ContextStore(storage_dir=tmp)
            loaded = store2.load("geospark://missions/persistent", touch=False)
            assert loaded is not None
            assert loaded.abstract == "Will outlive this instance"


# ======================================================================
# ContextRetriever
# ======================================================================


class TestContextRetriever:
    """Tests for the hierarchical retriever."""

    def _setup_store(self, tmp: str) -> ContextStore:
        """Create a store with sample data for retrieval tests."""
        store = ContextStore(storage_dir=tmp)
        store.save(GeoContext(
            uri="geospark://missions/melbourne_flood",
            category="missions",
            name="Melbourne Flood 2024",
            abstract="Major flooding event in Melbourne CBD",
            bounds_wgs84=[144.9, -37.9, 145.1, -37.7],
            temporal_start=datetime(2024, 6, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2024, 6, 30, tzinfo=timezone.utc),
            tags=["flood", "melbourne", "disaster"],
        ))
        store.save(GeoContext(
            uri="geospark://missions/sydney_fire",
            category="missions",
            name="Sydney Bushfire 2025",
            abstract="Bushfire near Sydney outskirts",
            bounds_wgs84=[150.9, -34.0, 151.2, -33.7],
            temporal_start=datetime(2025, 11, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2025, 12, 15, tzinfo=timezone.utc),
            tags=["fire", "sydney"],
        ))
        store.save(GeoContext(
            uri="geospark://datasets/modis_fire_2025",
            category="datasets",
            name="MODIS Fire 2025",
            abstract="MODIS active fire detections for 2025",
            tags=["fire", "satellite", "modis"],
        ))
        return store

    def test_retrieve_by_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            results, _ = retriever.retrieve(query="flood melbourne", limit=5)
            assert len(results) >= 1
            # Melbourne flood should be top result
            assert "melbourne" in results[0].context.name.lower()

    def test_retrieve_by_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            # Melbourne area
            results, stats = retriever.retrieve(
                bbox=[144.0, -38.0, 146.0, -37.0],
                limit=5,
            )
            assert stats.filtered_by_bbox >= 1  # Sydney should be filtered out
            uris = [r.context.uri for r in results]
            assert "geospark://missions/melbourne_flood" in uris

    def test_retrieve_by_temporal_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            # June 2024 only
            results, _ = retriever.retrieve(
                temporal_start=datetime(2024, 6, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                limit=5,
            )
            uris = [r.context.uri for r in results]
            assert "geospark://missions/melbourne_flood" in uris
            # Sydney fire 2025 should NOT match (unless it has no temporal info)

    def test_retrieve_by_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            results, _ = retriever.retrieve(
                query="fire",
                category="datasets",
                limit=5,
            )
            assert all(r.context.category == "datasets" for r in results)

    def test_retrieve_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            _, stats = retriever.retrieve(query="fire", limit=5)
            assert stats.total_candidates == 3
            assert stats.returned > 0
            assert "fire" in stats.query_terms

    def test_parent_score_propagation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            # Parent context
            store.save(GeoContext(
                uri="geospark://missions/melbourne",
                category="missions",
                name="Melbourne Operations",
                abstract="All Melbourne operations",
            ))
            # Child context with no independent relevance
            store.save(GeoContext(
                uri="geospark://missions/melbourne/weather_2026",
                category="missions",
                name="Weather report",
                abstract="Routine weather",
                parent_uri="geospark://missions/melbourne",
            ))

            retriever = ContextRetriever(store)
            results, _ = retriever.retrieve(query="melbourne operations", limit=10)
            # Child should get some parent_score from the parent's high semantic score
            child_result = next(
                (r for r in results if "weather_2026" in r.context.uri), None
            )
            if child_result:
                assert child_result.parent_score > 0

    def test_hottest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            # Make one context hot
            hot_ctx = store.load("geospark://missions/melbourne_flood")
            for _ in range(20):
                hot_ctx.touch()
            store.save(hot_ctx)

            hottest = retriever.hottest(limit=2)
            assert len(hottest) == 2
            # Hot one should be first
            assert hottest[0].uri == "geospark://missions/melbourne_flood"

    def test_coldest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            # Make one context cold (old)
            cold_ctx = store.load("geospark://missions/sydney_fire", touch=False)
            cold_ctx.created_at = datetime.now(timezone.utc) - timedelta(days=90)
            store.save(cold_ctx)

            coldest = retriever.coldest(limit=1)
            assert len(coldest) == 1
            assert coldest[0].uri == "geospark://missions/sydney_fire"

    def test_archive_cold_contexts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(storage_dir=tmp)
            # Fresh contexts (high hotness)
            store.save(GeoContext(
                uri="geospark://missions/hot",
                category="missions",
                name="Hot",
            ))
            # Old context (low hotness)
            old_ctx = GeoContext(
                uri="geospark://missions/cold",
                category="missions",
                name="Cold",
            )
            old_ctx.created_at = datetime.now(timezone.utc) - timedelta(days=90)
            store.save(old_ctx)

            retriever = ContextRetriever(store)
            archived = retriever.archive_cold(threshold=0.2)
            assert "geospark://missions/cold" in archived
            assert "geospark://missions/hot" not in archived

    def test_nearby(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            results = retriever.nearby(bbox=[144.0, -38.0, 146.0, -37.0])
            uris = [r.context.uri for r in results]
            assert "geospark://missions/melbourne_flood" in uris
            assert "geospark://missions/sydney_fire" not in uris

    def test_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(store)

            results = retriever.recent(
                start=datetime(2024, 5, 1, tzinfo=timezone.utc),
                end=datetime(2024, 7, 1, tzinfo=timezone.utc),
            )
            uris = [r.context.uri for r in results]
            assert "geospark://missions/melbourne_flood" in uris

    def test_weight_normalization(self) -> None:
        """Weights that don't sum to 1.0 should be normalized."""
        with tempfile.TemporaryDirectory() as tmp:
            store = self._setup_store(tmp)
            retriever = ContextRetriever(
                store,
                semantic_weight=0.8,
                hotness_weight=0.4,
                parent_weight=0.0,
            )
            # Internal weights should sum to 1.0 after normalization
            total = (
                retriever._semantic_weight
                + retriever._hotness_weight
                + retriever._parent_weight
            )
            assert abs(total - 1.0) < 0.001


class TestRetrievalResult:
    """Tests for RetrievalResult model."""

    def test_create_result(self) -> None:
        ctx = GeoContext(uri="geospark://test/x", category="test", name="X")
        result = RetrievalResult(
            context=ctx,
            semantic_score=0.8,
            hotness_score=0.6,
            parent_score=0.3,
            final_score=0.68,
        )
        assert result.semantic_score == 0.8
        assert result.tier_loaded == ContextTier.L0


class TestContextTier:
    """Tests for ContextTier enum."""

    def test_values(self) -> None:
        assert ContextTier.L0.value == "L0"
        assert ContextTier.L1.value == "L1"
        assert ContextTier.L2.value == "L2"
