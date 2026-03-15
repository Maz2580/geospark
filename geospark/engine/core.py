"""
GeoSpark Core Engine.

The central orchestrator that connects spatial reasoning, tools, and LLM integrations.
"""

from __future__ import annotations

import time
from typing import Any

from geospark.engine.crs_handler import CRSHandler
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import SpatialContext, SpatialQuery, SpatialResult
from geospark.tools.registry import ToolRegistry


class Engine:
    """
    The GeoSpark Engine: central orchestrator for spatial intelligence.

    Usage:
        engine = Engine(tools=["geocoder", "satellite", "terrain"])
        result = engine.execute(query)
    """

    def __init__(
        self,
        spatial_backend: str = "memory",
        tools: list[str] | None = None,
        cache_enabled: bool = True,
    ):
        self.spatial_reasoner = SpatialReasoner()
        self.crs_handler = CRSHandler()
        self.tool_registry = ToolRegistry()
        self.cache_enabled = cache_enabled
        self._cache: dict[str, SpatialResult] = {}

        # Register requested tools
        if tools:
            for tool_name in tools:
                self.tool_registry.load_tool(tool_name)

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute a spatial query and return results."""
        start_time = time.time()

        # Normalize CRS if needed
        if query.crs != "EPSG:4326" and query.geometry:
            query = self._normalize_crs(query)

        # Route to appropriate handler
        result = self._route_query(query)

        # Add execution metadata
        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def ask(self, question: str, llm: str = "anthropic") -> SpatialResult:
        """
        Ask a natural language spatial question.

        This method parses the question, determines required operations,
        builds a query plan, executes it, and returns structured results.

        TODO: This is the core "ChatGPT moment" for geospatial.
        The LLM integration layer translates natural language to GSP queries.
        """
        raise NotImplementedError(
            "Natural language interface coming in Phase 1. "
            "Use engine.execute(SpatialQuery(...)) for programmatic queries."
        )

    def chain(self, steps: list[dict[str, Any]]) -> QueryChain:
        """Create a chain of spatial operations."""
        return QueryChain(engine=self, steps=steps)

    def _normalize_crs(self, query: SpatialQuery) -> SpatialQuery:
        """Transform query geometry to EPSG:4326."""
        if query.geometry is None:
            return query
        transformed = self.crs_handler.transform_geometry(
            query.geometry, from_crs=query.crs, to_crs="EPSG:4326"
        )
        return query.model_copy(update={"geometry": transformed, "crs": "EPSG:4326"})

    def _route_query(self, query: SpatialQuery) -> SpatialResult:
        """Route a query to the appropriate handler."""
        operation = query.operation.value

        # Spatial reasoning operations (handled by engine directly)
        reasoning_ops = {
            "contains", "intersects", "touches", "crosses",
            "overlaps", "within", "disjoint", "distance",
            "area", "length", "buffer", "union", "intersection",
            "difference", "convex_hull", "centroid",
        }

        if operation in reasoning_ops:
            return self.spatial_reasoner.execute(query)

        # Tool-based operations
        tool = self.tool_registry.get_tool_for_operation(operation)
        if tool:
            return tool.execute(query)

        return SpatialResult(
            spatial_context=SpatialContext(summary=f"Unknown operation: {operation}"),
            errors=[f"No handler found for operation: {operation}"],
        )

    @property
    def available_tools(self) -> list[str]:
        """List all registered tools."""
        return self.tool_registry.list_tools()


class QueryChain:
    """A chain of spatial operations that execute sequentially."""

    def __init__(self, engine: Engine, steps: list[dict[str, Any]]):
        self.engine = engine
        self.steps = steps

    def run(self) -> SpatialResult:
        """Execute all steps in sequence, passing results forward."""
        result = None
        for step in self.steps:
            query = SpatialQuery(**step)
            # TODO: Pass previous result geometry as input to next step
            result = self.engine.execute(query)
        return result or SpatialResult()
