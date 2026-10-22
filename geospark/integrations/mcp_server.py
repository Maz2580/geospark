"""Tool definitions and handler for the LLM integrations (OpenRouter, OpenAI, Anthropic, generic).

Compatibility layer: these names are kept for existing imports, but the tools now come from the
shared ``MCPServerLauncher``, the same tool set the local Ollama loop and the MCP server use.
Every model therefore sees the same tools, schemas, provenance and error behaviour.

``spatial_query`` (the old name) is still accepted and forwarded to ``spatial_operation``.
"""

from __future__ import annotations

from typing import Any

from geospark.mcp_servers.launcher import MCPServerLauncher

_LEGACY_ALIASES = {"spatial_query": "spatial_operation"}

MCP_TOOLS: list[dict[str, Any]] = MCPServerLauncher().get_all_tools()


class GeoSparkMCPHandler:
    """Executes tool calls from an LLM against GeoSpark (via the shared launcher)."""

    def __init__(self, tools: list[str] | None = None) -> None:
        # ``tools`` is accepted for backwards compatibility; the launcher loads what it needs.
        self._launcher = MCPServerLauncher()

    def get_tools(self) -> list[dict[str, Any]]:
        return self._launcher.get_all_tools()

    def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._launcher.handle_tool_call(_LEGACY_ALIASES.get(tool_name, tool_name), arguments)
