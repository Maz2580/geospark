"""Spatial retriever — find relevant features by location and semantics."""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from geospark.engine.spatial_reasoner import SpatialReasoner


class RetrievedFeature(BaseModel):
    """A feature retrieved by spatial+semantic search."""

    feature: dict[str, Any]
    relevance_score: float = 0.0
    distance_m: float | None = None
    source: str = ""


class SpatialRetriever:
    """Retrieves relevant spatial features for a query.

    Combines spatial proximity with text-based semantic matching.
    For production, integrate with vector databases (Pinecone, Qdrant)
    for embedding-based similarity.
    """

    def __init__(self, features: list[dict[str, Any]] | None = None) -> None:
        self._features: list[dict[str, Any]] = features or []

    def add_features(self, features: list[dict[str, Any]]) -> int:
        """Add features to the retriever's index."""
        self._features.extend(features)
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
        """Retrieve features by text-based semantic matching.

        Simple word overlap matching. For production, replace with
        embedding-based similarity (OpenAI embeddings, etc.).
        """
        query_words = set(query.lower().split())
        results = []

        for feature in self._features:
            props = feature.get("properties", {})
            text = " ".join(str(v) for v in props.values()).lower()
            text_words = set(text.split())

            overlap = len(query_words & text_words)
            if overlap > 0:
                score = min(overlap / max(len(query_words), 1), 1.0)
                results.append(
                    RetrievedFeature(
                        feature=feature,
                        relevance_score=score,
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
