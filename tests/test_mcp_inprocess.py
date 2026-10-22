"""The internal tool launcher (used by the LLM integrations): honest error status."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("mcp")

from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.protocol.schema import SpatialResult


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
