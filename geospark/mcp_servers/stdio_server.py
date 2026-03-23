"""
MCP stdio server — connects GeoSpark to Claude Desktop and other MCP hosts.

This bridges the existing GeoSpark MCP server logic (tool definitions,
handlers, structured results) with the official MCP SDK transport layer.

Usage:
    # As installed command:
    geospark-mcp

    # As Python module:
    python -m geospark.mcp_servers

    # Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "geospark": {
          "command": "geospark-mcp"
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from geospark.mcp_servers.launcher import MCPServerLauncher


def create_server() -> Server:
    """Create an MCP server with all GeoSpark spatial tools."""
    server = Server("geospark")
    launcher = MCPServerLauncher()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for tool_def in launcher.get_all_tools():
            tools.append(
                Tool(
                    name=tool_def["name"],
                    description=tool_def.get("description", ""),
                    inputSchema=tool_def.get(
                        "inputSchema",
                        {"type": "object", "properties": {}},
                    ),
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = launcher.handle_tool_call(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def _main() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run() -> None:
    """Entry point for the ``geospark-mcp`` command."""
    asyncio.run(_main())


if __name__ == "__main__":
    run()
