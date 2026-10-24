"""
GeoSpark Core Engine.

The central orchestrator that connects spatial reasoning, tools, and LLM integrations.
"""

from __future__ import annotations

import contextlib
import math
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
        out.extend(pt for side in ("a", "b") if not args.get(f"place_{side}")
                   and (pt := _point_coords(args.get(f"geometry_{side}"))))
    elif tool in ("get_elevation", "spatial_operation", "reverse_geocode", "find_nearby_places", "get_weather"):
        if args.get("place"):
            return out  # looked up by the server
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
    places = list(body.get("places") or [])
    if isinstance(body.get("place"), dict):
        places.append(body["place"])
    for place in places:
        c = (place or {}).get("coordinates")
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            out.append((float(c[0]), float(c[1])))
    return out


_ZONE = re.compile(r"\b(?:MGA|UTM)?\s*zone\s*(\d{1,2})\b", re.I)
_DATUMS = ("GDA94", "GDA2020", "OSGB36", "NAD27", "NAD83", "ETRS89", "NZGD2000")


def _crs_mismatches(question: str, calls: list[dict[str, Any]]) -> list[str]:
    """Target systems of coordinate transformations that don't match what the question asks for.

    Live: asked for GDA2020 / MGA zone 55, the model picked a Lambert projection's EPSG code and still
    described the result as MGA zone 55. A target counts as matching when its zone (if the question
    names zones) and its datum (if the question names datums) are among those the question names.
    """
    zones = set(_ZONE.findall(question))
    datums = {d for d in _DATUMS if re.search(rf"\b{d}\b", question, re.I)}
    out = []
    for c in calls:
        if c.get("tool") != "transform_coordinates" or _failed(c.get("result")):
            continue
        target = str(((c.get("result") or {}).get("result") or {}).get("target_crs") or "")
        if not target:
            continue
        zone = _ZONE.search(target)
        wrong_zone = bool(zones) and "/" in target and (zone is None or zone.group(1) not in zones)
        datum = target.split("/")[0].strip()
        wrong_datum = bool(datums) and datum.upper() in _DATUMS and datum.upper() not in {d.upper() for d in datums}
        if (wrong_zone or wrong_datum) and target not in out:
            out.append(target)
    return out


# A quantity in an answer: a number and the unit after it ("3,137 square kilometres", "6.47 km")
_QUANTITY = re.compile(
    r"(?<![\w.,\u00a0\u2009\u202f])(\d{1,3}(?:[,\u00a0\u2009\u202f ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(km²|km2|m²|m2|square kilomet(?:re|er)s?|square met(?:re|er)s?|sq\.? ?km|sq\.? ?m|hectares?|ha|"
    r"kilomet(?:re|er)s?|km|met(?:re|er)s?|m)(?![\w²])", re.I)
# Factor from the unit to metres (lengths) or square metres (areas)
_UNIT_TO_SI = {"km": 1e3, "kilometre": 1e3, "kilometer": 1e3, "m": 1.0, "metre": 1.0, "meter": 1.0,
               "km²": 1e6, "km2": 1e6, "sq km": 1e6, "square kilometre": 1e6, "square kilometer": 1e6,
               "m²": 1.0, "m2": 1.0, "sq m": 1.0, "square metre": 1.0, "square meter": 1.0,
               "hectare": 1e4, "ha": 1e4}


def _unit_factor(unit: str) -> float | None:
    u = re.sub(r"\s+", " ", unit.lower().replace("sq.", "sq").strip())
    u = u[:-1] if u.endswith("s") and u not in ("ha",) else u
    return _UNIT_TO_SI.get(u)


def _numbers_in(value: Any, out: list[float]) -> None:
    """Every number in a tool reply, however deeply nested."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            out.append(float(value))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, out)
    elif isinstance(value, str):
        out.extend(float(n) for n in _NUMBER.findall(value) if len(n) < 20)


def _unsupported_quantities(answer: str, calls: list[dict[str, Any]], question: str) -> list[str]:
    """Quantities the answer states that no tool returned (allowing unit changes and rounding).

    Live: a buffer of 3,136,548 m² was reported as "3,137 square kilometres". Small models do the
    arithmetic around tool results themselves; a number that can't be traced back is flagged.
    """
    known: list[float] = []
    for c in calls:
        if not _failed(c.get("result")):
            reply = c.get("result") or {}
            _numbers_in(reply.get("result"), known)
            meta = reply.get("metadata") or {}
            _numbers_in([meta.get("warnings"), meta.get("quality")], known)  # e.g. a stated model uncertainty
    _numbers_in(question, known)
    known = [abs(k) for k in known if k != 0]
    if not known:
        return []
    # Sums and differences of two returned values ("20 km closer") are arithmetic on checked numbers
    few = sorted(set(known))[:60]
    known += [a + b for i, a in enumerate(few) for b in few[i:]] + [abs(a - b) for i, a in enumerate(few) for b in few[i + 1:]]
    bad: list[str] = []
    for m in _QUANTITY.finditer(answer or ""):
        text, unit = m.group(1), m.group(2)
        before = (answer or "")[max(0, m.start() - 25):m.start()].lower()
        if re.search(r"(rounded to|to the nearest|precision of|accurate to|accuracy of|±|\+/-)\s*(about |approximately )?$", before):
            continue  # a stated precision, not a measured quantity
        factor = _unit_factor(unit)
        if factor is None:
            continue
        text = re.sub(r"[\u00a0\u2009\u202f ]", ",", text)  # "2 726 638.60" -> "2,726,638.60"
        value = float(text.replace(",", ""))
        digits = text.replace(",", "")
        if "." in digits:
            step = 10 ** -len(digits.split(".")[1])  # "6.47" is stated to 0.01
        else:
            step = 10 ** (len(digits) - len(digits.rstrip("0"))) if digits.rstrip("0") else 1  # "6000" to 1000
        si = value * factor
        # the stated number's own rounding, or 1% ("about 6.5 km" for 6,473 m)
        tolerance = max(0.5 * step * factor, 0.01 * si)
        if not any(abs(si - k) <= tolerance for k in known):
            bad.append(f"{text} {unit}")
    return list(dict.fromkeys(bad))


_COMPARATIVE = re.compile(
    r"\b((?:the\s+)?[A-Z][\w'\u2019-]*(?:\s+[A-Z][\w'\u2019-]*){0,4})\s+(?:is|are|lies|sits)\s+(?:the\s+)?"
    r"(closer|nearer|farther|further|larger|bigger|smaller|higher|lower|taller|longer|shorter)\b")


def _self_contradiction(answer: str) -> list[str]:
    """Two different places named with the same comparative ("Sunshine Coast is closer" … "Gold Coast
    is closer"). Live: Qwen 3.5 4B's first line contradicted its own table and its last line."""
    seen: dict[str, str] = {}
    for m in _COMPARATIVE.finditer(answer.replace("*", "")):
        subject = re.sub(r"^the\s+", "", m.group(1).strip(), flags=re.I)
        word = {"nearer": "closer", "further": "farther", "bigger": "larger", "taller": "higher"}.get(m.group(2).lower(), m.group(2).lower())
        if word in seen and seen[word].lower() != subject.lower():
            return [f"{seen[word]} is {word}", f"{subject} is {word}"]
        seen.setdefault(word, subject)
    return []


def _comparison_conflicts(answer: str, calls: list[dict[str, Any]]) -> list[str]:
    """'X is closer/farther' claims that contradict the distances the tools measured.

    Live: Qwen 3.5 4B wrote "Sunshine Coast is closer to Brisbane" after measuring 90.52 km to the
    Sunshine Coast and 70.58 km to the Gold Coast.
    """
    measured: list[tuple[str, float]] = []  # (the places' names, distance)
    for c in calls:
        if c.get("tool") != "calculate_distance" or _failed(c.get("result")):
            continue
        body = (c.get("result") or {}).get("result") or {}
        names = " ".join(str(p.get("query", "")) + " " + str(p.get("display_name", "")) for p in body.get("places") or [])
        names += " " + " ".join(str(v) for k, v in (c.get("args") or {}).items() if k.startswith("place"))
        if isinstance(body.get("distance_m"), (int, float)) and names.strip():
            measured.append((names.lower(), float(body["distance_m"])))
    if len(measured) < 2:
        return []
    out = []
    for m in _COMPARATIVE.finditer(answer.replace("*", "")):
        word = m.group(2).lower()
        if word not in ("closer", "nearer", "farther", "further"):
            continue
        subject = re.sub(r"^the\s+", "", m.group(1).strip(), flags=re.I).lower()
        mine = [d for names, d in measured if subject in names]
        others = [d for names, d in measured if subject not in names]
        if not mine or not others:
            continue
        nearer = word in ("closer", "nearer")
        if (nearer and min(mine) > min(others)) or (not nearer and max(mine) < max(others)):
            out.append(f"{m.group(1).strip()} is {word}")
    return list(dict.fromkeys(out))


def _failed(reply: Any) -> bool:
    if not isinstance(reply, dict):
        return True
    return reply.get("status") == "error" or bool(reply.get("errors") and not reply.get("result"))


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
    calls = list(answer.tool_calls)
    for index, call in enumerate(calls):
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
        if _failed(reply):
            err = reply.get("error") or {}
            message = err.get("message") or "" if isinstance(err, dict) else ""
            message = message or (reply.get("errors") or ["unknown error"])[0]
            if any(str(later.get("tool")) == tool and not _failed(later.get("result")) for later in calls[index + 1:]):
                # The model read the error and called the tool again correctly: not a gap in the answer
                warnings.append(f"A first {tool} call failed ({message}); it was retried successfully.")
            else:
                failed_tools += 1
                warnings.append(f"Tool {tool} failed: {message}")
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
        if isinstance(body, dict) and isinstance(body.get("place"), dict):
            body = {**body, "places": [*(body.get("places") or []), body["place"]]}
        for place in (body.get("places") or []) if isinstance(body, dict) else []:
            if not place.get("coordinates"):
                continue
            with contextlib.suppress(Exception):
                features.append(SpatialFeature(
                    geometry={"type": "Point", "coordinates": place["coordinates"]},
                    properties={"display_name": place.get("display_name") or place.get("query")},
                ))
        if tool == "find_nearby_places" and isinstance(body, dict):
            for kind, items in (body.get("nearest") or {}).items():
                for item in items:
                    with contextlib.suppress(Exception):
                        features.append(SpatialFeature(
                            geometry={"type": "Point", "coordinates": item["coordinates"][:2]},
                            properties={"name": item.get("name"), "type": kind, "distance_m": item.get("distance_m")},
                        ))
    if not (getattr(answer, "answer", "") or "").strip():
        # Live: a small model called the tools, then spent its reply on hidden reasoning and returned no text
        quality["no_answer"] = True
        warnings.append("The model returned no answer text after its tool calls, so there is no answer to check.")
    unsupported = _unsupported_quantities(getattr(answer, "answer", "") or "", calls, question or "") if calls else []
    if unsupported:
        quality["unsupported_numbers"] = unsupported
        warnings.append(f"The answer states {', '.join(unsupported)}, which no tool returned (even allowing for unit "
                        "changes and rounding); treat that number as the model's own arithmetic, not a checked value.")
    conflicts = _comparison_conflicts(getattr(answer, "answer", "") or "", calls)
    if conflicts:
        quality["contradicts_tools"] = conflicts
        warnings.append(f"The answer says {', '.join(repr(c) for c in conflicts)}, which contradicts the distances the "
                        "tools measured.")
    contradiction = _self_contradiction(getattr(answer, "answer", "") or "")
    if contradiction:
        quality["self_contradiction"] = contradiction
        warnings.append(f"The answer contradicts itself: it says {contradiction[0]!r} and {contradiction[1]!r}.")
    mismatched = _crs_mismatches(question or "", calls)
    if mismatched:
        quality["crs_mismatch"] = mismatched
        warnings.append(f"Coordinates were converted to {', '.join(mismatched)}, which is not the system the question "
                        "asks for, so the answer may describe them as something they are not.")
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

        fallback = self._ask_openrouter(question, model, api_key, tools)
        if fallback.errors:
            # Both failed: say so in words, not as two raw HTTP errors (live: an OpenRouter 404 was
            # all a visitor saw after the local model timed out)
            fallback.errors = [
                "The answer could not be computed right now: the local language model did not answer "
                "in time and the backup model service also failed. Please try again in a minute.",
                *ollama_result.errors, *fallback.errors,
            ]
        return fallback

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
