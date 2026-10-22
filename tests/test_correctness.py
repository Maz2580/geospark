"""Correctness tests: geometry, CRS, honest results, and API responsiveness."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon, mapping

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import SpatialOperation, SpatialQuery
from geospark.utils.aio import run_sync
from geospark.utils.geo import overpass_bbox

GEOD = Geod(ellps="WGS84")


def _geodesic_area_perimeter(geom) -> tuple[float, float]:
    area, perimeter = GEOD.geometry_area_perimeter(geom)
    return abs(area), perimeter


def _square(lon: float, lat: float, side_m: float) -> Polygon:
    """An (approximately) side_m x side_m square whose SW corner is (lon, lat)."""
    east, _, _ = GEOD.fwd(lon, lat, 90, side_m)
    _, north, _ = GEOD.fwd(lon, lat, 0, side_m)
    return Polygon([(lon, lat), (east, lat), (east, north), (lon, north)])


# --- Buffer ---------------------------------------------------------------------


@pytest.mark.parametrize("lat", [0.0, -37.8, 60.0])
def test_polygon_buffer_keeps_its_shape(lat: float) -> None:
    """Buffering a convex polygon by r adds exactly perimeter*r + pi*r^2 of area.

    The old implementation drew a circle round the centroid, ignoring the polygon.
    """
    square = _square(144.97, lat, 1000)
    area, perimeter = _geodesic_area_perimeter(square)
    buffered = SpatialReasoner.geodesic_buffer(square, 100)
    expected = area + perimeter * 100 + math.pi * 100**2
    got, _ = _geodesic_area_perimeter(buffered)
    assert got == pytest.approx(expected, rel=0.005)
    assert buffered.contains(square)


def test_line_buffer_is_a_corridor_not_a_circle() -> None:
    start = (144.95, -37.81)
    end_lon, end_lat, _ = GEOD.fwd(*start, 90, 2000)
    line = LineString([start, (end_lon, end_lat)])
    got, _ = _geodesic_area_perimeter(SpatialReasoner.geodesic_buffer(line, 100))
    expected = 2000 * 200 + math.pi * 100**2  # corridor plus two round caps
    assert got == pytest.approx(expected, rel=0.005)


def test_point_buffer_is_a_geodesic_circle() -> None:
    center = (2.2945, 48.8584)
    ring = SpatialReasoner.geodesic_buffer(Point(center), 500).exterior.coords
    distances = [GEOD.inv(*center, x, y)[2] for x, y in ring]
    assert max(abs(d - 500) for d in distances) < 1.0


def test_zero_radius_buffer_is_unchanged() -> None:
    square = _square(0, 0, 1000)
    assert SpatialReasoner.geodesic_buffer(square, 0).equals(square)
    reasoner = SpatialReasoner()
    result = reasoner.execute(
        SpatialQuery(operation=SpatialOperation.BUFFER, geometry=mapping(square), radius_m=0)
    )
    assert result.features[0].properties["radius_m"] == 0


# --- Bounding boxes ------------------------------------------------------------------


@pytest.mark.parametrize("lat", [0.0, -37.8, 60.0, -75.0])
def test_bbox_covers_radius_east_west_at_any_latitude(lat: float) -> None:
    south, west, north, east = overpass_bbox(lat, 144.97, 2000)
    assert GEOD.inv(west, lat, east, lat)[2] == pytest.approx(4000, rel=0.001)
    assert GEOD.inv(144.97, south, 144.97, north)[2] == pytest.approx(4000, rel=0.001)
    assert south < lat < north and west < 144.97 < east


# --- CRS ---------------------------------------------------------------------------------


def test_second_geometry_is_reprojected_too() -> None:
    """A distance query in EPSG:3857 must match the same query in EPSG:4326."""
    from pyproj import Transformer

    to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    eiffel, louvre = (2.2945, 48.8584), (2.3376, 48.8606)
    engine = Engine()

    def distance(crs: str, a, b) -> float:
        result = engine.execute(
            SpatialQuery(
                operation=SpatialOperation.DISTANCE,
                geometry={"type": "Point", "coordinates": list(a)},
                metadata={"geometry_b": {"type": "Point", "coordinates": list(b)}},
                crs=crs,
            )
        )
        assert not result.errors, result.errors
        return result.features[0].properties["distance_m"]

    wgs84 = distance("EPSG:4326", eiffel, louvre)
    merc = distance("EPSG:3857", to_merc.transform(*eiffel), to_merc.transform(*louvre))
    assert wgs84 == pytest.approx(3172, abs=5)
    assert merc == pytest.approx(wgs84, abs=0.5)


def test_length_operation_is_geodesic() -> None:
    start = (144.95, -37.81)
    end_lon, end_lat, _ = GEOD.fwd(*start, 45, 1500)
    result = SpatialReasoner().execute(
        SpatialQuery(
            operation=SpatialOperation.LENGTH,
            geometry={"type": "LineString", "coordinates": [list(start), [end_lon, end_lat]]},
        )
    )
    assert not result.errors
    assert result.features[0].properties["length_m"] == pytest.approx(1500, abs=0.5)


# --- Honest results ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_path", "operation"),
    [
        ("geospark.tools.terrain.elevation.ElevationTool", SpatialOperation.SLOPE),
        ("geospark.tools.terrain.elevation.ElevationTool", SpatialOperation.VIEWSHED),
        ("geospark.tools.routing.osrm.OSRMRouteTool", SpatialOperation.ISOCHRONE),
        ("geospark.tools.change_detection.pixel_change.PixelChangeTool", SpatialOperation.CHANGE_DETECTION),
    ],
)
def test_unbuilt_operations_report_an_error(tool_path: str, operation: SpatialOperation) -> None:
    import importlib

    module, cls = tool_path.rsplit(".", 1)
    tool = getattr(importlib.import_module(module), cls)()
    result = tool.execute(
        SpatialQuery(operation=operation, geometry={"type": "Point", "coordinates": [0, 0]})
    )
    assert result.errors and "not implemented" in result.errors[0]


def test_mcp_elevation_reports_the_real_source() -> None:
    from geospark.mcp_servers.terrain import TerrainServer
    from geospark.protocol.schema import SpatialFeature, SpatialResult

    fake = SpatialResult(
        features=[SpatialFeature(geometry={"type": "Point", "coordinates": [0, 0]},
                                 properties={"elevation_m": 12.0, "attribution": "© DLR e.V. 2021"})],
        sources=["copernicus-glo30"],
    )
    server = TerrainServer()
    with patch.object(server.engine, "execute", return_value=fake):
        out = server._handle_elevation({"latitude": 0, "longitude": 0})
    assert out["metadata"]["source"] == "copernicus-glo30"
    assert out["metadata"]["attribution"] == "© DLR e.V. 2021"


def test_nominatim_outage_is_reported_not_raised() -> None:
    import httpx

    from geospark.tools.geocoding.nominatim import NominatimGeocoder

    with patch("httpx.Client.get", side_effect=httpx.ConnectError("down")):
        result = NominatimGeocoder().execute(
            SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Paris"})
        )
    assert result.errors and "unavailable" in result.errors[0]


# --- Async from sync -------------------------------------------------------------------------


def test_run_sync_works_inside_a_running_loop() -> None:
    """The old asyncio.run() raised here, and agents silently dropped weather data."""

    async def answer() -> int:
        await asyncio.sleep(0)
        return 42

    async def caller() -> int:
        return run_sync(answer())  # sync code called from inside a running loop

    assert run_sync(answer()) == 42
    assert asyncio.run(caller()) == 42


def test_report_weather_survives_a_running_event_loop() -> None:
    from geospark.agents.spatial_report import SpatialReport

    weather = MagicMock(errors=[], is_empty=False, features=[{
        "type": "current_weather", "temperature_c": 18.0, "feels_like_c": 17.0,
        "humidity_pct": 60, "wind_speed_kmh": 10.0, "precipitation_mm": 0.0,
        "weather_description": "Clear sky",
    }])
    report = SpatialReport.__new__(SpatialReport)

    async def inside_loop():
        return report._fetch_weather(-37.8, 144.97)

    with patch("geospark.data_channels.weather.WeatherChannel",
               **{"return_value.search": AsyncMock(return_value=weather)}):
        snapshot = asyncio.run(inside_loop())
    assert snapshot is not None and snapshot.temperature_c == 18.0


# --- API -----------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from geospark import security
    from geospark.api import app

    monkeypatch.setenv("GEOSPARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEOSPARK_RATE_LIMIT_ENABLED", "false")
    security.reset_llm_slots()
    return TestClient(app)


@pytest.mark.parametrize(
    "bad",
    [{"type": "Polygon"}, {"type": "Blob", "coordinates": [1, 2]}, {"type": "Point", "coordinates": "x"}, {}],
)
def test_malformed_geojson_is_a_400(client, bad) -> None:
    resp = client.post(
        "/api/v1/check-relationship",
        json={"geometry_a": bad, "geometry_b": {"type": "Point", "coordinates": [0, 0]},
              "relationship": "contains"},
    )
    assert resp.status_code == 400


def test_slow_agent_does_not_block_other_requests(client) -> None:
    """The API runs one worker: blocking work must not freeze the event loop.

    ``with client`` makes every request share one event loop, as in production
    (without it, TestClient gives each request its own loop and hides the problem).
    """
    from geospark.agents import GeoAgent

    def slow_run(self, goal):
        time.sleep(1.5)
        return MagicMock(model_dump=lambda: {"summary": "done"})

    with client, patch.object(GeoAgent, "run", slow_run):
        worker = threading.Thread(target=client.post, args=("/api/v1/agent/run",),
                                  kwargs={"json": {"goal": "slow"}})
        worker.start()
        time.sleep(0.2)  # let the slow request start
        t0 = time.time()
        assert client.get("/health").status_code == 200
        elapsed = time.time() - t0
        worker.join()
    assert elapsed < 0.5, f"/health waited {elapsed:.2f}s behind a slow agent"


def test_data_channel_registry_is_shared(client) -> None:
    from geospark import api

    assert api._channel_registry() is api._channel_registry()
