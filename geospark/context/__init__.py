"""GeoSpark Context — Geospatial Context Database (Phase 7B).

Hierarchical tiered storage for missions, datasets, and analysis history.
Inspired by OpenViking's filesystem-metaphor context database.

Key concepts:
- **Tiered loading**: L0 (abstract), L1 (overview), L2 (full data)
- **Hotness scoring**: balance access frequency and recency
- **Hierarchical URIs**: geospark://missions/melbourne/analysis/2026-04
- **Recursive retrieval**: propagate relevance scores up the tree
- **Archival**: cold contexts moved to _archive/ to reduce token overhead
"""
from __future__ import annotations

from geospark.context.geo_context import (
    ContextRelation,
    ContextTier,
    GeoContext,
    HotnessStats,
)
from geospark.context.retriever import ContextRetriever, RetrievalResult
from geospark.context.storage import ContextStore

__all__ = [
    "ContextRelation",
    "ContextRetriever",
    "ContextStore",
    "ContextTier",
    "GeoContext",
    "HotnessStats",
    "RetrievalResult",
]
