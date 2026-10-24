"""Official datum and height conversions: the gap found by testing frontier models (2026-10).

GPT-6.1 and Claude Opus 5.5 applied the GDA94 -> GDA2020 parameters and plate motion to the
millimetre, but height datums and grid-based conversions need national grid files they don't have:
GPT-6.1 declined, Opus 5.5 estimated 0.2-5.3 m off. GeoSpark uses the grids, and refuses PROJ's
silent ballpark fallback (AHD = ellipsoidal height; British National Grid ~124 m off).

These tests run offline (GEOSPARK_PROJ_NETWORK=false): grid-free operations are checked against
the official values; grid-based ones must refuse rather than approximate.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from geospark import geodesy
from geospark.mcp_servers.launcher import MCPServerLauncher

FED_SQ_GDA94_MGA55 = [321242.045, 5812466.767]
FED_SQ_GDA2020_MGA55 = [321242.536, 5812468.239]  # PROJ, GDA94 to GDA2020 (1), stated 0.01 m


def _grid_available(name: str) -> bool:
    """Is a grid already installed or cached here (then the refusal tests don't apply)?"""
    import os

    import pyproj

    dirs = [*pyproj.datadir.get_data_dir().split(os.pathsep), os.environ.get("PROJ_USER_WRITABLE_DIRECTORY", "")]
    return any(d and os.path.exists(os.path.join(d, name)) for d in dirs)


def test_gda94_to_gda2020_matches_the_official_operation() -> None:
    done = geodesy.transform("EPSG:28355", "EPSG:7855", [FED_SQ_GDA94_MGA55])
    e, n = done.coordinates[0]
    assert math.hypot(e - FED_SQ_GDA2020_MGA55[0], n - FED_SQ_GDA2020_MGA55[1]) < 0.002
    assert done.accuracy_m == 0.01 and "GDA94 to GDA2020" in done.method
    assert done.as_dict()["provenance"][0]["source"] == "proj-epsg"


def test_plate_motion_from_itrf2014_at_an_epoch() -> None:
    done = geodesy.transform("EPSG:7912", "EPSG:7843", [[144.9691, -37.8177, 50.0]], epoch=2026.8)
    lon, lat, _ = done.coordinates[0]
    assert abs(lat - -37.817703467) < 1e-8 and abs(lon - 144.969098524) < 1e-8  # ~0.41 m since 2020.0


def test_a_map_projection_is_exact() -> None:
    done = geodesy.transform("EPSG:7844", "EPSG:7855", [[144.9691, -37.8177]])
    assert done.accuracy_m is None and "exact" in done.as_dict()["accuracy_note"]


def test_a_height_never_falls_back_to_ballpark() -> None:
    """Without AUSGeoid2020, PROJ would quietly return AHD = ellipsoidal height (4.7 m off in Melbourne)."""
    if _grid_available("au_ga_AUSGeoid2020_20180201.tif"):
        pytest.skip("AUSGeoid2020 is installed on this machine")
    with pytest.raises(geodesy.GeodesyError, match=r"AUSGeoid2020|grid"):
        geodesy.convert_height(-37.8177, 144.9691, 40.0, "ellipsoidal", "AHD")


def test_british_national_grid_never_falls_back_to_ballpark() -> None:
    if _grid_available("uk_os_OSTN15_NTv2_OSGBtoETRS.tif"):
        pytest.skip("OSTN15 is installed on this machine")
    with pytest.raises(geodesy.GeodesyError, match=r"ballpark|grid"):
        geodesy.transform("EPSG:4258", "EPSG:27700", [[-0.1281, 51.5080]])


@pytest.mark.parametrize("bad", [("ellipsoidal", "AHD2"), ("AHD", "ODN"), ("ellipsoidal", "ellipsoidal")])
def test_height_references_are_checked(bad) -> None:
    with pytest.raises(geodesy.GeodesyError):
        geodesy.convert_height(-37.8, 144.9, 40.0, *bad)


def test_unknown_crs_is_a_clear_error() -> None:
    with pytest.raises(geodesy.GeodesyError, match="Unknown coordinate reference system"):
        geodesy.transform("EPSG:999999", "EPSG:4326", [[0, 0]])


def test_the_ask_tool_returns_the_method_and_accuracy() -> None:
    reply = MCPServerLauncher().handle_tool_call("transform_coordinates", {
        "explanation": "t", "source_crs": "EPSG:28355", "target_crs": "EPSG:7855", "coordinates": [FED_SQ_GDA94_MGA55]})
    assert reply["status"] == "success" and reply["result"]["accuracy_m"] == 0.01
    assert reply["metadata"]["provenance"][0]["source"] == "proj-epsg"


def test_the_ask_tool_reports_a_missing_grid_as_an_error() -> None:
    if _grid_available("au_ga_AUSGeoid2020_20180201.tif"):
        pytest.skip("AUSGeoid2020 is installed on this machine")
    reply = MCPServerLauncher().handle_tool_call("convert_height", {
        "explanation": "t", "latitude": -37.8177, "longitude": 144.9691, "height_m": 40,
        "from_reference": "ellipsoidal", "to_reference": "AHD"})
    assert reply["status"] == "error"


def test_api_endpoints() -> None:
    from geospark import api

    client = TestClient(api.app)
    body = client.post("/api/v1/transform", json={"source_crs": "EPSG:28355", "target_crs": "EPSG:7855",
                                                  "coordinates": [FED_SQ_GDA94_MGA55]}).json()
    assert abs(body["coordinates"][0][0] - FED_SQ_GDA2020_MGA55[0]) < 0.002
    assert client.post("/api/v1/height", json={"latitude": -37.8, "longitude": 144.9, "height_m": 40,
                                                "from_reference": "AHD", "to_reference": "ODN"}).status_code == 400


@pytest.mark.network
def test_with_the_official_grids_the_answers_match(monkeypatch) -> None:
    """Live: downloads AUSGeoid2020 and OSTN15 once (pytest -m network)."""
    monkeypatch.setenv("GEOSPARK_PROJ_NETWORK", "true")
    assert geodesy.convert_height(-37.8177, 144.9691, 40.0, "ellipsoidal", "AHD")["height_m"] == pytest.approx(35.257, abs=0.002)
    e, n = geodesy.transform("EPSG:4258", "EPSG:27700", [[-0.1281, 51.5080]]).coordinates[0]
    assert math.hypot(e - 530004.480, n - 180446.082) < 0.01
