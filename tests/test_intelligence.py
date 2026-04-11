"""Tests for the GeoSpark spatial intelligence module (Phase 7A)."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from geospark.memory.intelligence import (
    Contradiction,
    IntelligenceStats,
    MemoryAction,
    MemoryConnection,
    SpatialEpisode,
    SpatialFact,
    SpatialIntelligence,
    _word_overlap_score,
)
from geospark.memory.vector_store import VectorStore, _cosine_similarity

# ======================================================================
# VectorStore tests
# ======================================================================


class TestVectorStore:
    """Tests for the VectorStore."""

    def test_create_empty(self) -> None:
        store = VectorStore()
        assert store.count == 0
        assert store.dimension == 0

    def test_add_and_count(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("b", [0.0, 1.0, 0.0])
        assert store.count == 2

    def test_auto_dimension(self) -> None:
        store = VectorStore()
        store.add("a", [1.0, 2.0, 3.0])
        assert store.dimension == 3

    def test_dimension_mismatch_raises(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        with pytest.raises(ValueError, match="dimension"):
            store.add("b", [1.0, 0.0])

    def test_search_empty(self) -> None:
        store = VectorStore(dimension=3)
        results = store.search([1.0, 0.0, 0.0])
        assert results == []

    def test_search_finds_similar(self) -> None:
        store = VectorStore(dimension=3)
        store.add("x_axis", [1.0, 0.0, 0.0])
        store.add("y_axis", [0.0, 1.0, 0.0])
        store.add("near_x", [0.9, 0.1, 0.0])

        results = store.search([1.0, 0.0, 0.0], top_k=2)
        assert len(results) >= 1
        # x_axis should be the top match
        assert results[0][0] == "x_axis"
        assert results[0][1] > 0.9

    def test_search_with_threshold(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("b", [0.0, 1.0, 0.0])

        # High threshold should exclude orthogonal vectors
        results = store.search([1.0, 0.0, 0.0], threshold=0.5)
        ids = [r[0] for r in results]
        assert "a" in ids
        assert "b" not in ids

    def test_remove(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("b", [0.0, 1.0, 0.0])
        assert store.remove("a") is True
        assert store.count == 1
        assert store.remove("nonexistent") is False

    def test_remove_updates_search(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("b", [0.0, 1.0, 0.0])
        store.remove("a")
        results = store.search([1.0, 0.0, 0.0], top_k=5)
        ids = [r[0] for r in results]
        assert "a" not in ids

    def test_get_vector(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 2.0, 3.0])
        vec = store.get_vector("a")
        assert vec is not None
        assert float(vec[0]) == pytest.approx(1.0)
        assert store.get_vector("nonexistent") is None

    def test_replace_existing_id(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("a", [0.0, 1.0, 0.0])
        assert store.count == 1
        vec = store.get_vector("a")
        assert float(vec[1]) == pytest.approx(1.0)

    def test_clear(self) -> None:
        store = VectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0])
        store.add("b", [0.0, 1.0, 0.0])
        removed = store.clear()
        assert removed == 2
        assert store.count == 0

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/test_store"

            # Save
            store1 = VectorStore(dimension=3, storage_path=path)
            store1.add("a", [1.0, 0.0, 0.0])
            store1.add("b", [0.0, 1.0, 0.0])
            store1.save()

            # Reload
            store2 = VectorStore(dimension=0, storage_path=path)
            assert store2.count == 2
            assert store2.dimension == 3
            results = store2.search([1.0, 0.0, 0.0], top_k=1)
            assert results[0][0] == "a"


class TestCosineSimility:
    """Tests for cosine similarity helper."""

    def test_identical_vectors(self) -> None:
        a = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(a, b) == 0.0


# ======================================================================
# Data model tests
# ======================================================================


class TestSpatialFact:
    """Tests for SpatialFact model."""

    def test_create_fact(self) -> None:
        fact = SpatialFact(content="Paris is at 48.86°N, 2.35°E")
        assert fact.id
        assert fact.content == "Paris is at 48.86°N, 2.35°E"
        assert fact.confidence == 1.0
        assert fact.is_active is True
        assert fact.tags == []

    def test_fact_with_geometry(self) -> None:
        fact = SpatialFact(
            content="Eiffel Tower",
            geometry={"type": "Point", "coordinates": [2.2944, 48.8584]},
            tags=["landmark"],
            source="tool:geocode",
        )
        assert fact.geometry is not None
        assert fact.source == "tool:geocode"
        assert "landmark" in fact.tags

    def test_fact_default_values(self) -> None:
        fact = SpatialFact(content="test")
        assert fact.connections == []
        assert fact.source == ""
        assert fact.created_at is not None


class TestSpatialEpisode:
    """Tests for SpatialEpisode model."""

    def test_create_episode(self) -> None:
        ep = SpatialEpisode(content="PM2.5 was 42 in Delhi")
        assert ep.id
        assert ep.importance == 0.5
        assert ep.is_active is True

    def test_episode_with_timestamp(self) -> None:
        ts = datetime(2026, 4, 9, 14, 0, tzinfo=timezone.utc)
        ep = SpatialEpisode(
            content="Temperature was 28°C",
            occurred_at=ts,
            source="tool:weather",
            importance=0.7,
        )
        assert ep.occurred_at == ts
        assert ep.importance == 0.7

    def test_episode_session_id(self) -> None:
        ep = SpatialEpisode(
            content="Fire detected",
            session_id="abc123",
        )
        assert ep.session_id == "abc123"


class TestMemoryAction:
    """Tests for MemoryAction enum."""

    def test_all_actions(self) -> None:
        assert MemoryAction.ADD == "add"
        assert MemoryAction.UPDATE == "update"
        assert MemoryAction.REPLACE == "replace"
        assert MemoryAction.DELETE == "delete"
        assert MemoryAction.NOOP == "noop"


class TestMemoryConnection:
    """Tests for MemoryConnection model."""

    def test_create_connection(self) -> None:
        conn = MemoryConnection(source_id="a", target_id="b", similarity=0.85)
        assert conn.source_id == "a"
        assert conn.target_id == "b"
        assert conn.similarity == 0.85


class TestContradiction:
    """Tests for Contradiction model."""

    def test_create_contradiction(self) -> None:
        c = Contradiction(
            fact_a_id="a",
            fact_a_content="Paris is in France",
            fact_b_id="b",
            fact_b_content="Paris is in Germany",
            similarity=0.85,
        )
        assert c.fact_a_id == "a"
        assert c.similarity == 0.85


class TestWordOverlap:
    """Tests for word overlap scoring."""

    def test_exact_match(self) -> None:
        assert _word_overlap_score("Paris", "Paris is a city") == 0.9

    def test_word_overlap(self) -> None:
        score = _word_overlap_score("flood risk Melbourne", "flood warning in Melbourne area")
        assert 0.0 < score <= 0.8

    def test_no_overlap(self) -> None:
        assert _word_overlap_score("Tokyo weather", "Paris landmarks") == 0.0

    def test_empty_query(self) -> None:
        assert _word_overlap_score("", "some content") == 0.0


# ======================================================================
# SpatialIntelligence tests
# ======================================================================


class TestSpatialIntelligence:
    """Tests for the SpatialIntelligence engine."""

    def _make_intel(self, tmp: str) -> SpatialIntelligence:
        """Create a test intelligence instance (no Ollama)."""
        return SpatialIntelligence(
            storage_dir=tmp,
            ollama_url="http://localhost:99999",  # Intentionally unreachable
        )

    def test_remember_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact("Eiffel Tower is at 48.86°N, 2.29°E")
            assert fact.id
            assert fact.content == "Eiffel Tower is at 48.86°N, 2.29°E"
            assert fact.is_active is True

    def test_remember_fact_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact(
                "Melbourne uses EPSG:32755",
                source="user",
                confidence=0.95,
                tags=["crs", "preference"],
            )
            assert fact.source == "user"
            assert fact.confidence == 0.95
            assert "crs" in fact.tags

    def test_remember_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            ep = intel.remember_episode(
                "PM2.5 was 120 µg/m³ in Delhi",
                importance=0.8,
                source="tool:air_quality",
            )
            assert ep.importance == 0.8
            assert ep.source == "tool:air_quality"

    def test_recall_facts_by_word_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Eiffel Tower is at 48.86°N, 2.29°E")
            intel.remember_fact("Tokyo Tower is at 35.66°N, 139.75°E")
            intel.remember_fact("Big Ben is at 51.50°N, 0.12°W")

            results = intel.recall("Eiffel Tower")
            assert len(results) >= 1
            assert "Eiffel" in results[0]["content"]

    def test_recall_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_episode("Heavy rain in Melbourne today", importance=0.6)
            intel.remember_episode("Sunny weather in Sydney", importance=0.4)

            results = intel.recall("Melbourne rain", memory_type="episode")
            assert len(results) >= 1
            assert "Melbourne" in results[0]["content"]

    def test_recall_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Melbourne CBD coordinates: -37.81, 144.96")
            intel.remember_episode("Temperature was 32°C in Melbourne")

            results = intel.recall("Melbourne")
            assert len(results) == 2

    def test_recall_filter_by_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Paris is the capital of France")
            intel.remember_episode("It rained in Paris today")

            facts_only = intel.recall("Paris", memory_type="fact")
            episodes_only = intel.recall("Paris", memory_type="episode")
            assert all(r["type"] == "fact" for r in facts_only)
            assert all(r["type"] == "episode" for r in episodes_only)

    def test_recall_respects_active_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact("Old fact about London")
            fact.is_active = False
            intel._save()

            results = intel.recall("London")
            assert len(results) == 0

            results_with_inactive = intel.recall("London", include_inactive=True)
            assert len(results_with_inactive) == 1

    def test_find_contradictions_word_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Paris is in France")
            intel.remember_fact("Paris is in Germany")

            contradictions = intel.find_contradictions(threshold=0.5)
            # These should be detected as similar-but-different
            assert len(contradictions) >= 1
            assert contradictions[0].similarity >= 0.5

    def test_no_contradictions_for_different_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Paris is at 48.86°N")
            intel.remember_fact("Tokyo is at 35.68°N")

            contradictions = intel.find_contradictions(threshold=0.7)
            assert len(contradictions) == 0

    def test_resolve_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            f1 = intel.remember_fact("Paris population: 2.1 million")
            f2 = intel.remember_fact("Paris population: 2.2 million")

            result = intel.resolve_contradiction(keep_id=f2.id, remove_id=f1.id)
            assert result is True

            # Deactivated fact should not appear in active-only listing
            active_facts = intel.list_facts(active_only=True)
            ids = [f.id for f in active_facts]
            assert f1.id not in ids
            assert f2.id in ids

    def test_update_memory_add(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = intel.update_memory("New spatial fact", MemoryAction.ADD, source="test")
            assert result["action"] == "add"
            assert result["id"]
            assert intel.list_facts() != []

    def test_update_memory_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact("Paris population: 2.1M")
            result = intel.update_memory(
                "Paris population: 2.16M (2025 census)",
                MemoryAction.UPDATE,
                target_id=fact.id,
            )
            assert result["action"] == "update"
            updated_fact = intel.get_fact(fact.id)
            assert "2.16M" in updated_fact.content

    def test_update_memory_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            old_fact = intel.remember_fact("Earth circumference: 40000 km")
            result = intel.update_memory(
                "Earth circumference: 40,075 km (equatorial)",
                MemoryAction.REPLACE,
                target_id=old_fact.id,
            )
            assert result["action"] == "replace"
            assert result["removed_id"] == old_fact.id
            # Old fact should be deactivated
            assert intel.get_fact(old_fact.id).is_active is False

    def test_update_memory_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact("Temporary fact")
            result = intel.update_memory("", MemoryAction.DELETE, target_id=fact.id)
            assert result["action"] == "delete"
            assert intel.get_fact(fact.id).is_active is False

    def test_update_memory_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = intel.update_memory("anything", MemoryAction.NOOP)
            assert result["action"] == "noop"

    def test_update_memory_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = intel.update_memory(
                "update content", MemoryAction.UPDATE, target_id="nonexistent"
            )
            assert result["action"] == "noop"

    def test_extract_geocode_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {
                "features": [{
                    "properties": {"display_name": "Eiffel Tower, Paris, France"},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [2.2944, 48.8584],
                    },
                }]
            }
            extracted = intel.extract_from_result("geocode", result)
            assert len(extracted) == 1
            assert extracted[0]["type"] == "fact"
            assert "Eiffel Tower" in extracted[0]["content"]

    def test_extract_weather_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {
                "features": [{
                    "type": "current_weather",
                    "location": "Melbourne",
                    "temperature_c": 22,
                    "weather_description": "Partly cloudy",
                    "humidity_pct": 65,
                }]
            }
            extracted = intel.extract_from_result("weather", result)
            assert len(extracted) == 1
            assert extracted[0]["type"] == "episode"
            assert "22°C" in extracted[0]["content"]

    def test_extract_fire_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {
                "features": [{"confidence": 85}, {"confidence": 70}],
                "metadata": {"location": "California"},
            }
            extracted = intel.extract_from_result("fires", result)
            assert len(extracted) == 1
            assert "2 active fire" in extracted[0]["content"]

    def test_extract_elevation_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {"elevation_m": 8849, "latitude": 27.9881, "longitude": 86.9250}
            extracted = intel.extract_from_result("elevation", result)
            assert len(extracted) == 1
            assert "8849" in extracted[0]["content"]

    def test_extract_air_quality_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {
                "features": [{
                    "station_name": "Delhi Central",
                    "measurements": {"pm25": {"value": 120}},
                    "aqi_category": "Unhealthy",
                    "coordinates": [77.23, 28.61],
                }]
            }
            extracted = intel.extract_from_result("air_quality", result)
            assert len(extracted) == 1
            assert "PM2.5 = 120" in extracted[0]["content"]

    def test_extract_distance_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            result = {"distance_km": 343.56, "distance_m": 343560}
            extracted = intel.extract_from_result("distance", result)
            assert len(extracted) == 1
            assert "343.56 km" in extracted[0]["content"]

    def test_extract_unknown_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            extracted = intel.extract_from_result("unknown_tool", {"data": "test"})
            assert extracted == []

    def test_compact_old_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)

            # Add an old, low-importance episode
            old_ep = intel.remember_episode("Old weather data", importance=0.3)
            old_ep.created_at = datetime.now(timezone.utc) - timedelta(days=60)

            # Add a recent episode
            intel.remember_episode("Recent fire alert", importance=0.9)

            result = intel.compact(max_age_days=30, keep_important=0.7)
            assert result["compacted"] == 1
            assert result["kept"] == 1

    def test_compact_preserves_important(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)

            # Old but important
            ep = intel.remember_episode("Critical flood alert", importance=0.9)
            ep.created_at = datetime.now(timezone.utc) - timedelta(days=60)

            result = intel.compact(max_age_days=30, keep_important=0.7)
            assert result["compacted"] == 0
            assert result["kept"] == 1

    def test_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Fact 1")
            intel.remember_fact("Fact 2")
            intel.remember_episode("Episode 1")

            s = intel.stats()
            assert s.total_facts == 2
            assert s.active_facts == 2
            assert s.total_episodes == 1
            assert s.active_episodes == 1

    def test_get_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            fact = intel.remember_fact("Test fact")
            assert intel.get_fact(fact.id) is not None
            assert intel.get_fact("nonexistent") is None

    def test_get_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            ep = intel.remember_episode("Test episode")
            assert intel.get_episode(ep.id) is not None
            assert intel.get_episode("nonexistent") is None

    def test_list_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Fact A")
            f2 = intel.remember_fact("Fact B")
            f2.is_active = False

            active = intel.list_facts(active_only=True)
            all_facts = intel.list_facts(active_only=False)
            assert len(active) == 1
            assert len(all_facts) == 2

    def test_list_episodes_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_episode(
                "First",
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            intel.remember_episode(
                "Second",
                occurred_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            )

            episodes = intel.list_episodes()
            assert episodes[0].content == "Second"  # Most recent first

    def test_get_connections_for(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            # Manually add a connection
            intel._connections.append(
                MemoryConnection(source_id="a", target_id="b", similarity=0.8)
            )
            conns = intel.get_connections_for("a")
            assert len(conns) == 1
            assert conns[0].target_id == "b"

            conns_b = intel.get_connections_for("b")
            assert len(conns_b) == 1

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel1 = self._make_intel(tmp)
            intel1.remember_fact("Persistent fact")
            intel1.remember_episode("Persistent episode")

            # Reload from disk
            intel2 = self._make_intel(tmp)
            assert len(intel2.list_facts()) == 1
            assert len(intel2.list_episodes()) == 1
            assert intel2.list_facts()[0].content == "Persistent fact"

    def test_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intel = self._make_intel(tmp)
            intel.remember_fact("Fact")
            intel.remember_episode("Episode")
            intel._connections.append(
                MemoryConnection(source_id="x", target_id="y", similarity=0.5)
            )

            counts = intel.clear()
            assert counts["facts"] == 1
            assert counts["episodes"] == 1
            assert counts["connections"] == 1
            assert intel.stats().total_facts == 0


class TestIntelligenceStats:
    """Tests for IntelligenceStats model."""

    def test_default_stats(self) -> None:
        s = IntelligenceStats()
        assert s.total_facts == 0
        assert s.using_faiss is False

    def test_custom_stats(self) -> None:
        s = IntelligenceStats(
            total_facts=10,
            active_facts=8,
            total_episodes=5,
            contradictions_found=2,
        )
        assert s.total_facts == 10
        assert s.contradictions_found == 2
