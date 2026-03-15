"""Tests for domain-specific MCP servers."""
from __future__ import annotations

import pytest

from geospark.mcp_servers.base import BaseMCPServer
from geospark.mcp_servers.geocoding import GeocodingServer
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.mcp_servers.spatial_reasoning import SpatialReasoningServer
from geospark.mcp_servers.terrain import TerrainServer


class TestBaseMCPServer:
    """Tests for base MCP server."""

    def test_unknown_tool(self) -> None:
        server = BaseMCPServer()
        result = server.handle_tool_call("nonexistent", {})
        assert result["status"] == "error"
        assert result["error"]["code"] == "UNKNOWN_TOOL"


class TestSpatialReasoningServer:
    """Tests for spatial reasoning MCP server."""

    def test_has_tools(self) -> None:
        server = SpatialReasoningServer()
        tools = server.get_tools()
        assert len(tools) == 3
        names = [t["name"] for t in tools]
        assert "check_spatial_relationship" in names
        assert "calculate_distance" in names
        assert "spatial_operation" in names

    def test_check_relationship_contains(self) -> None:
        server = SpatialReasoningServer()
        result = server.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "test",
                "geometry_a": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "geometry_b": {"type": "Point", "coordinates": [5, 5]},
                "relationship": "contains",
            },
        )
        assert result["status"] == "success"
        assert result["result"]["holds"] is True

    def test_check_relationship_disjoint(self) -> None:
        server = SpatialReasoningServer()
        result = server.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "test",
                "geometry_a": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "geometry_b": {
                    "type": "Polygon",
                    "coordinates": [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]],
                },
                "relationship": "disjoint",
            },
        )
        assert result["status"] == "success"
        assert result["result"]["holds"] is True

    def test_calculate_distance(self) -> None:
        server = SpatialReasoningServer()
        result = server.handle_tool_call(
            "calculate_distance",
            {
                "explanation": "test",
                "point_a": {"type": "Point", "coordinates": [2.2945, 48.8584]},
                "point_b": {"type": "Point", "coordinates": [2.3376, 48.8606]},
            },
        )
        assert result["status"] == "success"
        assert result["result"]["distance_m"] > 3000
        assert result["result"]["distance_km"] > 3.0

    def test_spatial_operation_buffer(self) -> None:
        server = SpatialReasoningServer()
        result = server.handle_tool_call(
            "spatial_operation",
            {
                "explanation": "test",
                "operation": "buffer",
                "latitude": 48.8584,
                "longitude": 2.2945,
                "radius_m": 1000,
            },
        )
        assert result["status"] == "success"


class TestGeocodingServer:
    """Tests for geocoding MCP server."""

    def test_has_tools(self) -> None:
        server = GeocodingServer()
        tools = server.get_tools()
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "geocode" in names
        assert "reverse_geocode" in names


class TestTerrainServer:
    """Tests for terrain MCP server."""

    def test_has_tools(self) -> None:
        server = TerrainServer()
        tools = server.get_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "get_elevation"


class TestMCPServerLauncher:
    """Tests for the MCP server launcher."""

    def test_launch_all(self) -> None:
        launcher = MCPServerLauncher()
        assert len(launcher.active_servers) == 3
        tools = launcher.get_all_tools()
        assert len(tools) >= 6  # 3 + 2 + 1

    def test_launch_specific(self) -> None:
        launcher = MCPServerLauncher(servers=["spatial_reasoning"])
        assert launcher.active_servers == ["spatial_reasoning"]
        tools = launcher.get_all_tools()
        assert len(tools) == 3

    def test_route_tool_call(self) -> None:
        launcher = MCPServerLauncher()
        result = launcher.handle_tool_call(
            "check_spatial_relationship",
            {
                "explanation": "test",
                "geometry_a": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "geometry_b": {"type": "Point", "coordinates": [5, 5]},
                "relationship": "contains",
            },
        )
        assert result["status"] == "success"
        assert result["result"]["holds"] is True

    def test_route_unknown_tool(self) -> None:
        launcher = MCPServerLauncher()
        result = launcher.handle_tool_call("nonexistent", {})
        assert result["status"] == "error"

    def test_invalid_server_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown server"):
            MCPServerLauncher(servers=["nonexistent"])

    def test_available_servers(self) -> None:
        servers = MCPServerLauncher.available_servers()
        assert "spatial_reasoning" in servers
        assert "geocoding" in servers
        assert "terrain" in servers
