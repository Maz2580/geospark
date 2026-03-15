"""Base MCP server with shared tool dispatch pattern."""
from __future__ import annotations

from typing import Any


class BaseMCPServer:
    """Base class for domain-specific MCP servers.

    Each subclass defines its own tools and handlers. The dispatch
    pattern ensures consistent error handling and result format.
    """

    server_name: str = "geospark"
    tools: list[dict[str, Any]] = []

    def get_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions for this server."""
        return self.tools

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler."""
        arguments = {k: v for k, v in arguments.items() if k != "explanation"}

        handler = self._get_handlers().get(tool_name)
        if handler is None:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "UNKNOWN_TOOL",
                    "message": f"Unknown tool: {tool_name}",
                    "suggestion": f"Available tools: {list(self._get_handlers())}",
                },
            }
        try:
            result = handler(arguments)
            return {"status": "success", "tool": tool_name, **result}
        except ValueError as e:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": str(e),
                    "suggestion": "Check parameters and try again.",
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "tool": tool_name,
                "error": {
                    "code": "EXECUTION_ERROR",
                    "message": str(e),
                    "suggestion": "An unexpected error occurred.",
                },
            }

    def _get_handlers(self) -> dict[str, Any]:
        """Override in subclass to map tool names to handler methods."""
        return {}
