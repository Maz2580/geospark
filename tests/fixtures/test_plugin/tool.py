"""
Test fixture plugin tool.

A minimal BaseTool subclass used by the plugin system tests.
"""

from __future__ import annotations

from typing import ClassVar

from geospark.protocol.schema import (
    SpatialContext,
    SpatialQuery,
    SpatialResult,
)
from geospark.tools.base import BaseTool


class EchoTool(BaseTool):
    """A trivial tool that echoes the query operation name.

    Used exclusively for testing the community plugin loader.
    """

    name: ClassVar[str] = "echo_tool"
    description: ClassVar[str] = "Echoes the query operation for testing"
    supported_operations: ClassVar[list[str]] = ["echo"]

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Return a result whose summary contains the operation name."""
        return SpatialResult(
            spatial_context=SpatialContext(
                summary=f"echo:{query.operation.value}",
            ),
            sources=["test-echo-plugin"],
        )
