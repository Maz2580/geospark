"""Base MCP server with shared tool dispatch pattern."""
from __future__ import annotations

from typing import Any, ClassVar


class BaseMCPServer:
    """Base class for domain-specific MCP servers.

    Each subclass defines its own tools and handlers. The dispatch
    pattern ensures consistent error handling and result format.
    """

    server_name: ClassVar[str] = "geospark"
    tools: ClassVar[list[dict[str, Any]]] = []

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
            # A handler that reports errors failed, even though it returned normally
            status = "error" if result.get("errors") else "success"
            return {"status": status, "tool": tool_name, **result}
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


def verification(result: Any) -> dict[str, Any]:
    """The checkable part of an answer, for tool replies: status, provenance, units, quality.

    An LLM (or the person reading its answer) can cite the source and licence, see how a
    value was computed, and know the caveats.
    """
    out: dict[str, Any] = {
        "status": result.status,
        "provenance": [p.model_dump(mode="json", exclude_none=True) for p in result.provenance],
    }
    if result.spatial_context.units:
        out["units"] = result.spatial_context.units
    if result.warnings:
        out["warnings"] = result.warnings
    if result.quality:
        out["quality"] = result.quality
    return out
