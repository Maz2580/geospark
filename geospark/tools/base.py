"""
Base tool interface for GeoSpark tools.

All tools (built-in and community-contributed) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from geospark.protocol.schema import SpatialQuery, SpatialResult


class BaseTool(ABC):
    """
    Abstract base class for all GeoSpark tools.

    To create a custom tool:
    1. Subclass BaseTool
    2. Set name, description, and supported_operations
    3. Implement the execute() method
    4. Register via ToolRegistry or drop in geospark/tools/custom/
    """

    name: ClassVar[str] = "base_tool"
    description: ClassVar[str] = "Base tool"
    supported_operations: ClassVar[list[str]] = []

    @abstractmethod
    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute a spatial query using this tool."""
        ...

    def supports(self, operation: str) -> bool:
        """Check if this tool supports a given operation."""
        return operation in self.supported_operations

    def get_schema(self) -> dict[str, Any]:
        """
        Get the tool schema for LLM function calling.

        Returns an OpenAI-compatible function schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": self.supported_operations,
                        "description": "The spatial operation to perform",
                    },
                },
                "required": ["operation"],
            },
        }
