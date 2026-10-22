"""/ask answers carry the tools' provenance, units, caveats and found places (for the Proof panel)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from geospark.engine.core import answer_to_result
from geospark.mcp_servers.launcher import MCPServerLauncher

GEOCODE_REPLY = {
    "result": {"features": [{"geometry": {"type": "Point", "coordinates": [144.969, -37.818]},
                             "properties": {"display_name": "Federation Square"}}]},
    "metadata": {"status": "ok", "warnings": ["Another match 40 km away"],
                 "provenance": [{"source": "openstreetmap-nominatim", "name": "OpenStreetMap Nominatim",
                                 "licence": "ODbL-1.0"}]},
}


def _answer():
    distance = MCPServerLauncher().handle_tool_call("calculate_distance", {
        "explanation": "test",
        "point_a": {"type": "Point", "coordinates": [144.969, -37.818]},
        "point_b": {"type": "Point", "coordinates": [144.966, -37.815]},
    })
    failed = {"status": "error", "tool": "get_elevation", "error": {"message": "service down"}}
    return SimpleNamespace(answer="It is 425 m.", model="m", tool_calls=[
        {"tool": "geocode", "result": GEOCODE_REPLY},
        {"tool": "geocode", "result": GEOCODE_REPLY},
        {"tool": "calculate_distance", "result": distance},
        {"tool": "get_elevation", "result": failed},
    ])


def test_answer_collects_provenance_units_and_caveats_once() -> None:
    result = answer_to_result(_answer(), "ollama:m")
    assert [p.source for p in result.provenance] == ["openstreetmap-nominatim", "geospark-engine"]
    assert result.spatial_context.units["distance_m"] == "metre"
    assert result.warnings == ["Another match 40 km away", "Tool get_elevation failed: service down"]
    assert len(result.features) == 2 and result.sources[0] == "ollama:m"


def test_ask_endpoint_returns_the_checkable_part() -> None:
    from geospark import api

    with patch.object(api.get_engine(), "ask", return_value=answer_to_result(_answer(), "ollama:m")):
        body = TestClient(api.app).post("/api/v1/ask", json={"question": "How far?"}).json()
    assert body["status"] == "partial"  # a tool failed, so the answer is not fully checked
    assert body["provenance"][0]["licence"] == "ODbL-1.0"
    assert body["features"][0]["geometry"]["coordinates"] == [144.969, -37.818]
    assert body["tools_used"] == ["geocode", "geocode", "calculate_distance", "get_elevation"]
