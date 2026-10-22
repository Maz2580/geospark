"""
GeoSpark Core Engine.

The central orchestrator that connects spatial reasoning, tools, and LLM integrations.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from geospark.engine.crs_handler import CRSHandler
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import SpatialContext, SpatialQuery, SpatialResult
from geospark.tools.registry import ToolRegistry

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_COORD_TOLERANCE_DEG = 1e-3  # about 100 m: a coordinate "matches" a trusted one within this


def _point_coords(value: Any) -> tuple[float, float] | None:
    """(lon, lat) of a GeoJSON Point, else None."""
    if isinstance(value, dict) and value.get("type") == "Point":
        c = value.get("coordinates")
        if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(v, (int, float)) for v in c[:2]):
            return float(c[0]), float(c[1])
    return None


def _coordinates_supplied_by_model(tool: str, args: dict[str, Any]) -> list[tuple[float, float]]:
    """The (lon, lat) inputs a tool call received from the model itself (not looked up by the server)."""
    out: list[tuple[float, float]] = []
    if tool == "calculate_distance":
        for side in ("a", "b"):
            if not args.get(f"place_{side}"):
                pt = _point_coords(args.get(f"point_{side}"))
                if pt:
                    out.append(pt)
    elif tool == "check_spatial_relationship":
        out.extend(pt for pt in (_point_coords(args.get("geometry_a")), _point_coords(args.get("geometry_b"))) if pt)
    elif tool in ("get_elevation", "spatial_operation", "reverse_geocode"):
        lat, lon = args.get("latitude"), args.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            out.append((float(lon), float(lat)))
    return out


def _from_tool_reply(tool: str, body: Any) -> list[tuple[float, float]]:
    """(lon, lat) of places a tool looked up: geocode results and server-geocoded distance places."""
    out: list[tuple[float, float]] = []
    if not isinstance(body, dict):
        return out
    if tool in ("geocode", "reverse_geocode"):
        for f in body.get("features") or []:
            pt = _point_coords((f or {}).get("geometry"))
            if pt:
                out.append(pt)
    for place in body.get("places") or []:
        c = (place or {}).get("coordinates")
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            out.append((float(c[0]), float(c[1])))
    return out


def _matches(pt: tuple[float, float], trusted: list[tuple[float, float]]) -> bool:
    return any(abs(pt[0] - t[0]) <= _COORD_TOLERANCE_DEG and abs(pt[1] - t[1]) <= _COORD_TOLERANCE_DEG for t in trusted)


def _in_question(pt: tuple[float, float], numbers: list[float]) -> bool:
    def present(v: float) -> bool:
        return any(abs(v - n) <= _COORD_TOLERANCE_DEG for n in numbers)

    return present(pt[0]) and present(pt[1])


def answer_to_result(answer: Any, model_source: str, question: str = "") -> SpatialResult:
    """Turn an LLM answer into a checkable result: the tools' provenance, units, caveats and
    the places they found travel with the answer, so a reader can see where each number came from.

    It also checks the model's inputs. Coordinates a tool received that no lookup in this run
    produced, and that are not in the question, may have been recalled (or invented) by the model.
    The tool then computed correctly from possibly wrong points, so the answer is marked as not
    fully checked (``quality["unverified_coordinates"]``) and the reason is given as a caveat.
    """
    from geospark.protocol.provenance import Provenance
    from geospark.protocol.schema import SpatialFeature

    provenance: list[Provenance] = []
    seen: set[tuple[str, str | None]] = set()
    units: dict[str, str] = {}
    warnings: list[str] = []
    quality: dict[str, Any] = {}
    features: list[SpatialFeature] = []
    trusted: list[tuple[float, float]] = []
    numbers = [float(n) for n in _NUMBER.findall(question or "")]
    failed_tools = unverified = 0
    for call in answer.tool_calls:
        tool = str(call.get("tool"))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        reply = call.get("result") if isinstance(call.get("result"), dict) else {}
        suspicious = [pt for pt in _coordinates_supplied_by_model(tool, args)
                      if not _matches(pt, trusted) and not _in_question(pt, numbers)]
        if suspicious:
            unverified += len(suspicious)
            shown = ", ".join(f"[{lon:.4f}, {lat:.4f}]" for lon, lat in suspicious)
            warnings.append(
                f"{tool} was given coordinates {shown} that no geocode call in this answer produced and that "
                "are not in the question, so the model may have supplied them from memory. The result is "
                "computed exactly, but possibly for the wrong places."
            )
        if reply.get("status") == "error" or (reply.get("errors") and not reply.get("result")):
            err = reply.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else None
            failed_tools += 1
            warnings.append(f"Tool {tool} failed: {message or (reply.get('errors') or ['unknown error'])[0]}")
            continue
        meta = reply.get("metadata") or {}
        for item in meta.get("provenance") or []:
            try:
                p = Provenance(**item)
            except Exception:
                continue
            if (p.source, p.method) not in seen:
                seen.add((p.source, p.method))
                provenance.append(p)
        units.update(meta.get("units") or {})
        warnings.extend(w for w in meta.get("warnings") or [] if w not in warnings)
        quality.update(meta.get("quality") or {})
        body = reply.get("result")
        trusted.extend(_from_tool_reply(tool, body))
        found = (body.get("features") or []) if isinstance(body, dict) else []
        if tool in ("geocode", "reverse_geocode") and found:
            with contextlib.suppress(Exception):
                features.append(SpatialFeature(**found[0]))  # the best match is the one the model used
        for place in (body.get("places") or []) if isinstance(body, dict) else []:
            with contextlib.suppress(Exception):
                features.append(SpatialFeature(
                    geometry={"type": "Point", "coordinates": place["coordinates"]},
                    properties={"display_name": place.get("display_name") or place.get("query")},
                ))
    if failed_tools:
        quality["failed_tools"] = failed_tools
    if unverified:
        quality["unverified_coordinates"] = unverified
    return SpatialResult(
        features=features,
        spatial_context=SpatialContext(summary=answer.answer, total_features=len(answer.tool_calls), units=units),
        sources=[model_source, *[tc["tool"] for tc in answer.tool_calls]],
        provenance=provenance,
        warnings=warnings,
        quality=quality,
    )


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

        # Normalize CRS if needed (both the main geometry and any second geometry)
        if query.crs != "EPSG:4326" and (
            query.geometry or (query.metadata or {}).get("geometry_b")
        ):
            query = self._normalize_crs(query)

        # Route to appropriate handler. Reasoning operations enrich their own results
        # (provenance, units, quality); tool results are enriched here.
        result = self._route_query(query)
        if not self.spatial_reasoner_handles(query):
            from geospark.protocol.provenance import enrich

            enrich(result, query.operation.value)

        # Add execution metadata
        result.execution_time_ms = (time.time() - start_time) * 1000
        from geospark.runs import record

        record("compute", query.operation.value, query, result)
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

        url = ollama_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
        use_model = model or os.getenv("GEOSPARK_OLLAMA_MODEL") or "qwen2.5:7b"

        from geospark.integrations.ollama_tools import OllamaClient

        try:
            with OllamaClient(model=use_model, base_url=url, tools=tools) as client:
                answer = client.ask(question, model=use_model)
        except Exception as e:
            return SpatialResult(
                errors=[f"Ollama call failed: {e}"],
            )

        return answer_to_result(answer, f"ollama:{answer.model}", question)

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

        return answer_to_result(answer, f"openrouter:{answer.model}", question)

    def chain(self, steps: list[dict[str, Any]]) -> QueryChain:
        """Create a chain of spatial operations."""
        return QueryChain(engine=self, steps=steps)

    def _normalize_crs(self, query: SpatialQuery) -> SpatialQuery:
        """Transform the query geometry, and ``metadata["geometry_b"]``, to EPSG:4326.

        Distance, topology and overlay operations compare ``geometry`` with
        ``geometry_b``; transforming only one of them would compare coordinates in two
        different CRSs and silently give wrong answers.
        """
        update: dict[str, Any] = {"crs": "EPSG:4326"}
        if query.geometry is not None:
            update["geometry"] = self.crs_handler.transform_geometry(
                query.geometry, from_crs=query.crs, to_crs="EPSG:4326"
            )
        metadata = dict(query.metadata or {})
        geom_b = metadata.get("geometry_b")
        if isinstance(geom_b, dict):
            from shapely.geometry import mapping, shape

            from geospark.engine.crs_handler import reproject

            transformer = self.crs_handler.get_transformer(query.crs, "EPSG:4326")
            metadata["geometry_b"] = dict(mapping(reproject(shape(geom_b), transformer)))
            update["metadata"] = metadata
        return query.model_copy(update=update)

    _REASONING_OPS = frozenset({
        "contains", "intersects", "touches", "crosses", "overlaps", "within", "disjoint",
        "distance", "area", "length", "buffer", "union", "intersection", "difference",
        "convex_hull", "centroid",
    })

    def spatial_reasoner_handles(self, query: SpatialQuery) -> bool:
        return query.operation.value in self._REASONING_OPS

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
