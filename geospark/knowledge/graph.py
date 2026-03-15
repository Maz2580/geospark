"""In-memory spatial knowledge graph.

Stores spatial entities and their relationships, supports multi-hop graph
traversal, spatial proximity queries, and automatic relation discovery
using the ``SpatialReasoner`` for geodesic distance / topology checks.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.entities import SpatialEntity, SpatialRelation


class SpatialKnowledgeGraph:
    """In-memory spatial knowledge graph.

    Entities are stored as nodes keyed by ID. Relations are stored as an
    edge list. A secondary ``_spatial_index`` maps entity types to lists
    of entity IDs for fast type-based look-ups.

    Key capabilities:
    - CRUD for entities and relations
    - Spatial queries (find_entities with optional proximity filter)
    - Graph traversal (shortest_path via BFS, N-hop neighbors)
    - Automatic relation discovery (auto_relate) using geodesic distance
      and topological checks from ``SpatialReasoner``
    - Serialisation / deserialisation for persistence
    """

    def __init__(self) -> None:
        self._entities: dict[str, SpatialEntity] = {}
        self._relations: list[SpatialRelation] = []
        self._spatial_index: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    def add_entity(self, entity: SpatialEntity) -> None:
        """Add or update a spatial entity in the graph.

        Args:
            entity: The entity to add. If an entity with the same ID already
                exists it will be replaced.
        """
        self._entities[entity.id] = entity
        # Update spatial index
        type_ids = self._spatial_index.setdefault(entity.entity_type, [])
        if entity.id not in type_ids:
            type_ids.append(entity.id)

    def get_entity(self, entity_id: str) -> SpatialEntity | None:
        """Look up an entity by ID.

        Args:
            entity_id: Unique entity identifier.

        Returns:
            The entity, or ``None`` if not found.
        """
        return self._entities.get(entity_id)

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------

    def add_relation(self, relation: SpatialRelation) -> None:
        """Add a directed relation between two entities.

        Args:
            relation: The relation to add.

        Raises:
            ValueError: If source or target entity is not in the graph.
        """
        if relation.source_id not in self._entities:
            raise ValueError(
                f"Source entity '{relation.source_id}' not found in graph"
            )
        if relation.target_id not in self._entities:
            raise ValueError(
                f"Target entity '{relation.target_id}' not found in graph"
            )
        self._relations.append(relation)

    def get_relations(
        self,
        entity_id: str,
        relation_type: str | None = None,
    ) -> list[SpatialRelation]:
        """Get all relations involving an entity (as source **or** target).

        Args:
            entity_id: Entity ID to search for.
            relation_type: Optional filter by relation type.

        Returns:
            List of matching relations.
        """
        results: list[SpatialRelation] = []
        for rel in self._relations:
            if rel.source_id != entity_id and rel.target_id != entity_id:
                continue
            if relation_type is not None and rel.relation_type != relation_type:
                continue
            results.append(rel)
        return results

    # ------------------------------------------------------------------
    # Spatial queries
    # ------------------------------------------------------------------

    def find_entities(
        self,
        entity_type: str | None = None,
        near: dict[str, Any] | None = None,
        radius_m: float = 1000,
    ) -> list[SpatialEntity]:
        """Find entities by type and/or spatial proximity.

        Args:
            entity_type: Filter by entity type (e.g. ``"hospital"``).
                ``None`` means no type filter.
            near: GeoJSON geometry dict to search around. If ``None``,
                proximity is not considered.
            radius_m: Search radius in metres (default 1000).

        Returns:
            List of matching entities, sorted by distance when *near* is
            provided.
        """
        # Determine candidate IDs
        if entity_type is not None:
            candidate_ids = self._spatial_index.get(entity_type, [])
        else:
            candidate_ids = list(self._entities.keys())

        candidates = [self._entities[eid] for eid in candidate_ids if eid in self._entities]

        if near is None:
            return candidates

        # Filter by distance
        scored: list[tuple[float, SpatialEntity]] = []
        for entity in candidates:
            try:
                dist = SpatialReasoner.calculate_distance(near, entity.geometry)
            except Exception:
                continue
            if dist <= radius_m:
                scored.append((dist, entity))

        scored.sort(key=lambda pair: pair[0])
        return [entity for _, entity in scored]

    def query(self, query_str: str) -> list[SpatialEntity]:
        """Simple query parser for natural-language-style spatial queries.

        Supported patterns:
        - ``"hospitals near Paris"`` -- finds entities of a type that are
          near a named entity already in the graph.
        - ``"parks"`` -- returns all entities of the given type.

        Args:
            query_str: A simple spatial query string.

        Returns:
            Matching entities.
        """
        query_str = query_str.strip()

        # Pattern: "<type> near <entity_name>"
        match = re.match(
            r"^(\w+)\s+near\s+(.+)$", query_str, re.IGNORECASE
        )
        if match:
            entity_type = match.group(1).lower()
            ref_name = match.group(2).strip()

            # Find the reference entity by name (case-insensitive)
            ref_entity: SpatialEntity | None = None
            for ent in self._entities.values():
                if ent.name.lower() == ref_name.lower():
                    ref_entity = ent
                    break

            if ref_entity is None:
                return []

            return self.find_entities(
                entity_type=entity_type,
                near=ref_entity.geometry,
                radius_m=50_000,  # Default 50 km for natural-language queries
            )

        # Fallback: treat the whole string as an entity type
        return self.find_entities(entity_type=query_str.lower())

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def shortest_path(self, from_id: str, to_id: str) -> list[str]:
        """Find the shortest path between two entities via relations (BFS).

        Treats the graph as undirected (both source and target edges are
        traversed).

        Args:
            from_id: Start entity ID.
            to_id: End entity ID.

        Returns:
            List of entity IDs forming the shortest path (inclusive of
            start and end). Empty list if no path exists or if either
            entity is missing.
        """
        if from_id not in self._entities or to_id not in self._entities:
            return []
        if from_id == to_id:
            return [from_id]

        # Build adjacency from relations
        adj: dict[str, set[str]] = {}
        for rel in self._relations:
            adj.setdefault(rel.source_id, set()).add(rel.target_id)
            adj.setdefault(rel.target_id, set()).add(rel.source_id)

        # BFS
        visited: set[str] = {from_id}
        queue: deque[list[str]] = deque([[from_id]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbour in adj.get(current, set()):
                if neighbour == to_id:
                    return [*path, neighbour]
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append([*path, neighbour])

        return []

    def neighbors(self, entity_id: str, depth: int = 1) -> list[SpatialEntity]:
        """Get all entities connected within *depth* hops.

        Args:
            entity_id: Starting entity ID.
            depth: Maximum traversal depth (default 1).

        Returns:
            List of neighbouring entities (excluding the start entity).
            Empty list if entity not found.
        """
        if entity_id not in self._entities:
            return []

        # Build adjacency
        adj: dict[str, set[str]] = {}
        for rel in self._relations:
            adj.setdefault(rel.source_id, set()).add(rel.target_id)
            adj.setdefault(rel.target_id, set()).add(rel.source_id)

        visited: set[str] = {entity_id}
        current_frontier: set[str] = {entity_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in current_frontier:
                for nb in adj.get(node, set()):
                    if nb not in visited:
                        visited.add(nb)
                        next_frontier.add(nb)
            current_frontier = next_frontier

        visited.discard(entity_id)
        return [self._entities[eid] for eid in visited if eid in self._entities]

    # ------------------------------------------------------------------
    # Auto-relation discovery
    # ------------------------------------------------------------------

    def auto_relate(self, max_distance_m: float = 5000) -> int:
        """Auto-discover spatial relations between entities.

        For every pair of entities:
        - If distance <= ``max_distance_m``, add a ``"near"`` relation.
        - If one geometry *contains* the other, add a ``"contains"`` relation.

        Uses ``SpatialReasoner.calculate_distance`` and
        ``SpatialReasoner.check_relationship`` for ground-truth checks.

        Args:
            max_distance_m: Maximum distance in metres for the ``"near"``
                relation.

        Returns:
            Number of new relations added.
        """
        entities = list(self._entities.values())
        added = 0

        # Build set of existing relation tuples for dedup
        existing: set[tuple[str, str, str]] = {
            (r.source_id, r.target_id, r.relation_type)
            for r in self._relations
        }

        for i, ent_a in enumerate(entities):
            for ent_b in entities[i + 1 :]:
                # --- "near" relation ---
                try:
                    dist = SpatialReasoner.calculate_distance(
                        ent_a.geometry, ent_b.geometry
                    )
                except Exception:
                    dist = None

                if dist is not None and dist <= max_distance_m:
                    key = (ent_a.id, ent_b.id, "near")
                    key_rev = (ent_b.id, ent_a.id, "near")
                    if key not in existing and key_rev not in existing:
                        self._relations.append(
                            SpatialRelation(
                                source_id=ent_a.id,
                                target_id=ent_b.id,
                                relation_type="near",
                                properties={"distance_m": dist},
                            )
                        )
                        existing.add(key)
                        added += 1

                # --- "contains" relation ---
                try:
                    a_contains_b = SpatialReasoner.check_relationship(
                        ent_a.geometry, ent_b.geometry, "contains"
                    )
                except Exception:
                    a_contains_b = False

                if a_contains_b:
                    key = (ent_a.id, ent_b.id, "contains")
                    if key not in existing:
                        self._relations.append(
                            SpatialRelation(
                                source_id=ent_a.id,
                                target_id=ent_b.id,
                                relation_type="contains",
                            )
                        )
                        existing.add(key)
                        added += 1
                else:
                    try:
                        b_contains_a = SpatialReasoner.check_relationship(
                            ent_b.geometry, ent_a.geometry, "contains"
                        )
                    except Exception:
                        b_contains_a = False

                    if b_contains_a:
                        key = (ent_b.id, ent_a.id, "contains")
                        if key not in existing:
                            self._relations.append(
                                SpatialRelation(
                                    source_id=ent_b.id,
                                    target_id=ent_a.id,
                                    relation_type="contains",
                                )
                            )
                            existing.add(key)
                            added += 1

        return added

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a plain dict for persistence.

        Returns:
            Dict with ``"entities"`` and ``"relations"`` keys.
        """
        return {
            "entities": [e.model_dump() for e in self._entities.values()],
            "relations": [r.model_dump() for r in self._relations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpatialKnowledgeGraph:
        """Restore a graph from a serialised dict.

        Args:
            data: Dict previously produced by ``to_dict()``.

        Returns:
            A new ``SpatialKnowledgeGraph`` instance.
        """
        graph = cls()
        for entity_data in data.get("entities", []):
            graph.add_entity(SpatialEntity(**entity_data))
        for relation_data in data.get("relations", []):
            graph._relations.append(SpatialRelation(**relation_data))
        return graph

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def entity_count(self) -> int:
        """Number of entities in the graph."""
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        """Number of relations in the graph."""
        return len(self._relations)
