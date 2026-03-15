"""Tests for the GeoSpark Spatial Knowledge Graph module."""
from __future__ import annotations

import json
from typing import ClassVar

import pytest

from geospark.knowledge.entities import SpatialEntity, SpatialRelation
from geospark.knowledge.graph import SpatialKnowledgeGraph
from geospark.knowledge.loaders import GeoJSONLoader

# ---------------------------------------------------------------------------
# Fixtures / sample data
# ---------------------------------------------------------------------------

PARIS = SpatialEntity(
    id="paris",
    name="Paris",
    entity_type="city",
    geometry={
        "type": "Polygon",
        "coordinates": [[
            [2.25, 48.815],
            [2.42, 48.815],
            [2.42, 48.90],
            [2.25, 48.90],
            [2.25, 48.815],
        ]],
    },
    properties={"country": "France", "population": 2_161_000},
    tags=["capital", "europe"],
)

EIFFEL_TOWER = SpatialEntity(
    id="eiffel",
    name="Eiffel Tower",
    entity_type="landmark",
    geometry={"type": "Point", "coordinates": [2.2945, 48.8584]},
    properties={"category": "landmark", "height_m": 330},
    tags=["tourist", "landmark"],
)

LOUVRE = SpatialEntity(
    id="louvre",
    name="Louvre Museum",
    entity_type="museum",
    geometry={"type": "Point", "coordinates": [2.3376, 48.8606]},
    properties={"category": "museum"},
    tags=["tourist", "museum"],
)

NOTRE_DAME = SpatialEntity(
    id="notre_dame",
    name="Notre-Dame",
    entity_type="landmark",
    geometry={"type": "Point", "coordinates": [2.3500, 48.8530]},
    properties={"category": "landmark"},
    tags=["tourist", "landmark"],
)

TOKYO_TOWER = SpatialEntity(
    id="tokyo_tower",
    name="Tokyo Tower",
    entity_type="landmark",
    geometry={"type": "Point", "coordinates": [139.7454, 35.6586]},
    properties={"category": "landmark"},
    tags=["tourist"],
)

HOSPITAL_PARIS = SpatialEntity(
    id="hospital_paris",
    name="Hopital Necker",
    entity_type="hospital",
    geometry={"type": "Point", "coordinates": [2.3158, 48.8468]},
    properties={"beds": 500},
    tags=["healthcare"],
)


def _make_graph() -> SpatialKnowledgeGraph:
    """Build a small test graph with Paris entities."""
    graph = SpatialKnowledgeGraph()
    for entity in [PARIS, EIFFEL_TOWER, LOUVRE, NOTRE_DAME, TOKYO_TOWER, HOSPITAL_PARIS]:
        graph.add_entity(entity)
    return graph


# ---------------------------------------------------------------------------
# Entity CRUD
# ---------------------------------------------------------------------------


class TestEntityCRUD:
    """Tests for entity add / get / find."""

    def test_add_and_get_entity(self) -> None:
        graph = SpatialKnowledgeGraph()
        graph.add_entity(EIFFEL_TOWER)
        result = graph.get_entity("eiffel")
        assert result is not None
        assert result.name == "Eiffel Tower"

    def test_get_missing_entity(self) -> None:
        graph = SpatialKnowledgeGraph()
        assert graph.get_entity("nonexistent") is None

    def test_entity_count(self) -> None:
        graph = _make_graph()
        assert graph.entity_count == 6

    def test_add_entity_updates_existing(self) -> None:
        graph = SpatialKnowledgeGraph()
        graph.add_entity(EIFFEL_TOWER)
        updated = EIFFEL_TOWER.model_copy(update={"name": "Tour Eiffel"})
        graph.add_entity(updated)
        assert graph.entity_count == 1
        assert graph.get_entity("eiffel").name == "Tour Eiffel"

    def test_spatial_index_populated(self) -> None:
        graph = _make_graph()
        assert "landmark" in graph._spatial_index
        assert len(graph._spatial_index["landmark"]) == 3  # Eiffel, Notre-Dame, Tokyo


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


class TestRelations:
    """Tests for relation add / get."""

    def test_add_and_get_relation(self) -> None:
        graph = _make_graph()
        rel = SpatialRelation(
            source_id="paris",
            target_id="eiffel",
            relation_type="contains",
        )
        graph.add_relation(rel)
        assert graph.relation_count == 1
        rels = graph.get_relations("paris")
        assert len(rels) == 1
        assert rels[0].relation_type == "contains"

    def test_get_relations_as_target(self) -> None:
        graph = _make_graph()
        rel = SpatialRelation(
            source_id="paris",
            target_id="eiffel",
            relation_type="contains",
        )
        graph.add_relation(rel)
        # Entity appears as target
        rels = graph.get_relations("eiffel")
        assert len(rels) == 1

    def test_get_relations_filtered_by_type(self) -> None:
        graph = _make_graph()
        graph.add_relation(SpatialRelation(
            source_id="paris", target_id="eiffel", relation_type="contains",
        ))
        graph.add_relation(SpatialRelation(
            source_id="eiffel", target_id="louvre", relation_type="near",
        ))
        rels = graph.get_relations("eiffel", relation_type="near")
        assert len(rels) == 1
        assert rels[0].relation_type == "near"

    def test_add_relation_missing_source_raises(self) -> None:
        graph = _make_graph()
        with pytest.raises(ValueError, match="Source entity"):
            graph.add_relation(SpatialRelation(
                source_id="nonexistent",
                target_id="eiffel",
                relation_type="near",
            ))

    def test_add_relation_missing_target_raises(self) -> None:
        graph = _make_graph()
        with pytest.raises(ValueError, match="Target entity"):
            graph.add_relation(SpatialRelation(
                source_id="eiffel",
                target_id="nonexistent",
                relation_type="near",
            ))


# ---------------------------------------------------------------------------
# Spatial queries -- find_entities
# ---------------------------------------------------------------------------


class TestFindEntities:
    """Tests for find_entities with type and proximity filters."""

    def test_find_by_type(self) -> None:
        graph = _make_graph()
        landmarks = graph.find_entities(entity_type="landmark")
        assert len(landmarks) == 3

    def test_find_by_type_no_match(self) -> None:
        graph = _make_graph()
        result = graph.find_entities(entity_type="airport")
        assert result == []

    def test_find_near_point(self) -> None:
        graph = _make_graph()
        near_eiffel = {"type": "Point", "coordinates": [2.2945, 48.8584]}
        # All Paris entities within 10 km, no type filter
        results = graph.find_entities(near=near_eiffel, radius_m=10_000)
        names = {e.name for e in results}
        assert "Eiffel Tower" in names
        assert "Louvre Museum" in names
        assert "Tokyo Tower" not in names

    def test_find_near_with_type_filter(self) -> None:
        graph = _make_graph()
        near_eiffel = {"type": "Point", "coordinates": [2.2945, 48.8584]}
        hospitals = graph.find_entities(
            entity_type="hospital", near=near_eiffel, radius_m=10_000,
        )
        assert len(hospitals) == 1
        assert hospitals[0].name == "Hopital Necker"

    def test_find_sorted_by_distance(self) -> None:
        graph = _make_graph()
        near_eiffel = {"type": "Point", "coordinates": [2.2945, 48.8584]}
        results = graph.find_entities(
            entity_type="landmark", near=near_eiffel, radius_m=10_000,
        )
        # Should include Paris landmarks but not Tokyo
        assert len(results) == 2  # Eiffel, Notre-Dame (not Tokyo)
        # First result should be Eiffel Tower (distance ~0)
        assert results[0].id == "eiffel"


# ---------------------------------------------------------------------------
# Query parser
# ---------------------------------------------------------------------------


class TestQueryParser:
    """Tests for the simple natural-language query parser."""

    def test_query_type_near_entity(self) -> None:
        graph = _make_graph()
        graph.add_relation(SpatialRelation(
            source_id="paris", target_id="hospital_paris", relation_type="contains",
        ))
        # "hospitals near Paris" -- finds hospital entities near the Paris entity
        results = graph.query("hospital near Paris")
        assert len(results) == 1
        assert results[0].name == "Hopital Necker"

    def test_query_type_only(self) -> None:
        graph = _make_graph()
        results = graph.query("landmark")
        assert len(results) == 3

    def test_query_no_reference_found(self) -> None:
        graph = _make_graph()
        results = graph.query("hospital near Berlin")
        assert results == []


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------


class TestGraphTraversal:
    """Tests for shortest_path and neighbors."""

    def _graph_with_chain(self) -> SpatialKnowledgeGraph:
        """Build a graph: paris -> eiffel -> louvre -> notre_dame."""
        graph = _make_graph()
        graph.add_relation(SpatialRelation(
            source_id="paris", target_id="eiffel", relation_type="contains",
        ))
        graph.add_relation(SpatialRelation(
            source_id="eiffel", target_id="louvre", relation_type="near",
        ))
        graph.add_relation(SpatialRelation(
            source_id="louvre", target_id="notre_dame", relation_type="near",
        ))
        return graph

    def test_shortest_path_direct(self) -> None:
        graph = self._graph_with_chain()
        path = graph.shortest_path("paris", "eiffel")
        assert path == ["paris", "eiffel"]

    def test_shortest_path_multi_hop(self) -> None:
        graph = self._graph_with_chain()
        path = graph.shortest_path("paris", "notre_dame")
        assert path == ["paris", "eiffel", "louvre", "notre_dame"]

    def test_shortest_path_no_path(self) -> None:
        graph = self._graph_with_chain()
        # Tokyo Tower has no relations
        path = graph.shortest_path("paris", "tokyo_tower")
        assert path == []

    def test_shortest_path_same_node(self) -> None:
        graph = self._graph_with_chain()
        path = graph.shortest_path("paris", "paris")
        assert path == ["paris"]

    def test_shortest_path_missing_entity(self) -> None:
        graph = self._graph_with_chain()
        path = graph.shortest_path("paris", "nonexistent")
        assert path == []

    def test_neighbors_depth_1(self) -> None:
        graph = self._graph_with_chain()
        nbs = graph.neighbors("eiffel", depth=1)
        nb_ids = {e.id for e in nbs}
        assert nb_ids == {"paris", "louvre"}

    def test_neighbors_depth_2(self) -> None:
        graph = self._graph_with_chain()
        nbs = graph.neighbors("eiffel", depth=2)
        nb_ids = {e.id for e in nbs}
        assert "notre_dame" in nb_ids
        assert "paris" in nb_ids
        assert "louvre" in nb_ids

    def test_neighbors_missing_entity(self) -> None:
        graph = self._graph_with_chain()
        assert graph.neighbors("nonexistent") == []


# ---------------------------------------------------------------------------
# Auto-relate
# ---------------------------------------------------------------------------


class TestAutoRelate:
    """Tests for auto-discovered spatial relations."""

    def test_auto_relate_discovers_near(self) -> None:
        graph = _make_graph()
        added = graph.auto_relate(max_distance_m=10_000)
        # Paris landmarks are all within ~5 km of each other
        assert added > 0
        near_rels = [r for r in graph._relations if r.relation_type == "near"]
        assert len(near_rels) > 0

    def test_auto_relate_discovers_contains(self) -> None:
        graph = _make_graph()
        graph.auto_relate(max_distance_m=20_000)
        contains_rels = [r for r in graph._relations if r.relation_type == "contains"]
        # Paris polygon should contain the Paris-based point entities
        assert len(contains_rels) >= 1
        source_ids = {r.source_id for r in contains_rels}
        assert "paris" in source_ids

    def test_auto_relate_no_duplicate(self) -> None:
        graph = _make_graph()
        graph.auto_relate(max_distance_m=10_000)
        second_run = graph.auto_relate(max_distance_m=10_000)
        assert second_run == 0  # No new relations on second run


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    """Tests for to_dict / from_dict round-trip."""

    def test_round_trip(self) -> None:
        graph = _make_graph()
        graph.add_relation(SpatialRelation(
            source_id="paris", target_id="eiffel", relation_type="contains",
        ))
        data = graph.to_dict()
        restored = SpatialKnowledgeGraph.from_dict(data)
        assert restored.entity_count == graph.entity_count
        assert restored.relation_count == graph.relation_count
        assert restored.get_entity("eiffel").name == "Eiffel Tower"

    def test_to_dict_is_json_serialisable(self) -> None:
        graph = _make_graph()
        data = graph.to_dict()
        dumped = json.dumps(data)
        assert len(dumped) > 0

    def test_from_dict_empty(self) -> None:
        graph = SpatialKnowledgeGraph.from_dict({"entities": [], "relations": []})
        assert graph.entity_count == 0
        assert graph.relation_count == 0


# ---------------------------------------------------------------------------
# GeoJSONLoader
# ---------------------------------------------------------------------------


class TestGeoJSONLoader:
    """Tests for loading GeoJSON into the knowledge graph."""

    GEOJSON_FC: ClassVar[dict] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "feat_1",
                "geometry": {"type": "Point", "coordinates": [2.3, 48.86]},
                "properties": {"name": "Place A", "category": "park"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.35, 48.85]},
                "properties": {"name": "Place B"},
            },
        ],
    }

    def test_load_feature_collection(self) -> None:
        loader = GeoJSONLoader()
        entities = loader.load(self.GEOJSON_FC, entity_type="poi")
        assert len(entities) == 2

    def test_feature_id_assignment(self) -> None:
        loader = GeoJSONLoader()
        entities = loader.load(self.GEOJSON_FC)
        ids = [e.id for e in entities]
        assert "feat_1" in ids
        # Second feature has no ID, should get a hash-based ID
        assert all(isinstance(i, str) and len(i) > 0 for i in ids)

    def test_entity_type_from_property(self) -> None:
        loader = GeoJSONLoader()
        entities = loader.load(self.GEOJSON_FC, entity_type="poi")
        types = {e.entity_type for e in entities}
        # First feature has category "park", second falls back to "poi"
        assert "park" in types
        assert "poi" in types

    def test_load_single_feature(self) -> None:
        single = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"name": "Origin"},
        }
        loader = GeoJSONLoader()
        entities = loader.load(single)
        assert len(entities) == 1
        assert entities[0].name == "Origin"

    def test_load_bare_geometry(self) -> None:
        bare = {"type": "Point", "coordinates": [1.0, 2.0]}
        loader = GeoJSONLoader()
        entities = loader.load(bare)
        assert len(entities) == 1
        assert entities[0].geometry["type"] == "Point"

    def test_load_into_graph(self) -> None:
        loader = GeoJSONLoader()
        entities = loader.load(self.GEOJSON_FC, entity_type="poi")
        graph = SpatialKnowledgeGraph()
        for e in entities:
            graph.add_entity(e)
        assert graph.entity_count == 2
