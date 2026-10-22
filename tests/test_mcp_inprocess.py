"""The MCP server's tool surface, in-process: listing, calling, and honest error status."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

mcp_types = pytest.importorskip("mcp.types")

from geospark.mcp_servers.launcher import MCPServerLauncher  # noqa: E402
from geospark.mcp_servers.stdio_server import create_server  # noqa: E402
from geospark.protocol.schema import SpatialResult  # noqa: E402


def _call(server, request):
    handler = server.request_handlers[type(request)]
    return asyncio.run(handler(request)).root


def test_list_tools_has_schemas() -> None:
    server = create_server()
    tools = _call(server, mcp_types.ListToolsRequest(method="tools/list")).tools
    names = {t.name for t in tools}
    assert names == {
        "check_spatial_relationship", "calculate_distance", "spatial_operation",
        "geocode", "reverse_geocode", "get_elevation",
    }
    for tool in tools:
        assert tool.description and tool.inputSchema["type"] == "object"


def _tool(server, name: str, arguments: dict) -> dict:
    result = _call(server, mcp_types.CallToolRequest(
        method="tools/call", params=mcp_types.CallToolRequestParams(name=name, arguments=arguments)
    ))
    return json.loads(result.content[0].text)


def test_call_distance_tool() -> None:
    out = _tool(create_server(), "calculate_distance", {
        "explanation": "test",
        "point_a": {"type": "Point", "coordinates": [2.2945, 48.8584]},
        "point_b": {"type": "Point", "coordinates": [2.3376, 48.8606]},
    })
    assert out["status"] == "success"
    assert out["result"]["distance_m"] == pytest.approx(3172, abs=5)


def test_unknown_tool_is_an_error() -> None:
    out = MCPServerLauncher().handle_tool_call("no_such_tool", {})
    assert out["status"] == "error"


def test_geocoding_outage_is_an_error_not_an_empty_success() -> None:
    """An LLM told 'no results' would conclude the place doesn't exist."""
    launcher = MCPServerLauncher()
    outage = SpatialResult(errors=["Geocoding service unavailable (ConnectError). Try again shortly."])
    with patch("geospark.engine.core.Engine.execute", return_value=outage):
        out = launcher.handle_tool_call("geocode", {"explanation": "t", "query": "Paris"})
    assert out["status"] == "error"
    assert "unavailable" in out["suggestion"]


def test_place_not_found_is_still_a_clean_empty_result() -> None:
    launcher = MCPServerLauncher()
    with patch("geospark.engine.core.Engine.execute", return_value=SpatialResult()):
        out = launcher.handle_tool_call("geocode", {"explanation": "t", "query": "Atlantis"})
    assert out["status"] == "success" and out["result"]["features"] == []


def test_failed_elevation_is_an_error() -> None:
    launcher = MCPServerLauncher()
    with patch("geospark.engine.core.Engine.execute", return_value=SpatialResult(errors=["no data"])):
        out = launcher.handle_tool_call("get_elevation", {"explanation": "t", "latitude": 0, "longitude": 0})
    assert out["status"] == "error"
