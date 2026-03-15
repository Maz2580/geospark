"""Spatial entity models for the knowledge graph.

Defines the core data structures -- SpatialEntity and SpatialRelation --
used to represent spatial knowledge as a graph of typed, located entities
connected by spatial relationships.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SpatialEntity(BaseModel):
    """A typed spatial entity with geometry and metadata.

    Represents a real-world geographic feature (city, hospital, park, river,
    building, etc.) as a node in the spatial knowledge graph.

    Attributes:
        id: Unique identifier for the entity.
        name: Human-readable name.
        entity_type: Category string (e.g. "city", "hospital", "park").
        geometry: GeoJSON geometry dict.
        properties: Arbitrary key-value metadata.
        tags: Searchable string tags.
    """

    id: str
    name: str
    entity_type: str
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class SpatialRelation(BaseModel):
    """A directed relationship between two spatial entities.

    Represents an edge in the knowledge graph -- for example "Paris contains
    Eiffel Tower" or "Hospital A is near Park B".

    Attributes:
        source_id: ID of the source entity.
        target_id: ID of the target entity.
        relation_type: Relationship kind (e.g. "contains", "near", "within",
            "adjacent_to", "part_of").
        properties: Extra relation metadata (e.g. ``{"distance_m": 500}``).
    """

    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
