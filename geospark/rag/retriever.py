"""Spatial retriever — find relevant features by location and semantics."""
from __future__ import annotations

import math
from typing import Any

import httpx
from pydantic import BaseModel

from geospark.engine.spatial_reasoner import SpatialReasoner


class RetrievedFeature(BaseModel):
    """A feature retrieved by spatial+semantic search."""

    feature: dict[str, Any]
    relevance_score: float = 0.0
    distance_m: float | None = None
    source: str = ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SpatialRetriever:
    """Retrieves relevant spatial features for a query.

    Combines spatial proximity with embedding-based semantic matching.
    Uses Ollama embeddings when available, falls back to word overlap.
    """

    def __init__(
        self,
        features: list[dict[str, Any]] | None = None,
        ollama_url: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        self._features: list[dict[str, Any]] = features or []
        self._embeddings: list[list[float]] = []
        self._ollama_url = ollama_url or "http://localhost:11434"
        self._embed_model = embed_model or "qwen2.5:7b"
        self._embedding_available: bool | None = None  # Lazy check

    def _check_embedding_available(self) -> bool:
        """Check if Ollama embedding is reachable (once, then cached)."""
        if self._embedding_available is not None:
            return self._embedding_available
        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/embed",
                json={"model": self._embed_model, "input": "test"},
                timeout=5.0,
            )
            self._embedding_available = resp.status_code == 200
        except Exception:
            self._embedding_available = False
        return self._embedding_available

    def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text via Ollama."""
        resp = httpx.post(
            f"{self._ollama_url}/api/embed",
            json={"model": self._embed_model, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    def _feature_text(self, feature: dict[str, Any]) -> str:
        """Extract searchable text from a feature's properties."""
        props = feature.get("properties", {})
        return " ".join(str(v) for v in props.values())

    def add_features(self, features: list[dict[str, Any]]) -> int:
        """Add features to the retriever's index.

        If Ollama embeddings are available, pre-computes embeddings for
        each feature. Falls back to word-overlap matching if not.
        """
        self._features.extend(features)

        # Pre-compute embeddings if available
        if self._check_embedding_available():
            for f in features:
                try:
                    text = self._feature_text(f)
                    emb = self._get_embedding(text)
                    self._embeddings.append(emb)
                except Exception:
                    self._embeddings.append([])
        else:
            self._embeddings.extend([] for _ in features)

        return len(self._features)

    def retrieve_by_location(
        self,
        query_geometry: dict[str, Any],
        radius_m: float = 10000,
        limit: int = 10,
    ) -> list[RetrievedFeature]:
        """Retrieve features near a location.

        Args:
            query_geometry: GeoJSON geometry to search around.
            radius_m: Search radius in meters.
            limit: Maximum features to return.

        Returns:
            Features sorted by distance (nearest first).
        """
        results = []
        for feature in self._features:
            geom = feature.get("geometry")
            if geom is None:
                continue

            try:
                dist = SpatialReasoner.calculate_distance(query_geometry, geom)
            except Exception:
                continue

            if dist <= radius_m:
                score = max(0.0, 1.0 - dist / radius_m)
                results.append(
                    RetrievedFeature(
                        feature=feature,
                        relevance_score=score,
                        distance_m=dist,
                    )
                )

        results.sort(key=lambda r: r.distance_m or float("inf"))
        return results[:limit]

    def retrieve_by_text(
        self,
        query: str,
        limit: int = 10,
    ) -> list[RetrievedFeature]:
        """Retrieve features by semantic matching.

        Uses Ollama embedding cosine similarity when available,
        falls back to word overlap otherwise.
        """
        # Try embedding-based retrieval
        if self._check_embedding_available() and any(self._embeddings):
            return self._retrieve_by_embedding(query, limit)
        return self._retrieve_by_word_overlap(query, limit)

    def _retrieve_by_embedding(
        self, query: str, limit: int
    ) -> list[RetrievedFeature]:
        """Embedding-based semantic retrieval via cosine similarity."""
        try:
            query_emb = self._get_embedding(query)
        except Exception:
            return self._retrieve_by_word_overlap(query, limit)

        results = []
        for i, feature in enumerate(self._features):
            emb = self._embeddings[i] if i < len(self._embeddings) else []
            if not emb:
                continue
            score = _cosine_similarity(query_emb, emb)
            if score > 0.1:  # Minimum threshold
                results.append(
                    RetrievedFeature(
                        feature=feature,
                        relevance_score=score,
                        source="embedding",
                    )
                )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    def _retrieve_by_word_overlap(
        self, query: str, limit: int
    ) -> list[RetrievedFeature]:
        """Word overlap fallback for when embeddings aren't available."""
        query_words = set(query.lower().split())
        results = []

        for feature in self._features:
            text = self._feature_text(feature).lower()
            text_words = set(text.split())

            overlap = len(query_words & text_words)
            if overlap > 0:
                score = min(overlap / max(len(query_words), 1), 1.0)
                results.append(
                    RetrievedFeature(
                        feature=feature,
                        relevance_score=score,
                        source="word_overlap",
                    )
                )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    def retrieve(
        self,
        query: str | None = None,
        geometry: dict[str, Any] | None = None,
        radius_m: float = 10000,
        limit: int = 10,
        spatial_weight: float = 0.6,
    ) -> list[RetrievedFeature]:
        """Combined spatial + semantic retrieval.

        Args:
            query: Text query for semantic matching.
            geometry: GeoJSON geometry for spatial proximity.
            radius_m: Search radius in meters.
            limit: Max results.
            spatial_weight: Weight for spatial score (0-1). Text weight = 1 - spatial_weight.
        """
        spatial_results = {}
        text_results = {}

        if geometry:
            for r in self.retrieve_by_location(geometry, radius_m, limit=limit * 2):
                key = id(r.feature)
                spatial_results[key] = r

        if query:
            for r in self.retrieve_by_text(query, limit=limit * 2):
                key = id(r.feature)
                text_results[key] = r

        # Combine scores
        all_keys = set(spatial_results.keys()) | set(text_results.keys())
        combined = []
        text_weight = 1.0 - spatial_weight

        for key in all_keys:
            spatial_score = spatial_results[key].relevance_score if key in spatial_results else 0.0
            text_score = text_results[key].relevance_score if key in text_results else 0.0
            final_score = spatial_score * spatial_weight + text_score * text_weight

            feature = (
                spatial_results[key].feature
                if key in spatial_results
                else text_results[key].feature
            )
            distance = spatial_results[key].distance_m if key in spatial_results else None

            combined.append(
                RetrievedFeature(
                    feature=feature,
                    relevance_score=final_score,
                    distance_m=distance,
                )
            )

        combined.sort(key=lambda r: r.relevance_score, reverse=True)
        return combined[:limit]

    @property
    def feature_count(self) -> int:
        """Number of indexed features."""
        return len(self._features)
