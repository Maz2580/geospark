"""Isochrones and travel-time matrices (Valhalla): parsing, geodesic areas, repairs, policy."""

from __future__ import annotations

import json

import httpx
import pytest
from pyproj import Geod

from geospark.tools.routing import valhalla

GEOD = Geod(ellps="WGS84")
FED_SQ = (-37.8180, 144.9691)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("GEOSPARK_VALHALLA_URL", raising=False)
    monkeypatch.delenv("GEOSPARK_ENV", raising=False)
    valhalla.reset()
    yield
    valhalla.reset()


def square(lat: float, lon: float, half_m: float) -> list[list[float]]:
    north = GEOD.fwd(lon, lat, 0, half_m)[1]
    south = GEOD.fwd(lon, lat, 180, half_m)[1]
    east = GEOD.fwd(lon, lat, 90, half_m)[0]
    west = GEOD.fwd(lon, lat, 270, half_m)[0]
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


@pytest.fixture
def server(monkeypatch):
    """A fake Valhalla answering over httpx.MockTransport; records requests."""
    seen: list[httpx.Request] = []
    state = {"handler": None}
    real = httpx.Client

    def transport(request):
        seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real(*a, transport=httpx.MockTransport(transport), **k))

    def use(handler):
        state["handler"] = handler
        return seen

    return use


def iso_response(request):
    body = json.loads(request.content)
    features = [{"type": "Feature", "properties": {"contour": c["time"]},
                 "geometry": {"type": "Polygon", "coordinates": [square(*FED_SQ, 100 * c["time"])]}}
                for c in body["contours"]]
    return httpx.Response(200, json={"type": "FeatureCollection", "features": features})


def test_isochrone_contours_largest_first_with_geodesic_area(server) -> None:
    seen = server(iso_response)
    result = valhalla.isochrone(*FED_SQ, [10, 5], "walk")
    assert [f.properties["minutes"] for f in result.features] == [10.0, 5.0]
    assert result.features[0].properties["area_sq_km"] == pytest.approx(4.0, rel=0.01)  # 2 km x 2 km
    body = json.loads(seen[0].content)
    assert body["costing"] == "pedestrian" and seen[0].url.path == "/isochrone"
    assert seen[0].headers["User-Agent"].startswith("GeoSpark/")
    assert result.spatial_context.units["area_sq_km"] == "square kilometre"
    assert result.provenance[0].name.startswith("Valhalla (FOSSGIS") and "OpenStreetMap" in result.provenance[0].attribution
    assert any("typical speeds" in w for w in result.warnings)


def test_invalid_polygon_is_repaired_and_flagged(server) -> None:
    bowtie = [[144.96, -37.82], [144.98, -37.81], [144.98, -37.82], [144.96, -37.81], [144.96, -37.82]]
    server(lambda r: httpx.Response(200, json={"features": [
        {"properties": {"contour": 10}, "geometry": {"type": "Polygon", "coordinates": [bowtie]}}]}))
    result = valhalla.isochrone(*FED_SQ, [10])
    assert any("repaired" in w for w in result.warnings)
    assert result.features[0].properties["area_sq_km"] > 0


@pytest.mark.parametrize(("minutes", "mode"), [([0], "walk"), ([61], "walk"), ([1, 2, 3, 4, 5], "walk"), ([10], "fly")])
def test_bad_requests_are_refused_before_calling_valhalla(server, minutes, mode) -> None:
    seen = server(iso_response)
    with pytest.raises(ValueError):
        valhalla.isochrone(*FED_SQ, minutes, mode)
    assert seen == []


def test_valhalla_400_becomes_a_clear_error(server) -> None:
    server(lambda r: httpx.Response(400, json={"error": "No suitable edges near location"}))
    with pytest.raises(ValueError, match="No suitable edges"):
        valhalla.isochrone(0.0, -30.0, [10])  # mid-Atlantic


def test_public_server_is_spaced_and_cached(server, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(valhalla.time, "sleep", lambda s: sleeps.append(s))
    seen = server(iso_response)
    valhalla.isochrone(*FED_SQ, [10])
    valhalla.isochrone(*FED_SQ, [15])
    valhalla.isochrone(*FED_SQ, [10])  # cached
    assert len(seen) == 2 and sleeps and sleeps[0] > 0.5


def test_production_refuses_to_use_the_public_demo(monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_ENV", "production")
    with pytest.raises(valhalla.RoutingUnavailableError, match="GEOSPARK_VALHALLA_URL"):
        valhalla.isochrone(*FED_SQ, [10])


def test_configured_server_is_used_without_throttling(server, monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_ENV", "production")
    monkeypatch.setenv("GEOSPARK_VALHALLA_URL", "http://valhalla.internal:8002/")
    sleeps: list[float] = []
    monkeypatch.setattr(valhalla.time, "sleep", lambda s: sleeps.append(s))
    seen = server(iso_response)
    valhalla.isochrone(*FED_SQ, [10])
    valhalla.isochrone(*FED_SQ, [20])
    assert str(seen[0].url) == "http://valhalla.internal:8002/isochrone" and not sleeps
    assert valhalla.isochrone(*FED_SQ, [10]).provenance[0].name == "Valhalla"


def test_travel_time_matrix(server) -> None:
    server(lambda r: httpx.Response(200, json={"sources_to_targets": [[
        {"from_index": 0, "to_index": 0, "time": 744, "distance": 0.981},
        {"from_index": 0, "to_index": 1, "time": None, "distance": None},
    ]]}))
    result = valhalla.travel_time_matrix([FED_SQ], [(-37.8136, 144.9631), (-37.9, 145.5)], "walk")
    first, second = (f.properties for f in result.features)
    assert first["minutes"] == 12.4 and first["network_distance_m"] == 981.0
    assert second["minutes"] is None and any("not connected" in w for w in result.warnings)
    assert result.features[0].geometry["coordinates"][0] == [FED_SQ[1], FED_SQ[0]]  # GeoJSON lon, lat


def test_engine_isochrone_operation(server) -> None:
    from geospark import Engine
    from geospark.protocol import SpatialOperation, SpatialQuery

    server(iso_response)
    result = Engine(tools=["router"]).execute(SpatialQuery(
        operation=SpatialOperation.ISOCHRONE, geometry={"type": "Point", "coordinates": [FED_SQ[1], FED_SQ[0]]},
        metadata={"minutes": [10], "mode": "bike"}))
    assert result.status == "ok" and result.features[0].properties["mode"] == "bike"


def test_rest_isochrone(server, monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from geospark.api import app

    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    server(iso_response)
    client = TestClient(app)
    body = client.post("/api/v1/isochrone?format=geojson", json={"lat": FED_SQ[0], "lon": FED_SQ[1], "minutes": [10]}).json()
    assert body["type"] == "FeatureCollection" and body["features"][0]["properties"]["minutes"] == 10.0
    assert client.post("/api/v1/isochrone", json={"lat": 0, "lon": 0, "mode": "fly"}).status_code == 422
    assert client.post("/api/v1/isochrone", json={"lat": 0, "lon": 0, "minutes": [99]}).status_code == 400
    monkeypatch.setenv("GEOSPARK_ENV", "production")
    monkeypatch.setenv("GEOSPARK_ADMIN_TOKEN", "x" * 30)
    assert client.post("/api/v1/isochrone", json={"lat": 0, "lon": 0}).status_code == 503


@pytest.mark.network
def test_live_public_valhalla() -> None:
    result = valhalla.isochrone(*FED_SQ, [10], "walk")
    assert 0.5 < result.features[0].properties["area_sq_km"] < 3
