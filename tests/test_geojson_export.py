"""QGIS-ready GeoJSON: RFC 7946 output that GDAL (QGIS's reader) opens with the right CRS and fields."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from geospark import Engine
from geospark.protocol import SpatialOperation, SpatialQuery
from geospark.protocol.provenance import enrich, source_provenance
from geospark.protocol.schema import SpatialFeature, SpatialResult

NOMINATIM = {"features": [
    {"geometry": {"type": "Point", "coordinates": [144.9691, -37.8177]},
     "properties": {"display_name": "Federation Square, Melbourne, Australia", "importance": 0.41, "type": "square"}},
    {"geometry": {"type": "Point", "coordinates": [144.9631, -37.8136]},
     "properties": {"display_name": "Melbourne Town Hall, Melbourne, Australia", "importance": 0.20, "type": "townhall"}},
]}


def read_columns(path) -> dict:
    """Attribute columns exactly as GDAL reads them (what QGIS shows in the attribute table)."""
    from pyogrio.raw import read

    meta, _fids, _geometry, field_data = read(path)
    return dict(zip(meta["fields"], field_data, strict=True))


def geocoded() -> SpatialResult:
    with patch("geospark.tools.geocoding.client.get_json", return_value=NOMINATIM):
        return Engine(tools=["geocoder"]).execute(
            SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Federation Square"}))


def test_feature_collection_follows_rfc_7946() -> None:
    fc = geocoded().to_geojson()
    assert fc["type"] == "FeatureCollection"
    assert "crs" not in fc  # RFC 7946 removed it: coordinates are always WGS84 lon/lat
    assert fc["bbox"] == pytest.approx([144.9631, -37.8177, 144.9691, -37.8136])
    first = fc["features"][0]
    assert first["type"] == "Feature" and "id" not in first  # no null ids
    assert first["properties"]["display_name"].startswith("Federation Square")
    assert "OpenStreetMap contributors" in first["properties"]["attribution"]
    meta = fc["geospark"]
    assert meta["status"] == "ok" and meta["provenance"][0]["licence"] == "ODbL-1.0"
    json.dumps(fc)  # fully serialisable


def test_values_are_json_safe() -> None:
    when = datetime(2026, 10, 22, tzinfo=timezone.utc)
    fc = SpatialResult(features=[SpatialFeature(geometry={"type": "Point", "coordinates": [0, 0]},
                                                properties={"observed_at": when})]).to_geojson()
    assert fc["features"][0]["properties"]["observed_at"] == "2026-10-22T00:00:00+00:00"


def test_gdal_reads_it_like_qgis(tmp_path) -> None:
    pyogrio = pytest.importorskip("pyogrio")
    path = tmp_path / "places.geojson"
    path.write_text(json.dumps(geocoded().to_geojson()))
    info = pyogrio.read_info(path)
    assert info["features"] == 2
    assert info["crs"] == "EPSG:4326"
    assert info["geometry_type"] == "Point"
    assert {"display_name", "importance", "attribution"} <= set(info["fields"])
    columns = read_columns(path)
    assert columns["importance"].dtype.kind == "f"  # numbers stay numeric columns


def test_computed_polygon_opens_in_gdal(tmp_path) -> None:
    pyogrio = pytest.importorskip("pyogrio")
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.BUFFER,
                                           geometry={"type": "Point", "coordinates": [2.2945, 48.8584]},
                                           radius_m=250))
    path = tmp_path / "buffer.geojson"
    path.write_text(json.dumps(result.to_geojson()))
    info = pyogrio.read_info(path)
    assert info["geometry_type"] == "Polygon" and "area_sq_m" in info["fields"]


def test_location_report_as_a_map_layer(tmp_path) -> None:
    pytest.importorskip("pyogrio")
    from geospark.agents.spatial_report import LocationReport, NearbyItem, WeatherSnapshot

    report = LocationReport(
        query="Federation Square", coordinates=[144.9691, -37.8177], address="Federation Square",
        elevation_m=23.1, weather=WeatherSnapshot(temperature_c=21.5, conditions="Clear sky"),
        nearby=[NearbyItem(name="Flinders St Pharmacy", amenity_type="pharmacy", distance_m=140,
                           coordinates=[144.9672, -37.8183])],
        radius_m=1000, data_gaps=["air quality"],
        provenance=[source_provenance("openstreetmap-overpass")],
    )
    fc = report.to_geojson()
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert kinds == ["location", "amenity"]
    assert fc["features"][0]["properties"]["weather_temperature_c"] == 21.5
    assert fc["geospark"]["warnings"] == ["No data: air quality"]
    path = tmp_path / "report.geojson"
    path.write_text(json.dumps(fc))
    columns = read_columns(path)
    assert list(columns["kind"]) == ["location", "amenity"]
    assert columns["distance_m"][1] == 140


def test_cloud_cover_flag_and_warning() -> None:
    scenes = SpatialResult(features=[
        SpatialFeature(geometry={"type": "Point", "coordinates": [0, 0]}, properties={"cloud_cover": c})
        for c in (72.0, 88.5)
    ])
    enrich(scenes, "satellite_view")
    assert scenes.quality["cloud_cover_pct"] == {"min": 72.0, "max": 88.5}
    assert any("cloud" in w for w in scenes.warnings)


# --- REST ---------------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from geospark.api import app

    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    return TestClient(app)


def test_rest_geojson_by_query_parameter(api) -> None:
    with patch("geospark.tools.geocoding.client.get_json", return_value=NOMINATIM):
        resp = api.post("/api/v1/geocode?format=geojson", json={"query": "Federation Square"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/geo+json")
    assert resp.json()["type"] == "FeatureCollection"


def test_rest_geojson_by_accept_header(api) -> None:
    with patch("geospark.tools.geocoding.client.get_json", return_value=NOMINATIM):
        resp = api.post("/api/v1/geocode", json={"query": "Federation Square"},
                        headers={"Accept": "application/geo+json"})
    assert resp.json()["type"] == "FeatureCollection"


def test_rest_default_stays_json(api) -> None:
    with patch("geospark.tools.geocoding.client.get_json", return_value=NOMINATIM):
        body = api.post("/api/v1/geocode", json={"query": "Federation Square"}).json()
    assert "features" in body and "type" not in body  # the existing SpatialResult shape


def test_rest_rejects_unknown_format(api) -> None:
    assert api.post("/api/v1/geocode?format=kml", json={"query": "x"}).status_code == 422


# --- CLI ------------------------------------------------------------------------------------------


def test_cli_geojson_file(tmp_path) -> None:
    pyogrio = pytest.importorskip("pyogrio")
    from geospark.cli import main

    out = tmp_path / "fedsq.geojson"
    with patch("geospark.tools.geocoding.client.get_json", return_value=NOMINATIM):
        result = CliRunner().invoke(main, ["geocode", "Federation Square", "--geojson", str(out)])
    assert result.exit_code == 0, result.output
    assert "OpenStreetMap contributors" in result.output  # attribution shown in the terminal too
    assert pyogrio.read_info(out)["features"] == 2
