"""Verifiable answers: provenance, units, quality flags, warnings, and refusing bad input."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from geospark import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.protocol import Provenance, SpatialOperation, SpatialQuery
from geospark.protocol.schema import SpatialFeature, SpatialResult

EIFFEL = {"type": "Point", "coordinates": [2.2945, 48.8584]}
LOUVRE = {"type": "Point", "coordinates": [2.3376, 48.8606]}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
# Melbourne typed as [lat, lon]: latitude -37.8 lands in the longitude slot, 144.9 in latitude
SWAPPED = {"type": "Polygon", "coordinates": [[[-37.8, 144.9], [-37.8, 145.0], [-37.7, 145.0], [-37.8, 144.9]]]}


def by_source(result, source: str) -> Provenance:
    return next(p for p in result.provenance if p.source == source)


# --- Provenance and units -------------------------------------------------------------

def test_computed_answer_says_how_it_was_computed() -> None:
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.DISTANCE, geometry=EIFFEL,
                                           metadata={"geometry_b": LOUVRE}))
    assert result.status == "ok"
    engine = by_source(result, "geospark-engine")
    assert "Geodesic" in engine.method and "WGS84" in engine.method
    assert "pyproj" in engine.dataset_version and "GEOS" in engine.dataset_version
    assert engine.licence == "Apache-2.0" and engine.retrieved_at is None
    assert result.spatial_context.units == {"distance_m": "metre", "distance_km": "kilometre"}


def test_buffer_units_and_method() -> None:
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.BUFFER, geometry=EIFFEL, radius_m=100))
    assert result.spatial_context.units["area_sq_m"] == "square metre"
    assert "azimuthal equidistant" in by_source(result, "geospark-engine").method


def test_geocoding_cites_openstreetmap_with_licence_and_time() -> None:
    payload = {"features": [{"geometry": {"type": "Point", "coordinates": [144.969, -37.818]},
                             "properties": {"display_name": "Federation Square, Melbourne, Australia",
                                            "importance": 0.41}}]}
    with patch("geospark.tools.geocoding.client.get_json", return_value=payload):
        result = Engine(tools=["geocoder"]).execute(
            SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Federation Square"}))
    osm = by_source(result, "openstreetmap-nominatim")
    assert osm.licence == "ODbL-1.0" and "OpenStreetMap contributors" in osm.attribution
    assert osm.retrieved_at is not None
    assert result.quality["match_importance"] == 0.41 and not result.warnings


def test_ambiguous_place_name_is_flagged() -> None:
    payload = {"features": [
        {"geometry": {"type": "Point", "coordinates": [2.35, 48.86]},
         "properties": {"display_name": "Paris, Île-de-France, France", "importance": 0.80}},
        {"geometry": {"type": "Point", "coordinates": [-95.55, 33.66]},
         "properties": {"display_name": "Paris, Lamar County, Texas, United States", "importance": 0.78}},
    ]}
    with patch("geospark.tools.geocoding.client.get_json", return_value=payload):
        result = Engine(tools=["geocoder"]).execute(
            SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Paris"}))
    assert any("Ambiguous" in w and "Texas" in w for w in result.warnings)
    assert result.quality["candidates"] == 2


@pytest.mark.parametrize(("source", "accuracy"), [("copernicus-dem", 4.0), ("open-elevation-api", 16.0)])
def test_elevation_reports_vertical_accuracy_and_datum(source: str, accuracy: float) -> None:
    from geospark.tools.terrain.elevation import ElevationTool

    raw = ElevationTool._elevation_result(-37.8177, 144.9691, 23.1, source, None)
    from geospark.protocol.provenance import enrich

    result = enrich(raw, "elevation")
    assert result.quality["vertical_accuracy_le90_m"] == accuracy
    assert result.quality["vertical_datum"]
    assert by_source(result, source).name
    assert result.spatial_context.units["elevation_m"] == "metre"


def test_data_channel_results_carry_provenance_and_keep_their_fetch_time() -> None:
    from geospark.data_channels.base import ChannelResult

    result = ChannelResult(channel="weather", source="open-meteo", features=[{"t": 1}], total_results=1)
    provenance = result.provenance[0]
    assert provenance.licence == "CC-BY-4.0" and provenance.retrieved_at == result.timestamp
    assert ChannelResult(channel="weather", errors=["down"]).provenance == []


# --- Warnings -----------------------------------------------------------------------------

def test_large_geometry_topology_warning() -> None:
    big = {"type": "Polygon", "coordinates": [[[100, -40], [155, -40], [155, -10], [100, -10], [100, -40]]]}
    point = {"type": "Point", "coordinates": [144.96, -37.81]}
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.CONTAINS, geometry=big,
                                           metadata={"geometry_b": point}))
    assert result.status == "ok"
    assert any("geodesic" in w for w in result.warnings)


def test_small_geometry_topology_has_no_warning() -> None:
    park = {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]]}
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.CONTAINS, geometry=park,
                                           metadata={"geometry_b": {"type": "Point", "coordinates": [2.295, 48.855]}}))
    assert result.warnings == []


# --- Refusing to guess -----------------------------------------------------------------------

def test_invalid_polygon_is_refused_not_measured() -> None:
    """A bow-tie polygon's area used to come back as ~0: a confident wrong answer."""
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.AREA, geometry=BOWTIE))
    assert result.status == "cannot_answer"
    assert "Self-intersection" in result.errors[0] and "make_valid" in result.errors[0]


def test_lat_lon_swap_is_explained() -> None:
    result = Engine().execute(SpatialQuery(operation=SpatialOperation.AREA, geometry=SWAPPED))
    assert result.status == "cannot_answer"
    assert "[latitude, longitude]" in result.errors[0]


def test_direct_helpers_refuse_bad_input_too() -> None:
    with pytest.raises(ValueError, match="Self-intersection"):
        SpatialReasoner.check_relationship(BOWTIE, EIFFEL, "contains")
    with pytest.raises(ValueError, match="latitude"):
        SpatialReasoner.calculate_distance({"type": "Point", "coordinates": [48.8584, 182.0]}, EIFFEL)
    with pytest.raises(ValueError, match="empty"):
        SpatialReasoner.calculate_distance({"type": "Point", "coordinates": []}, EIFFEL)


def test_status_values() -> None:
    feature = SpatialFeature(geometry=EIFFEL)
    assert SpatialResult(features=[feature]).status == "ok"
    assert SpatialResult(features=[feature], errors=["one source failed"]).status == "partial"
    assert SpatialResult(errors=["no answer"]).status == "cannot_answer"
    assert SpatialResult().model_dump()["status"] == "ok"  # serialised for API and MCP clients


# --- What MCP clients and REST clients see --------------------------------------------------

def test_mcp_distance_reply_is_verifiable() -> None:
    out = MCPServerLauncher().handle_tool_call(
        "calculate_distance", {"explanation": "t", "point_a": EIFFEL, "point_b": LOUVRE})
    meta = out["metadata"]
    assert meta["status"] == "ok" and meta["units"]["distance_m"] == "metre"
    assert meta["provenance"][0]["source"] == "geospark-engine"


def test_mcp_relationship_refuses_invalid_geometry() -> None:
    out = MCPServerLauncher().handle_tool_call(
        "check_spatial_relationship",
        {"explanation": "t", "geometry_a": BOWTIE, "geometry_b": EIFFEL, "relationship": "contains"})
    assert out["status"] == "error"
    assert "Self-intersection" in out["error"]["message"]


def test_mcp_distance_explains_swapped_point() -> None:
    out = MCPServerLauncher().handle_tool_call(
        "calculate_distance",
        {"explanation": "t", "point_a": {"type": "Point", "coordinates": [-37.81, 144.96]}, "point_b": EIFFEL})
    assert out["status"] == "error" and "[latitude, longitude]" in out["error"]["message"]


@pytest.fixture
def api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from geospark.api import app

    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    return TestClient(app)


def test_rest_distance_includes_provenance(api) -> None:
    body = api.post("/api/v1/distance", json={"lat_a": 48.8584, "lon_a": 2.2945, "lat_b": 48.8606, "lon_b": 2.3376}).json()
    assert body["units"]["distance_m"] == "metre"
    assert body["provenance"][0]["method"].startswith("Geodesic")


def test_rest_relationship_refuses_bowtie_with_reason(api) -> None:
    resp = api.post("/api/v1/check-relationship",
                    json={"geometry_a": BOWTIE, "geometry_b": EIFFEL, "relationship": "contains"})
    assert resp.status_code == 400 and "Self-intersection" in resp.json()["detail"]


def test_location_report_lists_its_sources() -> None:
    from geospark.agents.spatial_report import SpatialReport, WeatherSnapshot

    class Launcher:
        def handle_tool_call(self, name, args):
            if name == "geocode":
                return {"status": "success", "result": {"features": [{
                    "geometry": {"type": "Point", "coordinates": [144.969, -37.818]},
                    "properties": {"display_name": "Federation Square"}}]}}
            return {"status": "success", "result": {"elevation_m": 23.1}, "metadata": {"source": "copernicus-dem"}}

    class Overpass:
        def load_amenities_by_type(self, bbox, services, timeout=None):
            return {}

    report = SpatialReport.__new__(SpatialReport)
    report.__init__()
    report._launcher, report._overpass = Launcher(), Overpass()
    with patch.object(SpatialReport, "_fetch_weather", return_value=WeatherSnapshot(temperature_c=20.0)), \
         patch.object(SpatialReport, "_fetch_air_quality", return_value=None), \
         patch("httpx.post", side_effect=ConnectionError("no LLM")):
        result = report.analyze("Federation Square", radius_m=500)
    sources = [p.source for p in result.provenance]
    assert sources[:4] == ["openstreetmap-nominatim", "copernicus-dem", "open-meteo", "openstreetmap-overpass"]
    assert "openaq" not in sources  # not used, so not cited


def test_rest_elevation_includes_accuracy_and_provenance(api) -> None:
    from geospark.tools.terrain.elevation import ElevationTool

    raw = ElevationTool._elevation_result(-37.8177, 144.9691, 23.1, "copernicus-dem", "© DLR")
    with patch("geospark.tools.terrain.elevation.ElevationTool.execute", return_value=raw):
        body = api.post("/api/v1/elevation", json={"latitude": -37.8177, "longitude": 144.9691}).json()
    assert body["elevation_m"] == 23.1  # existing fields unchanged
    assert body["quality"]["vertical_accuracy_le90_m"] == 4.0
    assert body["provenance"][0]["source"] == "copernicus-dem"
    assert body["units"] == {"elevation_m": "metre"}


def _geocode_result(candidates):
    from geospark.protocol.provenance import enrich

    features = [SpatialFeature(geometry={"type": "Point", "coordinates": list(lonlat)},
                               properties={"display_name": name, "importance": imp})
                for name, lonlat, imp in candidates]
    return enrich(SpatialResult(features=features, sources=["openstreetmap-nominatim"]), "geocode")


def test_same_name_same_country_far_apart_is_ambiguous() -> None:
    """Real Nominatim scores for 'Springfield' (2026-10-22): five US cities within 0.12."""
    result = _geocode_result([
        ("Springfield, Sangamon County, Illinois, United States", (-89.6501, 39.7990), 0.613),
        ("Springfield, Hampden County, Massachusetts, United States", (-72.5898, 42.1015), 0.611),
        ("Springfield, Greene County, Missouri, United States", (-93.2923, 37.2090), 0.596),
    ])
    assert result.quality["ambiguous"] is True
    assert "Illinois" in result.warnings[0] and "Massachusetts" in result.warnings[0]


def test_near_equal_candidates_close_together_are_not_ambiguous() -> None:
    """Two entries for the same square (e.g. the plaza and its precinct) are one place."""
    result = _geocode_result([
        ("Federation Square, Melbourne", (144.9691, -37.8177), 0.41),
        ("Federation Square precinct, Melbourne", (144.9700, -37.8170), 0.40),
    ])
    assert not result.warnings and "ambiguous" not in result.quality
