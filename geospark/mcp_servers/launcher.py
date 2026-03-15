"""Launcher for GeoSpark MCP servers — start all or individual servers."""
from __future__ import annotations

from typing import Any

from geospark.mcp_servers.base import BaseMCPServer
from geospark.mcp_servers.geocoding import GeocodingServer
from geospark.mcp_servers.spatial_reasoning import SpatialReasoningServer
from geospark.mcp_servers.terrain import TerrainServer

# Registry of available MCP servers
SERVERS: dict[str, type[BaseMCPServer]] = {
    "spatial_reasoning": SpatialReasoningServer,
    "geocoding": GeocodingServer,
    "terrain": TerrainServer,
}


class MCPServerLauncher:
    """Manages multiple GeoSpark MCP servers.

    Can run all servers or a specific subset. Each server is
    independently discoverable by MCP hosts (Claude Desktop, etc.).
    """

    def __init__(self, servers: list[str] | None = None) -> None:
        if servers is None:
            servers = list(SERVERS.keys())

        self._servers: dict[str, BaseMCPServer] = {}
        for name in servers:
            if name not in SERVERS:
                raise ValueError(
                    f"Unknown server: {name}. Available: {list(SERVERS.keys())}"
                )
            self._servers[name] = SERVERS[name]()

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get combined tool definitions from all active servers."""
        tools = []
        for server in self._servers.values():
            tools.extend(server.get_tools())
        return tools

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Route a tool call to the appropriate server."""
        for server in self._servers.values():
            tool_names = [t["name"] for t in server.get_tools()]
            if tool_name in tool_names:
                return server.handle_tool_call(tool_name, arguments)

        return {
            "status": "error",
            "tool": tool_name,
            "error": {
                "code": "UNKNOWN_TOOL",
                "message": f"No server handles tool: {tool_name}",
                "suggestion": f"Available tools: {[t['name'] for t in self.get_all_tools()]}",
            },
        }

    @property
    def active_servers(self) -> list[str]:
        """List active server names."""
        return list(self._servers.keys())

    @staticmethod
    def available_servers() -> list[str]:
        """List all available server names."""
        return list(SERVERS.keys())
