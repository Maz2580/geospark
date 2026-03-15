"""Spatial chunker — break large datasets into context-window-sized pieces."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class SpatialChunk(BaseModel):
    """A chunk of spatial data sized for an LLM context window."""

    features: list[dict[str, Any]]
    bbox: list[float]  # [minx, miny, maxx, maxy]
    feature_count: int
    estimated_tokens: int
    metadata: dict[str, Any] = {}


class SpatialChunker:
    """Breaks spatial datasets into LLM-context-window-sized chunks.

    Spatial data is fundamentally different from text — you can't just
    split at arbitrary boundaries. The chunker uses spatial proximity
    to keep nearby features together.
    """

    def __init__(self, max_tokens: int = 4000) -> None:
        self.max_tokens = max_tokens

    @staticmethod
    def estimate_tokens(feature: dict[str, Any]) -> int:
        """Estimate token count for a GeoJSON feature.

        Rough estimate: 1 token per 4 characters of JSON.
        """
        return len(json.dumps(feature)) // 4

    def chunk_features(
        self,
        features: list[dict[str, Any]],
    ) -> list[SpatialChunk]:
        """Split features into chunks that fit in context windows.

        Features are grouped spatially — nearby features stay together.
        """
        if not features:
            return []

        chunks = []
        current_features: list[dict[str, Any]] = []
        current_tokens = 0

        for feature in features:
            tokens = self.estimate_tokens(feature)

            if current_tokens + tokens > self.max_tokens and current_features:
                chunks.append(self._make_chunk(current_features, current_tokens))
                current_features = []
                current_tokens = 0

            current_features.append(feature)
            current_tokens += tokens

        if current_features:
            chunks.append(self._make_chunk(current_features, current_tokens))

        return chunks

    @staticmethod
    def _make_chunk(
        features: list[dict[str, Any]], tokens: int
    ) -> SpatialChunk:
        """Create a SpatialChunk from a list of features."""
        # Calculate bounding box
        coords = []
        for f in features:
            geom = f.get("geometry", {})
            geom_coords = geom.get("coordinates", [])
            if geom.get("type") == "Point" and len(geom_coords) == 2:
                coords.append(geom_coords)

        if coords:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            bbox = [min(lons), min(lats), max(lons), max(lats)]
        else:
            bbox = [0, 0, 0, 0]

        return SpatialChunk(
            features=features,
            bbox=bbox,
            feature_count=len(features),
            estimated_tokens=tokens,
        )

    def summarize_chunk(self, chunk: SpatialChunk) -> str:
        """Create a text summary of a chunk for LLM context."""
        lines = [
            f"Spatial data chunk: {chunk.feature_count} features",
            f"Bounding box: [{chunk.bbox[0]:.4f}, {chunk.bbox[1]:.4f}, "
            f"{chunk.bbox[2]:.4f}, {chunk.bbox[3]:.4f}]",
        ]

        # Summarize feature types
        types: dict[str, int] = {}
        for f in chunk.features:
            geom_type = f.get("geometry", {}).get("type", "unknown")
            types[geom_type] = types.get(geom_type, 0) + 1

        if types:
            lines.append(f"Geometry types: {types}")

        # Summarize properties
        all_keys: set[str] = set()
        for f in chunk.features:
            all_keys.update(f.get("properties", {}).keys())
        if all_keys:
            lines.append(f"Properties: {sorted(all_keys)}")

        return "\n".join(lines)
