"""Spatial Knowledge Graph module.

Provides structured spatial knowledge for multi-hop queries via an
in-memory graph of typed spatial entities connected by spatial relations.
"""

from __future__ import annotations

from geospark.knowledge.entities import SpatialEntity, SpatialRelation
from geospark.knowledge.graph import SpatialKnowledgeGraph
from geospark.knowledge.loaders import GeoJSONLoader, OverpassLoader

__all__ = [
    "GeoJSONLoader",
    "OverpassLoader",
    "SpatialEntity",
    "SpatialKnowledgeGraph",
    "SpatialRelation",
]
