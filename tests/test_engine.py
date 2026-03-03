"""Tests for GeoSpark Engine."""

import pytest
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.engine.crs_handler import CRSHandler
from geospark.protocol.schema import (
    Point,
    SpatialQuery,
    SpatialOperation,
)


class TestEngine:
    def test_create_engine(self):
        engine = Engine()
        assert engine is not None

    def test_execute_buffer(self):
        engine = Engine()
        q = SpatialQuery(
            operation=SpatialOperation.BUFFER,
            geometry=Point.from_latlon(51.5074, -0.1278),
            radius_m=1000,
        )
        result = engine.execute(q)
        assert not result.is_empty
        assert result.features[0].properties["operation"] == "buffer"
        assert result.execution_time_ms is not None

    def test_execute_centroid(self):
        engine = Engine()
        q = SpatialQuery(
            operation=SpatialOperation.CENTROID,
            geometry=Point.from_latlon(51.5074, -0.1278),
        )
        result = engine.execute(q)
        assert not result.is_empty

    def test_unknown_operation(self):
        """Tools not loaded should return an error."""
        engine = Engine()
        q = SpatialQuery(
            operation=SpatialOperation.GEOCODE,
            metadata={"query": "London"},
        )
        result = engine.execute(q)
        assert len(result.errors) > 0


class TestSpatialReasoner:
    def test_check_relationship_contains(self):
        # A large polygon contains a point inside it
        polygon = {
            "type": "Polygon",
            "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
        }
        point = {"type": "Point", "coordinates": [0, 0]}

        assert SpatialReasoner.check_relationship(polygon, point, "contains") is True
        assert SpatialReasoner.check_relationship(polygon, point, "disjoint") is False

    def test_check_relationship_disjoint(self):
        point_a = {"type": "Point", "coordinates": [0, 0]}
        point_b = {"type": "Point", "coordinates": [10, 10]}

        assert SpatialReasoner.check_relationship(point_a, point_b, "disjoint") is True
        assert SpatialReasoner.check_relationship(point_a, point_b, "intersects") is False


class TestCRSHandler:
    def test_validate_coordinates_valid(self):
        handler = CRSHandler()
        assert handler.validate_coordinates(0, 0) is True
        assert handler.validate_coordinates(-180, -90) is True
        assert handler.validate_coordinates(180, 90) is True

    def test_validate_coordinates_invalid(self):
        handler = CRSHandler()
        assert handler.validate_coordinates(200, 0) is False
        assert handler.validate_coordinates(0, 100) is False

    def test_suggest_utm_zone(self):
        handler = CRSHandler()
        # London is in UTM zone 30N
        utm = handler.suggest_utm_zone(-0.1278, 51.5074)
        assert utm == "EPSG:32630"

    def test_get_crs_info(self):
        handler = CRSHandler()
        info = handler.get_crs_info("EPSG:4326")
        assert info["code"] == "EPSG:4326"
        assert info["type"] == "geographic"
