"""Tests for GeoSpark Protocol schema."""

from geospark.protocol.schema import (
    BBox,
    Point,
    SpatialFeature,
    SpatialFilter,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
    TemporalFilter,
)


class TestPoint:
    def test_create_point(self):
        p = Point(coordinates=(10.0, 20.0))
        assert p.coordinates == (10.0, 20.0)
        assert p.type.value == "Point"

    def test_from_latlon(self):
        p = Point.from_latlon(lat=51.5074, lon=-0.1278)
        assert p.coordinates == (-0.1278, 51.5074)  # lon, lat order


class TestBBox:
    def test_create_bbox(self):
        bbox = BBox(min_lon=-10, min_lat=40, max_lon=10, max_lat=60)
        assert bbox.to_tuple() == (-10, 40, 10, 60)


class TestSpatialQuery:
    def test_create_simple_query(self):
        q = SpatialQuery(
            operation=SpatialOperation.FIND_WITHIN,
            geometry=Point.from_latlon(51.5074, -0.1278),
            radius_m=5000,
        )
        assert q.operation == SpatialOperation.FIND_WITHIN
        assert q.radius_m == 5000
        assert q.crs == "EPSG:4326"

    def test_query_with_filters(self):
        q = SpatialQuery(
            operation=SpatialOperation.FIND_WITHIN,
            geometry=Point.from_latlon(51.5074, -0.1278),
            radius_m=10000,
            filters=SpatialFilter(category="hospital"),
        )
        assert q.filters.category == "hospital"

    def test_query_with_temporal_filter(self):
        from datetime import datetime

        q = SpatialQuery(
            operation=SpatialOperation.CHANGE_DETECTION,
            filters=SpatialFilter(
                temporal=TemporalFilter(
                    after=datetime(2020, 1, 1),
                    before=datetime(2025, 1, 1),
                )
            ),
        )
        assert q.filters.temporal.after.year == 2020


class TestSpatialResult:
    def test_empty_result(self):
        r = SpatialResult()
        assert r.is_empty
        assert len(r.features) == 0

    def test_result_with_features(self):
        r = SpatialResult(
            features=[
                SpatialFeature(
                    geometry={"type": "Point", "coordinates": [0, 0]},
                    properties={"name": "Test"},
                )
            ],
        )
        assert not r.is_empty
        assert r.features[0].properties["name"] == "Test"

    def test_to_geojson(self):
        r = SpatialResult(
            features=[
                SpatialFeature(
                    geometry={"type": "Point", "coordinates": [0, 0]},
                    properties={"name": "Test"},
                    id="1",
                )
            ],
        )
        geojson = r.to_geojson()
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1
        assert geojson["features"][0]["type"] == "Feature"
