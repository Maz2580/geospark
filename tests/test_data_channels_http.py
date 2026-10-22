"""Data channels against realistic upstream responses.

httpx's MockTransport answers with payloads shaped like each provider's documented response,
so the channels' real request-building and parsing code runs (no network).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from geospark.data_channels.air_quality import AirQualityChannel
from geospark.data_channels.fires import FiresChannel
from geospark.data_channels.registry import ChannelRegistry
from geospark.data_channels.weather import WeatherChannel

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch):
    """Route every httpx request to a handler; returns the list of requests made."""
    seen: list[httpx.Request] = []
    state: dict[str, Handler] = {}
    real_async_client = httpx.AsyncClient

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    def make_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport_handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_async_client)

    def use(handler: Handler) -> list[httpx.Request]:
        state["handler"] = handler
        return seen

    return use


def run(coro):
    return asyncio.run(coro)


# --- Weather (Open-Meteo) ---------------------------------------------------------

OPEN_METEO = {
    "timezone": "Australia/Melbourne",
    "elevation": 31.0,
    "current": {
        "time": "2026-10-22T11:00", "temperature_2m": 26.8, "relative_humidity_2m": 38,
        "apparent_temperature": 26.2, "precipitation": 0.0, "weather_code": 0,
        "wind_speed_10m": 15.3, "wind_direction_10m": 200,
    },
    "daily": {
        "time": ["2026-10-22", "2026-10-23"],
        "temperature_2m_max": [28.1, 22.4], "temperature_2m_min": [14.0, 12.2],
        "precipitation_sum": [0.0, 3.1], "wind_speed_10m_max": [24.0, 31.5], "weather_code": [0, 61],
    },
}


def test_weather_parses_current_and_daily(upstream) -> None:
    seen = upstream(lambda r: httpx.Response(200, json=OPEN_METEO))
    result = run(WeatherChannel().search(lat=-37.8178, lon=144.9691, filters={"forecast_days": 2}))
    assert not result.errors
    current = next(f for f in result.features if f["type"] == "current_weather")
    assert current["temperature_c"] == 26.8
    assert current["weather_description"] == "Clear sky"
    assert current["coordinates"] == [144.9691, -37.8178]  # GeoJSON order: lon, lat
    daily = [f for f in result.features if f["type"] == "daily_forecast"]
    assert [d["precipitation_mm"] for d in daily] == [0.0, 3.1]
    assert seen[0].url.params["forecast_days"] == "2"
    assert result.metadata["timezone"] == "Australia/Melbourne"


def test_weather_upstream_error_is_reported(upstream) -> None:
    upstream(lambda r: httpx.Response(503, text="maintenance"))
    result = run(WeatherChannel().search(lat=0, lon=0))
    assert result.errors and "Weather API error" in result.errors[0]
    assert not result.features


def test_weather_needs_a_location() -> None:
    assert run(WeatherChannel().search()).errors


# --- Air quality (OpenAQ v3) ----------------------------------------------------------

OPENAQ_LOCATIONS = {
    "meta": {"found": 1},
    "results": [{
        "id": 2178,
        "name": "Melbourne CBD",
        "locality": "Melbourne",
        "country": {"id": 9, "code": "AU", "name": "Australia"},
        "provider": {"id": 1, "name": "EPA Victoria"},
        "sensors": [
            {"id": 3920, "name": "pm25 µg/m³", "parameter": {"id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"}},
            {"id": 3921, "name": "no2 ppm", "parameter": {"id": 7, "name": "no2", "units": "ppm", "displayName": "NO₂"}},
        ],
        "coordinates": {"latitude": -37.8136, "longitude": 144.9631},
        "licenses": [{"id": 1, "name": "CC BY 4.0", "attribution": {"name": "EPA Victoria", "url": "https://www.epa.vic.gov.au"}}],
        "distance": 640.2,
    }],
}
OPENAQ_LATEST = {
    "meta": {"found": 2},
    "results": [
        {"datetime": {"utc": "2026-10-22T00:00:00Z"}, "value": 8.4, "sensorsId": 3920, "locationsId": 2178},
        {"datetime": {"utc": "2026-10-22T00:00:00Z"}, "value": 0.011, "sensorsId": 3921, "locationsId": 2178},
    ],
}


def _openaq(request: httpx.Request) -> httpx.Response:
    assert request.headers["X-API-Key"] == "test-key"
    if request.url.path.endswith("/latest"):
        return httpx.Response(200, json=OPENAQ_LATEST)
    return httpx.Response(200, json=OPENAQ_LOCATIONS)


def test_air_quality_parses_v3_locations_and_latest(upstream, monkeypatch) -> None:
    monkeypatch.setenv("OPENAQ_API_KEY", "test-key")
    seen = upstream(_openaq)
    result = run(AirQualityChannel().search(lat=-37.81, lon=144.96))
    assert not result.errors
    station = result.features[0]
    assert station["station_name"] == "Melbourne CBD"
    assert station["country"] == "Australia"
    assert station["city"] == "Melbourne"
    assert station["coordinates"] == [144.9631, -37.8136]
    assert station["measurements"]["pm25"] == {"value": 8.4, "unit": "µg/m³", "last_updated": "2026-10-22T00:00:00Z"}
    assert station["measurements"]["no2"]["value"] == 0.011
    assert station["aqi_category"]  # derived from PM2.5
    assert station["licenses"][0]["attribution"] == "EPA Victoria"
    assert {r.url.path for r in seen} == {"/v3/locations", "/v3/locations/2178/latest"}
    assert "key required" in result.metadata["api"]


def test_air_quality_station_without_latest_still_listed(upstream, monkeypatch) -> None:
    monkeypatch.setenv("OPENAQ_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/latest"):
            return httpx.Response(500)
        return httpx.Response(200, json=OPENAQ_LOCATIONS)

    upstream(handler)
    result = run(AirQualityChannel().search(lat=-37.81, lon=144.96))
    assert result.features[0]["station_name"] == "Melbourne CBD"
    assert result.features[0]["measurements"] == {}


def test_air_quality_without_key_says_how_to_get_one(monkeypatch) -> None:
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    result = run(AirQualityChannel().search(lat=0, lon=0))
    assert result.errors and "OPENAQ_API_KEY" in result.errors[0]


# --- Fires (NASA FIRMS CSV) --------------------------------------------------------------

FIRMS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight
-33.861,150.021,330.5,0.4,0.4,2026-10-21,0312,N,85,2.0NRT,290.1,12.4,D
-33.902,150.110,301.2,0.4,0.4,2026-10-21,0312,N,40,2.0NRT,288.0,3.1,D
-33.950,150.200,345.0,0.4,0.4,2026-10-21,1506,N,95,2.0NRT,291.5,20.7,N
"""


def test_fires_parse_filter_and_sort(upstream, monkeypatch) -> None:
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-map-key")
    seen = upstream(lambda r: httpx.Response(200, text=FIRMS_CSV))
    result = run(FiresChannel().search(bbox=(-34.5, 149.5, -33.5, 150.5), filters={"min_confidence": 50}))
    assert not result.errors
    assert [f["confidence"] for f in result.features] == [95.0, 85.0]  # 40 filtered out, sorted desc
    assert result.features[0]["coordinates"] == [150.2, -33.95]
    # FIRMS area order is west,south,east,north
    assert "/149.5,-34.5,150.5,-33.5/" in str(seen[0].url)


def test_fires_no_detections(upstream, monkeypatch) -> None:
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-map-key")
    upstream(lambda r: httpx.Response(200, text=FIRMS_CSV.splitlines()[0] + "\n"))
    result = run(FiresChannel().search(lat=-37.8, lon=144.9))
    assert result.total_results == 0 and not result.errors


def test_fires_area_too_large(upstream, monkeypatch) -> None:
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-map-key")
    upstream(lambda r: httpx.Response(401))
    result = run(FiresChannel().search(lat=-37.8, lon=144.9))
    assert result.errors and "too large" in result.errors[0]


# --- Registry and cache ---------------------------------------------------------------------


def test_registry_caches_identical_searches(upstream) -> None:
    seen = upstream(lambda r: httpx.Response(200, json=OPEN_METEO))
    registry = ChannelRegistry()

    async def twice():
        a = await registry.search("weather", lat=-37.8, lon=144.9)
        b = await registry.search("weather", lat=-37.8, lon=144.9)
        return a, b

    first, second = run(twice())
    assert first.features == second.features
    assert len(seen) == 1  # second answer came from the cache


def test_registry_unknown_channel() -> None:
    with pytest.raises(ValueError):
        run(ChannelRegistry().search("no-such-channel", lat=0, lon=0))


# --- Place-name lookup and health checks ------------------------------------------------------


def test_weather_geocodes_place_names_with_open_meteo(upstream) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.params["name"] == "Melbourne"
            return httpx.Response(200, json={"results": [
                {"name": "Melbourne", "country": "Australia", "latitude": -37.814, "longitude": 144.963}
            ]})
        assert request.url.params["latitude"] == "-37.814"
        return httpx.Response(200, json=OPEN_METEO)

    upstream(handler)
    result = run(WeatherChannel().search(location="Melbourne"))
    assert result.query["location"] == "Melbourne, Australia"
    assert result.features[0]["coordinates"] == [144.963, -37.814]


def test_weather_unknown_place(upstream, monkeypatch) -> None:
    upstream(lambda r: httpx.Response(200, json={"results": []}))
    monkeypatch.setattr(
        "geospark.data_channels.weather.MCPServerLauncher",
        lambda: type("L", (), {"handle_tool_call": lambda self, n, a: {"status": "error"}})(),
    )
    result = run(WeatherChannel().search(location="Atlantis"))
    assert result.errors and "Atlantis" in result.errors[0]


def test_fires_known_region_skips_geocoding(upstream, monkeypatch) -> None:
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-map-key")
    seen = upstream(lambda r: httpx.Response(200, text=FIRMS_CSV))
    run(FiresChannel().search(location="Amazon rainforest"))
    # Amazon box (min_lat, min_lon, max_lat, max_lon) = (-5, -65, 0, -55) -> FIRMS west,south,east,north
    assert "/-65.0,-5.0,-55.0,0.0/" in str(seen[0].url)


@pytest.mark.parametrize(
    ("status", "expected"), [(200, "ok"), (500, "warn")]
)
def test_weather_health_check(monkeypatch, status: int, expected: str) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(status))
    assert WeatherChannel().check().status == expected


def test_weather_health_check_unreachable(monkeypatch) -> None:
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    assert WeatherChannel().check().status == "error"


def test_registry_check_all_reports_every_channel(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"results": []}))
    statuses = ChannelRegistry().check_all()
    assert {s.name for s in statuses} >= {"weather", "air-quality", "fires"}
