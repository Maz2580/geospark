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
        """Execute a spatial query and return results.

        Note:
            If no CRS is specified on the query, EPSG:4326 (WGS84) is assumed.
            This is the GeoSpark protocol default.
        """
        start_time = time.time()

        # Normalize CRS if needed
        if query.crs != "EPSG:4326" and query.geometry:
            query = self._normalize_crs(query)

        # Route to appropriate handler
        result = self._route_query(query)

        # Add execution metadata
        result.execution_time_ms = (time.time() - start_time) * 1000
        return result

    def ask(
        self,
        question: str,
        model: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        ollama_url: str | None = None,
    ) -> SpatialResult:
        """
        Ask a natural language spatial question.

        Tries Ollama first (local, fast, free), falls back to OpenRouter.
        Override with ``provider="ollama"`` or ``provider="openrouter"``.

        Args:
            question: Natural language spatial question.
            model: Override the LLM model.
            api_key: Override the OpenRouter API key.
            provider: Force ``"ollama"`` or ``"openrouter"`` (default: auto).
            ollama_url: Ollama base URL (default: OLLAMA_BASE_URL env or
                ``http://localhost:11434``).

        Returns:
            SpatialResult with the answer, tools used, and metadata.

        Examples:
            engine = Engine(tools=["geocoder", "terrain"])
            result = engine.ask("How far is Paris from London?")
            print(result.spatial_context.summary)
        """
        import os

        tools = self.available_tools or ["geocoder", "terrain"]

        # Determine provider order
        if provider == "openrouter":
            return self._ask_openrouter(question, model, api_key, tools)
        if provider == "ollama":
            return self._ask_ollama(question, model, ollama_url, tools)

        # Auto mode: try Ollama first, fall back to OpenRouter
        ollama_result = self._ask_ollama(question, model, ollama_url, tools)
        if not ollama_result.errors:
            return ollama_result

        # Ollama failed — try OpenRouter
        key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            # Return the Ollama error since OpenRouter isn't configured either
            return ollama_result

        return self._ask_openrouter(question, model, api_key, tools)

    def _ask_ollama(
        self,
        question: str,
        model: str | None,
        ollama_url: str | None,
        tools: list[str],
    ) -> SpatialResult:
        """Try answering via local Ollama."""
        import os

        url = ollama_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        use_model = model or os.getenv("GEOSPARK_OLLAMA_MODEL", "qwen2.5:7b")

        from geospark.integrations.ollama_tools import OllamaClient

        try:
            with OllamaClient(model=use_model, base_url=url, tools=tools) as client:
                answer = client.ask(question, model=use_model)
        except Exception as e:
            return SpatialResult(
                errors=[f"Ollama call failed: {e}"],
            )

        tools_used = [tc["tool"] for tc in answer.tool_calls]
        return SpatialResult(
            spatial_context=SpatialContext(
                summary=answer.answer,
                total_features=len(answer.tool_calls),
            ),
            sources=[f"ollama:{answer.model}", *tools_used],
        )

    def _ask_openrouter(
        self,
        question: str,
        model: str | None,
        api_key: str | None,
        tools: list[str],
    ) -> SpatialResult:
        """Try answering via OpenRouter."""
        import os

        key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            return SpatialResult(
                errors=[
                    "OPENROUTER_API_KEY not set. "
                    "Set it in .env or pass api_key= to engine.ask()"
                ],
            )

        from geospark.integrations.openrouter import OpenRouterClient

        try:
            with OpenRouterClient(api_key=key, model=model, tools=tools) as client:
                answer = client.ask(question, model=model)
        except Exception as e:
            return SpatialResult(
                errors=[f"OpenRouter call failed: {e}"],
            )

        tools_used = [tc["tool"] for tc in answer.tool_calls]
        return SpatialResult(
            spatial_context=SpatialContext(
                summary=answer.answer,
                total_features=len(answer.tool_calls),
            ),
            sources=[f"openrouter:{answer.model}", *tools_used],
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
