"""The MCP server (SDK 2.x) end to end over Streamable HTTP: tools, schemas, structured
results and honest errors. Network-backed tools run against mocks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("mcp")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from geospark import api, security
from geospark.protocol.schema import SpatialFeature, SpatialResult

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
EIFFEL = {"type": "Point", "coordinates": [2.2945, 48.8584]}
LOUVRE = {"type": "Point", "coordinates": [2.3376, 48.8606]}
BOWTIE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
EXPECTED_TOOLS = {
    "calculate_distance", "check_spatial_relationship", "spatial_operation", "geocode",
    "reverse_geocode", "get_elevation", "route", "get_weather", "get_air_quality",
    "get_active_fires", "location_report", "select_site",
}


@pytest.fixture(scope="module")
def mcp():
    api.enable_mcp_http(api.app)
    with TestClient(api.app, base_url="https://geospark.terrascout.app") as client:
        counter = iter(range(1, 10_000))

        def rpc(method: str, params: dict | None = None) -> dict:
            body = {"jsonrpc": "2.0", "id": next(counter), "method": method, "params": params or {}}
            response = client.post("/mcp", json=body, headers=HEADERS)
            assert response.status_code == 200, response.text
            return response.json()

        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "pytest", "version": "0"}})
        yield rpc


def call(rpc, name: str, arguments: dict) -> dict:
    return rpc("tools/call", {"name": name, "arguments": arguments})["result"]


# --- discovery -------------------------------------------------------------------------------

def test_initialize_negotiates_older_clients(mcp) -> None:
    result = mcp("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "old-client", "version": "0"}})["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "geospark"
    assert "[longitude, latitude]" in result["instructions"]


def test_tools_have_output_schemas_and_read_only_annotations(mcp) -> None:
    tools = mcp("tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool["outputSchema"]["type"] == "object", tool["name"]
        assert tool["annotations"]["readOnlyHint"] is True
        assert "explanation" not in tool["inputSchema"].get("required", [])
    by_name = {t["name"]: t for t in tools}
    assert by_name["calculate_distance"]["annotations"]["openWorldHint"] is False  # pure computation
    assert by_name["geocode"]["annotations"]["openWorldHint"] is True  # calls a web service


def test_tool_order_is_deterministic(mcp) -> None:
    first = [t["name"] for t in mcp("tools/list")["result"]["tools"]]
    assert first == [t["name"] for t in mcp("tools/list")["result"]["tools"]]


# --- computation ---------------------------------------------------------------------------------

def test_distance_structured_with_units_and_provenance(mcp) -> None:
    result = call(mcp, "calculate_distance", {"point_a": EIFFEL, "point_b": LOUVRE, "explanation": "legacy"})
    assert not result.get("isError")
    data = result["structuredContent"]
    assert data["distance_m"] == pytest.approx(3172, abs=5)
    assert data["units"]["distance_m"] == "metre"
    assert data["provenance"][0]["method"].startswith("Geodesic")


def test_invalid_geometry_is_a_tool_error_with_reason(mcp) -> None:
    result = call(mcp, "check_spatial_relationship",
                  {"geometry_a": BOWTIE, "geometry_b": EIFFEL, "relationship": "contains"})
    assert result["isError"] is True
    assert "Self-intersection" in result["content"][0]["text"]


def test_swapped_coordinates_are_explained(mcp) -> None:
    result = call(mcp, "calculate_distance",
                  {"point_a": {"type": "Point", "coordinates": [-37.81, 144.96]}, "point_b": EIFFEL})
    assert result["isError"] is True and "[latitude, longitude]" in result["content"][0]["text"]


def test_buffer_returns_geojson(mcp) -> None:
    data = call(mcp, "spatial_operation", {"operation": "buffer", "geometry": EIFFEL, "radius_m": 100})["structuredContent"]
    assert data["type"] == "FeatureCollection"
    assert data["features"][0]["geometry"]["type"] == "Polygon"
    assert data["geospark"]["units"]["area_sq_m"] == "square metre"


def test_bad_arguments_are_rejected(mcp) -> None:
    result = call(mcp, "get_elevation", {"latitude": 200, "longitude": 0})
    assert result["isError"] is True


# --- web data (mocked) ------------------------------------------------------------------------------

SPRINGFIELD = {"features": [
    {"geometry": {"type": "Point", "coordinates": [-89.65, 39.80]},
     "properties": {"display_name": "Springfield, Illinois, United States", "importance": 0.613}},
    {"geometry": {"type": "Point", "coordinates": [-72.59, 42.10]},
     "properties": {"display_name": "Springfield, Massachusetts, United States", "importance": 0.611}},
]}


def test_geocode_surfaces_ambiguity(mcp) -> None:
    with patch("geospark.tools.geocoding.client.get_json", return_value=SPRINGFIELD):
        data = call(mcp, "geocode", {"query": "Springfield"})["structuredContent"]
    assert len(data["features"]) == 2
    assert any("Ambiguous" in w for w in data["geospark"]["warnings"])
    assert data["geospark"]["provenance"][0]["licence"] == "ODbL-1.0"


def test_unknown_place_is_an_error_not_an_empty_answer(mcp) -> None:
    with patch("geospark.tools.geocoding.client.get_json", return_value={"features": []}):
        result = call(mcp, "geocode", {"query": "Atlantis"})
    assert result["isError"] is True and "No place found" in result["content"][0]["text"]


def test_elevation_includes_accuracy(mcp) -> None:
    from geospark.tools.terrain.elevation import ElevationTool

    raw = ElevationTool._elevation_result(-37.8177, 144.9691, 23.1, "copernicus-dem", "© DLR")
    with patch("geospark.tools.terrain.elevation.ElevationTool.execute", return_value=raw):
        data = call(mcp, "get_elevation", {"latitude": -37.8177, "longitude": 144.9691})["structuredContent"]
    assert data["elevation_m"] == 23.1 and data["quality"]["vertical_accuracy_le90_m"] == 4.0
    assert data["provenance"][0]["source"] == "copernicus-dem"


def test_weather_tool(mcp) -> None:
    from geospark.data_channels.base import ChannelResult

    forecast = ChannelResult(channel="weather", source="open-meteo", total_results=1,
                             features=[{"type": "current_weather", "temperature_c": 18.2}])
    with patch("geospark.data_channels.registry.ChannelRegistry.search", AsyncMock(return_value=forecast)):
        data = call(mcp, "get_weather", {"latitude": -37.81, "longitude": 144.96})["structuredContent"]
    assert data["features"][0]["temperature_c"] == 18.2
    assert data["provenance"][0]["licence"] == "CC-BY-4.0"


def test_data_source_down_is_an_error(mcp) -> None:
    from geospark.data_channels.base import ChannelResult

    down = ChannelResult(channel="air-quality", errors=["OPENAQ_API_KEY not set"])
    with patch("geospark.data_channels.registry.ChannelRegistry.search", AsyncMock(return_value=down)):
        result = call(mcp, "get_air_quality", {"latitude": 28.6, "longitude": 77.2})
    assert result["isError"] is True and "OPENAQ_API_KEY" in result["content"][0]["text"]


def test_route_tool(mcp) -> None:
    line = SpatialResult(features=[SpatialFeature(
        geometry={"type": "LineString", "coordinates": [[2.2945, 48.8584], [2.3376, 48.8606]]},
        properties={"distance_m": 3900.0, "duration_s": 720.0})], sources=["osrm-public-demo"])
    with patch("geospark.tools.routing.osrm.OSRMRouteTool.execute", return_value=line):
        data = call(mcp, "route", {"from_latitude": 48.8584, "from_longitude": 2.2945,
                                   "to_latitude": 48.8606, "to_longitude": 2.3376})["structuredContent"]
    assert data["features"][0]["geometry"]["type"] == "LineString"
    assert data["geospark"]["units"] == {"distance_m": "metre", "duration_s": "second"}
    assert "OSRM" in data["geospark"]["provenance"][0]["name"]


def test_heavy_tools_respect_the_concurrency_cap(mcp, monkeypatch) -> None:
    monkeypatch.setenv("GEOSPARK_MAX_LLM_CONCURRENCY", "1")
    security.reset_llm_slots()
    held = security.heavy_work_slot()
    held.__enter__()  # another request holds the only slot
    try:
        result = call(mcp, "location_report", {"location": "Federation Square"})
    finally:
        held.__exit__(None, None, None)
        security.reset_llm_slots()
    assert result["isError"] is True and "busy" in result["content"][0]["text"]


def test_location_report_tool(mcp) -> None:
    from geospark.agents.spatial_report import LocationReport, NearbyItem

    report = LocationReport(query="Federation Square", coordinates=[144.9691, -37.8177], address="Federation Square",
                            nearby=[NearbyItem(name="Pharmacy", amenity_type="pharmacy", distance_m=140,
                                               coordinates=[144.9672, -37.8183])])
    with patch("geospark.agents.SpatialReport.analyze", return_value=report):
        data = call(mcp, "location_report", {"location": "Federation Square"})["structuredContent"]
    assert [f["properties"]["kind"] for f in data["features"]] == ["location", "amenity"]


def test_mcp_http_is_off_unless_enabled(monkeypatch) -> None:
    monkeypatch.delenv("GEOSPARK_MCP_HTTP", raising=False)
    assert api.mcp_http_enabled() is False
    monkeypatch.setenv("GEOSPARK_MCP_HTTP", "true")
    assert api.mcp_http_enabled() is True
