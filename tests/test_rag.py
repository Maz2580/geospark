"""Tests for the GeoSpark Spatial RAG module."""
from __future__ import annotations

from geospark.rag.chunker import SpatialChunker
from geospark.rag.context_builder import ContextBuilder
from geospark.rag.retriever import SpatialRetriever

# Sample features for testing
SAMPLE_FEATURES = [
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.2945, 48.8584]},
        "properties": {"name": "Eiffel Tower", "category": "landmark"},
    },
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.3376, 48.8606]},
        "properties": {"name": "Louvre Museum", "category": "museum"},
    },
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.3500, 48.8530]},
        "properties": {"name": "Notre-Dame", "category": "landmark"},
    },
    {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [139.7454, 35.6586]},
        "properties": {"name": "Tokyo Tower", "category": "landmark"},
    },
]


class TestSpatialRetriever:
    """Tests for spatial retrieval."""

    def test_create_empty(self) -> None:
        retriever = SpatialRetriever()
        assert retriever.feature_count == 0

    def test_add_features(self) -> None:
        retriever = SpatialRetriever()
        count = retriever.add_features(SAMPLE_FEATURES)
        assert count == 4

    def test_retrieve_by_location(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        # Search near Eiffel Tower — should find Paris features, not Tokyo
        results = retriever.retrieve_by_location(
            query_geometry={"type": "Point", "coordinates": [2.3, 48.86]},
            radius_m=10000,
        )
        assert len(results) == 3  # 3 Paris features within 10km
        assert all(r.distance_m is not None for r in results)
        # Results should be sorted by distance
        distances = [r.distance_m for r in results]
        assert distances == sorted(distances)

    def test_retrieve_by_text(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        results = retriever.retrieve_by_text("landmark Tower")
        assert len(results) >= 1
        # Should find features with "landmark" or "Tower" in properties
        names = [r.feature["properties"]["name"] for r in results]
        assert any("Tower" in n for n in names)

    def test_combined_retrieve(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        results = retriever.retrieve(
            query="museum",
            geometry={"type": "Point", "coordinates": [2.3, 48.86]},
            radius_m=10000,
        )
        assert len(results) >= 1

    def test_empty_results(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        results = retriever.retrieve_by_location(
            query_geometry={"type": "Point", "coordinates": [0, 0]},
            radius_m=100,
        )
        assert len(results) == 0


class TestSpatialChunker:
    """Tests for spatial chunking."""

    def test_estimate_tokens(self) -> None:
        tokens = SpatialChunker.estimate_tokens(SAMPLE_FEATURES[0])
        assert tokens > 0

    def test_chunk_small_dataset(self) -> None:
        chunker = SpatialChunker(max_tokens=10000)
        chunks = chunker.chunk_features(SAMPLE_FEATURES)
        # Small dataset should fit in one chunk
        assert len(chunks) == 1
        assert chunks[0].feature_count == 4

    def test_chunk_large_dataset(self) -> None:
        chunker = SpatialChunker(max_tokens=50)  # Very small limit
        chunks = chunker.chunk_features(SAMPLE_FEATURES)
        # Should create multiple chunks
        assert len(chunks) > 1
        total = sum(c.feature_count for c in chunks)
        assert total == 4

    def test_chunk_empty(self) -> None:
        chunker = SpatialChunker()
        chunks = chunker.chunk_features([])
        assert len(chunks) == 0

    def test_chunk_has_bbox(self) -> None:
        chunker = SpatialChunker(max_tokens=10000)
        chunks = chunker.chunk_features(SAMPLE_FEATURES)
        bbox = chunks[0].bbox
        assert len(bbox) == 4
        assert bbox[0] < bbox[2]  # minx < maxx
        assert bbox[1] < bbox[3]  # miny < maxy

    def test_summarize_chunk(self) -> None:
        chunker = SpatialChunker(max_tokens=10000)
        chunks = chunker.chunk_features(SAMPLE_FEATURES)
        summary = chunker.summarize_chunk(chunks[0])
        assert "4 features" in summary
        assert "Point" in summary


class TestContextBuilder:
    """Tests for context building."""

    def test_build_empty_context(self) -> None:
        builder = ContextBuilder()
        context = builder.build_context(query="test")
        assert "No relevant spatial data" in context

    def test_build_context_with_features(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        builder = ContextBuilder(retriever=retriever)
        context = builder.build_context(
            query="landmark",
            geometry={"type": "Point", "coordinates": [2.3, 48.86]},
            radius_m=10000,
        )
        assert "Spatial Context" in context
        assert "features" in context.lower()

    def test_build_prompt_with_context(self) -> None:
        retriever = SpatialRetriever(features=SAMPLE_FEATURES)
        builder = ContextBuilder(retriever=retriever)
        messages = builder.build_prompt_with_context(
            user_query="What landmarks are nearby?",
            geometry={"type": "Point", "coordinates": [2.3, 48.86]},
        )
        assert len(messages) >= 2
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "What landmarks are nearby?"
