"""Backwards-compatible alias: the MCP server now lives in ``geospark.mcp_servers.server``.

Usage:
    geospark-mcp                      # installed command (stdio)
    python -m geospark.mcp_servers    # same

    # Claude Desktop config (macOS: ~/Library/Application Support/Claude/claude_desktop_config.json,
    # Windows: %APPDATA%\\Claude\\claude_desktop_config.json):
    {"mcpServers": {"geospark": {"command": "geospark-mcp"}}}
"""

from __future__ import annotations

from geospark.mcp_servers.server import create_server, run

__all__ = ["create_server", "run"]
