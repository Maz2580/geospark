"""
GeoSpark REST API.

FastAPI server exposing GeoSpark capabilities via HTTP.
Designed to run in Docker or standalone.

Usage:
    uvicorn geospark.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import hmac
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from shapely.errors import ShapelyError

from geospark import __version__, security
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.provenance import Provenance, engine_provenance, enrich
from geospark.protocol.schema import (
    Point,
    SpatialFilter,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)
from geospark.sandbox import (
    check_context_quota,
    check_memory_quota,
    namespace_for,
    sandboxes,
)
from geospark.security import check_model, llm_slot, verify_admin

load_dotenv()

# Global engine instance
_engine: Engine | None = None
_start_time: float = time.time()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(tools=["geocoder", "terrain"])
    return _engine


# --- Hosted MCP over Streamable HTTP (opt-in: GEOSPARK_MCP_HTTP=true) ---
# Public and read-only: the same tools as `geospark-mcp`, under the API's rate limits,
# body cap and the shared concurrency cap for heavy tools. Stateless (no session state).
_mcp_server: Any = None


class _McpExactPath:
    """Serve POST /mcp directly. The mount answers /mcp/, and a 307 redirect on POST breaks
    some MCP clients, while /mcp is the URL people paste into their client config."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


def mcp_http_enabled() -> bool:
    return os.getenv("GEOSPARK_MCP_HTTP", "").lower() in ("1", "true", "yes")


def enable_mcp_http(target: FastAPI) -> None:
    """Mount the MCP server at /mcp (idempotent)."""
    global _mcp_server
    if _mcp_server is not None:
        return
    from geospark.mcp_servers.server import create_server

    _mcp_server = create_server()
    target.mount(
        "/mcp",
        _mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            # Served publicly behind the tunnel: not a localhost-only server, so no
            # localhost DNS-rebinding guard (which would reject the public Host header)
            host="0.0.0.0",
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate security config and initialize the engine on startup."""
    security.check_startup_config()
    get_engine()
    if _mcp_server is not None:
        async with _mcp_server.session_manager.run():
            yield
    else:
        yield


app = FastAPI(
    title="GeoSpark API",
    description="The Open-Source Geospatial Intelligence Engine. Give any AI model a spatial mind.",
    version=__version__,
    lifespan=lifespan,
)

# Rate limiting — sliding window per IP/API key (Phase 8A)
from geospark.middleware.rate_limiter import RateLimitMiddleware, set_route_limit  # noqa: E402

app.add_middleware(RateLimitMiddleware)
# Expensive routes (LLM calls, agents, embeddings, upstream fan-out) get lower limits
for _prefix in (
    "/api/v1/agent/",
    "/api/v1/ask",
    "/api/v1/flows/build",
    "/api/v1/flows/templates/",
    "/api/v1/memory/",
    "/api/v1/data/status",
    "/api/v1/overture/",
):
    set_route_limit(_prefix, int(os.getenv("GEOSPARK_RATE_LIMIT_EXPENSIVE_RPM", "12")))
# Cheap listings under those prefixes keep the normal limit (longest prefix wins)
for _prefix in ("/api/v1/agent/list", "/api/v1/memory/stats"):
    set_route_limit(_prefix, int(os.getenv("GEOSPARK_RATE_LIMIT_RPM", "60")) + 10)

# Audit logging — structured JSONL per day (Phase 8A)
from geospark.middleware.audit_log import AuditLogMiddleware  # noqa: E402

app.add_middleware(AuditLogMiddleware)

# Usage tracking — per-endpoint and per-key counters (Phase 8A)
from geospark.middleware.usage_tracker import UsageTrackingMiddleware  # noqa: E402

app.add_middleware(UsageTrackingMiddleware)

# Request body cap (default 1 MB)
from geospark.middleware.body_limit import BodySizeLimitMiddleware  # noqa: E402

app.add_middleware(BodySizeLimitMiddleware)

# CORS last = outermost, so every response (including 413/429) carries CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# Registered unconditionally (middleware can only be added before startup); a no-op
# unless /mcp is mounted
app.add_middleware(_McpExactPath)

if mcp_http_enabled():
    enable_mcp_http(app)
    set_route_limit("/mcp", int(os.getenv("GEOSPARK_RATE_LIMIT_MCP_RPM", "60")))

# --- Static UI ---
_ui_dir = Path(__file__).parent / "ui"
if _ui_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_ui_dir / "assets")), name="assets")


def _serve_page(page: str) -> HTMLResponse:
    """Serve an HTML page from the ui/ directory."""
    path = _ui_dir / page
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui_index():
    return _serve_page("index.html")


@app.get("/playground", response_class=HTMLResponse, include_in_schema=False)
async def ui_playground():
    return _serve_page("playground.html")


@app.get("/agents", response_class=HTMLResponse, include_in_schema=False)
async def ui_agents():
    return _serve_page("agents.html")


@app.get("/data", response_class=HTMLResponse, include_in_schema=False)
async def ui_data():
    return _serve_page("data.html")


@app.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def ui_status():
    return _serve_page("status.html")


@app.get("/memory", response_class=HTMLResponse, include_in_schema=False)
async def ui_memory():
    return _serve_page("memory.html")


@app.get("/context", response_class=HTMLResponse, include_in_schema=False)
async def ui_context():
    return _serve_page("context.html")


@app.get("/guide", response_class=HTMLResponse, include_in_schema=False)
async def ui_guide():
    return _serve_page("guide.html")


@app.get("/flows", response_class=HTMLResponse, include_in_schema=False)
async def ui_flows():
    return _serve_page("flows.html")


# --- LLM Gateway Router ---
from geospark.llm_gateway import router as llm_router  # noqa: E402

app.include_router(llm_router)

# --- API Key Auth (optional) ---

_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_security = Security(_bearer_scheme)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = _bearer_security,
) -> None:
    """Check Bearer token against GEOSPARK_API_KEY env var.

    If GEOSPARK_API_KEY is not set, all requests are allowed (open mode).
    """
    api_key = os.getenv("GEOSPARK_API_KEY")
    if not api_key:
        return  # No key configured — open access
    presented = credentials.credentials if credentials is not None else ""
    admin = os.getenv("GEOSPARK_ADMIN_TOKEN", "")
    if presented and (
        hmac.compare_digest(presented.encode(), api_key.encode())
        or (admin and hmac.compare_digest(presented.encode(), admin.encode()))
    ):
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Request/Response Models ---


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    tools: list[str] = []


class GeocodeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Address or place name to geocode")
    limit: int = Field(5, ge=1, le=40, description="Max results")


class SpatialQueryRequest(BaseModel):
    operation: str = Field(..., description="Spatial operation to perform")
    latitude: float | None = Field(None, ge=-90, le=90, description="Latitude")
    longitude: float | None = Field(None, ge=-180, le=180, description="Longitude")
    radius_m: float | None = Field(None, ge=0, le=50_000, description="Radius in meters")
    category: str | None = Field(None, description="Feature category filter")


class RelationshipRequest(BaseModel):
    geometry_a: dict[str, Any] = Field(..., description="First geometry (GeoJSON)")
    geometry_b: dict[str, Any] = Field(..., description="Second geometry (GeoJSON)")
    relationship: str = Field(
        ...,
        description="Topological relationship to check",
        pattern="^(contains|intersects|within|touches|crosses|overlaps|disjoint)$",
    )


class RelationshipResponse(BaseModel):
    relationship: str
    result: bool
    note: str = "Ground-truth spatial reasoning via GeoSpark"
    provenance: list[Provenance] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DistanceRequest(BaseModel):
    lat_a: float = Field(..., ge=-90, le=90, description="Latitude of point A")
    lon_a: float = Field(..., ge=-180, le=180, description="Longitude of point A")
    lat_b: float = Field(..., ge=-90, le=90, description="Latitude of point B")
    lon_b: float = Field(..., ge=-180, le=180, description="Longitude of point B")


class DistanceResponse(BaseModel):
    distance_m: float
    distance_km: float
    note: str = "Geodesic distance on WGS84 ellipsoid"
    units: dict[str, str] = Field(default_factory=lambda: {"distance_m": "metre", "distance_km": "kilometre"})
    provenance: list[Provenance] = Field(default_factory=list)


class ElevationRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="Latitude")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="Natural language spatial question")
    model: str | None = Field(None, max_length=200, description="Override LLM model")


class AskResponse(BaseModel):
    answer: str
    model: str
    tools_used: list[str] = []
    tokens_used: int = 0


# --- Endpoints ---


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check."""
    engine = get_engine()
    return HealthResponse(tools=engine.available_tools)


@app.get("/api/v1/status")
async def status():
    """System status with uptime, memory, and tool information."""
    import sys

    uptime_seconds = time.time() - _start_time

    # Read memory from /proc on Linux (Docker), fallback gracefully
    memory: dict[str, Any] = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    memory["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmSize:"):
                    memory["vms_mb"] = round(int(line.split()[1]) / 1024, 1)
    except OSError:
        memory["note"] = "Memory info unavailable on this platform"

    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": round(uptime_seconds, 1),
        "python_version": sys.version,
        "memory": memory,
        "tools": {
            "loaded": get_engine().available_tools,
            "count": len(get_engine().available_tools),
        },
        "environment": os.getenv("GEOSPARK_ENV", "development"),
    }


@app.get("/api/v1/info")
async def info():
    """System information."""
    return {
        "name": "GeoSpark",
        "version": __version__,
        "protocol": "GSP v0.1",
        "tools": get_engine().available_tools,
        "database": os.getenv("GEOSPARK_DB_BACKEND", "memory"),
    }


# --- GeoJSON output (QGIS-ready): ?format=geojson or Accept: application/geo+json ---

GEOJSON_MEDIA_TYPE = "application/geo+json"
FormatParam = Query(None, pattern="^(json|geojson)$", description="'geojson' returns an RFC 7946 FeatureCollection")


def _wants_geojson(http: Request, fmt: str | None) -> bool:
    return fmt == "geojson" or (fmt is None and GEOJSON_MEDIA_TYPE in http.headers.get("accept", ""))


def _geojson(collection: dict[str, Any]) -> JSONResponse:
    return JSONResponse(collection, media_type=GEOJSON_MEDIA_TYPE)


# Handlers that do blocking work (HTTP to Nominatim/Overpass/Ollama, LLM tool loops) are
# plain ``def``: FastAPI runs them in its thread pool, so one slow request can't freeze the
# event loop for everyone else (the API runs a single uvicorn worker).
@app.post("/api/v1/geocode", response_model=SpatialResult, dependencies=[Depends(verify_api_key)])
def geocode(request: GeocodeRequest, http: Request, format: str | None = FormatParam):
    """Geocode an address or place name."""
    engine = get_engine()
    query = SpatialQuery(
        operation=SpatialOperation.GEOCODE,
        metadata={"query": request.query},
        limit=request.limit,
    )
    result = engine.execute(query)
    return _geojson(result.to_geojson()) if _wants_geojson(http, format) else result


@app.post("/api/v1/query", response_model=SpatialResult, dependencies=[Depends(verify_api_key)])
def spatial_query(request: SpatialQueryRequest, http: Request, format: str | None = FormatParam):
    """Execute a spatial query."""
    engine = get_engine()

    geometry = None
    if request.latitude is not None and request.longitude is not None:
        geometry = Point.from_latlon(request.latitude, request.longitude)

    try:
        op = SpatialOperation(request.operation)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown operation: {request.operation}. "
            f"Available: {[o.value for o in SpatialOperation]}",
        ) from e

    query = SpatialQuery(
        operation=op,
        geometry=geometry,
        radius_m=request.radius_m,
        filters=SpatialFilter(category=request.category) if request.category else None,
    )
    result = engine.execute(query)
    return _geojson(result.to_geojson()) if _wants_geojson(http, format) else result


@app.post("/api/v1/check-relationship", response_model=RelationshipResponse, dependencies=[Depends(verify_api_key)])
async def check_relationship(request: RelationshipRequest):
    """
    Check topological relationship between two geometries.

    This is GeoSpark's killer feature -- ground-truth spatial reasoning
    that LLMs get wrong ~80% of the time.
    """
    try:
        result = SpatialReasoner.check_relationship(
            request.geometry_a,
            request.geometry_b,
            request.relationship,
        )
        checked = enrich(SpatialResult(), request.relationship, [request.geometry_a, request.geometry_b])
        return RelationshipResponse(
            relationship=request.relationship,
            result=result,
            provenance=checked.provenance,
            warnings=checked.warnings,
        )
    except ValueError as e:
        # Validation already explains the problem (invalid shape, [lat, lon] order, ...)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (KeyError, TypeError, AttributeError, ShapelyError) as e:
        # Malformed GeoJSON is the caller's mistake (400), not a server error (500)
        raise HTTPException(
            status_code=400, detail=f"Invalid GeoJSON geometry: {type(e).__name__}: {e}"
        ) from e


@app.post(
    "/api/v1/ask",
    response_model=AskResponse,
    dependencies=[Depends(verify_api_key), Depends(llm_slot)],
)
def ask(request: AskRequest, http: Request):
    """
    Ask a natural language spatial question.

    Tries local Ollama (Qwen 2.5 7B) first, falls back to OpenRouter.
    """
    check_model(http, request.model)
    engine = get_engine()
    result = engine.ask(request.question, model=request.model)

    if result.errors:
        raise HTTPException(status_code=503, detail=result.errors[0])

    # sources format: ["ollama:qwen2.5:7b", "geocode", "calculate_distance"]
    model_source = result.sources[0] if result.sources else "unknown"
    tools_used = result.sources[1:] if len(result.sources) > 1 else []
    return AskResponse(
        answer=result.spatial_context.summary,
        model=model_source,
        tools_used=tools_used,
        tokens_used=0,
    )


@app.post("/api/v1/distance", response_model=DistanceResponse, dependencies=[Depends(verify_api_key)])
async def distance(request: DistanceRequest):
    """Calculate geodesic distance between two points."""
    geom_a = {"type": "Point", "coordinates": [request.lon_a, request.lat_a]}
    geom_b = {"type": "Point", "coordinates": [request.lon_b, request.lat_b]}
    d = SpatialReasoner.calculate_distance(geom_a, geom_b)
    return DistanceResponse(
        distance_m=round(d, 2), distance_km=round(d / 1000, 3), provenance=[engine_provenance("distance")]
    )


@app.post("/api/v1/elevation", dependencies=[Depends(verify_api_key)])
async def elevation(request: ElevationRequest, http: Request, format: str | None = FormatParam):
    """Get elevation at a point (meters above sea level)."""
    engine = get_engine()
    query = SpatialQuery(
        operation=SpatialOperation.ELEVATION,
        geometry=Point.from_latlon(request.latitude, request.longitude),
    )
    # The lookup is network-bound and synchronous; run it off the event loop
    # so one slow elevation read does not stall every other request.
    result = await asyncio.to_thread(engine.execute, query)
    if result.errors:
        raise HTTPException(status_code=502, detail=result.errors[0])
    if _wants_geojson(http, format):
        return _geojson(result.to_geojson())
    props = result.features[0].properties if result.features else {}
    response = {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "elevation_m": props.get("elevation_m"),
        "source": _ELEVATION_SOURCE_NAMES.get(result.sources[0] if result.sources else "", "unknown"),
        "vertical_datum": props.get("vertical_datum"),
    }
    for key in ("attribution", "fallback_note"):
        if props.get(key):
            response[key] = props[key]
    # Verifiable answer: accuracy of the DEM, units, and where the value came from
    response["units"] = {"elevation_m": "metre"}
    if result.quality:
        response["quality"] = result.quality
    response["provenance"] = [p.model_dump(mode="json", exclude_none=True) for p in result.provenance]
    return response


_ELEVATION_SOURCE_NAMES = {
    "copernicus-dem": "Copernicus DEM GLO-30",
    "open-elevation-api": "Open Elevation API",
}


@app.get("/api/v1/tools")
async def list_tools():
    """List available GeoSpark tools."""
    from geospark.tools.registry import TOOL_CLASSES

    return {
        "loaded": get_engine().available_tools,
        "available": list(TOOL_CLASSES.keys()),
    }


@app.get("/api/v1/models")
async def list_models():
    """List available free LLM models."""
    from geospark.integrations.openrouter import FREE_MODELS

    return {"models": FREE_MODELS}


# --- Flow Endpoints ---


class TemplateRunRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict, description="Override template parameters")


@app.get("/api/v1/flows/templates")
async def flow_list_templates():
    """List available flow templates."""
    from geospark.flows import list_templates

    return {"templates": list_templates()}


@app.get("/api/v1/flows/templates/{template_name}")
async def flow_get_template(template_name: str):
    """Get a flow template definition."""
    from geospark.flows import get_template

    try:
        f = get_template(template_name)
        return f.model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_name}") from None


@app.post("/api/v1/flows/templates/{template_name}/run", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def flow_run_template(template_name: str, request: TemplateRunRequest):
    """Run a flow template with optional parameter overrides."""
    from geospark.flows import FlowRunner, get_template

    try:
        f = get_template(template_name, **request.parameters)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_name}") from None

    engine = get_engine()
    runner = FlowRunner(engine=engine)
    run = runner.run(f)

    return {
        "run_id": str(run.id),
        "flow_name": f.name,
        "status": run.status,
        "steps_completed": len(run.step_results),
        "step_results": run.step_results,
        "errors": run.errors,
    }


# --- Chat-to-Flow Builder (Phase 8B) ---


class FlowBuildRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000, description="Natural-language goal for the flow")
    model: str | None = Field(
        None, max_length=200, description="Ollama model to drive the builder (default: server model)"
    )
    max_turns: int = Field(20, ge=1, le=20, description="Max LLM turns")


@app.post("/api/v1/flows/build", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def flow_build(request: FlowBuildRequest, http: Request):
    """Build a Flow from a natural-language goal via incremental LLM tool calling.

    Uses the chat-to-flow builder (Phase 8B). Each LLM turn invokes one
    builder method (add_step, add_route, set_trigger, finish_flow) against
    an internal FlowBuilder; the DAG is validated before the final Flow is
    returned. The LLM backend is Ollama by default.
    """
    from geospark.flows import ChatFlowSession, make_ollama_chat_fn

    check_model(http, request.model)
    # The Ollama URL is server configuration only: accepting it from callers would let
    # anyone make this server fetch arbitrary internal URLs (SSRF).
    session = ChatFlowSession(
        llm_fn=make_ollama_chat_fn(model=request.model or security.default_ollama_model())
    )
    try:
        result = session.run(request.goal, max_turns=request.max_turns)
    except Exception as err:
        raise HTTPException(
            status_code=502,
            detail=f"LLM backend error ({type(err).__name__})",
        ) from err

    payload: dict[str, Any] = {
        "ok": result.flow is not None,
        "turns": result.turns,
        "duration_s": result.duration_s,
        "error": result.error,
        "tool_calls": [
            {
                "tool": tc.tool,
                "arguments": tc.arguments,
                "result": tc.result,
                "ok": tc.ok,
            }
            for tc in result.tool_calls
        ],
        "flow": result.flow.model_dump() if result.flow is not None else None,
    }
    return payload


# --- Persistent Flow Endpoints ---


class SaveFlowRequest(BaseModel):
    name: str = Field(..., description="Flow name")
    description: str = Field("", description="Flow description")
    steps: list[dict[str, Any]] = Field(..., description="Flow step definitions")
    trigger: dict[str, Any] | None = Field(None, description="Trigger config")
    metadata: dict[str, Any] = Field(default_factory=dict)


def _get_store():
    """Get flow store, raise 503 if not configured."""
    from geospark.flows.persistence import get_flow_store

    store = get_flow_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Flow persistence not configured. Set GEOSPARK_FLOW_BACKEND=supabase",
        )
    return store


@app.get("/api/v1/flows")
async def flow_list():
    """List saved flows (requires persistence backend)."""
    store = _get_store()
    flows = store.list_flows()
    return {"flows": [f.model_dump() for f in flows]}


@app.post("/api/v1/flows", dependencies=[Depends(verify_admin)])
async def flow_save(request: SaveFlowRequest):
    """Save a flow definition (requires persistence backend)."""
    from geospark.flows.flow_schema import Flow, FlowStep, FlowTrigger

    store = _get_store()
    steps = [FlowStep(**s) for s in request.steps]
    trigger = FlowTrigger(**request.trigger) if request.trigger else FlowTrigger()
    flow = Flow(
        name=request.name,
        description=request.description,
        steps=steps,
        trigger=trigger,
        metadata=request.metadata,
    )
    flow_id = store.save_flow(flow)
    return {"flow_id": flow_id, "name": flow.name}


@app.get("/api/v1/flows/{flow_id}")
async def flow_get(flow_id: str):
    """Get a saved flow by ID."""
    store = _get_store()
    flow = store.get_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow.model_dump()


@app.delete("/api/v1/flows/{flow_id}", dependencies=[Depends(verify_admin)])
async def flow_delete(flow_id: str):
    """Delete a saved flow and its runs."""
    store = _get_store()
    deleted = store.delete_flow(flow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"deleted": flow_id}


@app.post("/api/v1/flows/{flow_id}/run", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def flow_run_saved(flow_id: str):
    """Run a saved flow."""
    from geospark.flows import FlowRunner

    store = _get_store()
    flow = store.get_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    runner = FlowRunner(engine=get_engine(), store=store)
    run = runner.run(flow)

    return {
        "run_id": run.id,
        "flow_id": flow_id,
        "status": run.status,
        "steps_completed": len(run.step_results),
        "errors": run.errors,
    }


@app.get("/api/v1/flow-runs")
async def flow_run_list(flow_id: str | None = None):
    """List flow runs, optionally filtered by flow_id."""
    store = _get_store()
    runs = store.list_runs(flow_id=flow_id)
    return {"runs": [r.model_dump() for r in runs]}


@app.get("/api/v1/flow-runs/{run_id}")
async def flow_run_get(run_id: str):
    """Get a specific flow run."""
    store = _get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump()


# --- Data Channel Endpoints ---


class DataChannelRequest(BaseModel):
    location: str | None = Field(None, max_length=500, description="Location name to geocode")
    lat: float | None = Field(None, ge=-90, le=90, description="Latitude")
    lon: float | None = Field(None, ge=-180, le=180, description="Longitude")
    start_date: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="End date (YYYY-MM-DD)")
    filters: dict[str, Any] = Field(default_factory=dict)


_registry = None


def _channel_registry():
    """One shared registry, so its LRU+TTL cache actually serves repeat requests."""
    global _registry
    if _registry is None:
        from geospark.data_channels import ChannelRegistry

        _registry = ChannelRegistry()
    return _registry


@app.get("/api/v1/data/channels")
async def data_list_channels():
    """List available data channels."""

    registry = _channel_registry()
    channels = registry.load_all()
    return {
        "channels": [
            {"name": ch.name, "description": ch.description, "tier": ch.tier}
            for ch in channels
        ]
    }


@app.get("/api/v1/data/status")
def data_channel_status():
    """Health check all data channels."""

    registry = _channel_registry()
    return {"channels": [s.model_dump() for s in registry.check_all()]}


@app.post("/api/v1/data/{channel_name}")
async def data_query(channel_name: str, request: DataChannelRequest):
    """Query a data channel."""

    registry = _channel_registry()
    try:
        result = await registry.search(
            channel_name,
            location=request.location,
            lat=request.lat,
            lon=request.lon,
            start_date=request.start_date,
            end_date=request.end_date,
            filters=request.filters,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Overture Maps (v0.8): places, buildings, roads, admin areas; no API key ---


class OvertureRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")
    radius_m: float = Field(500, gt=0, le=2000, description="Search radius in metres (ignored for divisions)")
    category: str | None = Field(None, max_length=100, description="Places only: e.g. 'cafe', 'pharmacy'")
    limit: int | None = Field(None, ge=1, le=2000)


@app.post("/api/v1/overture/{theme}", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def overture(theme: str, request: OvertureRequest, http: Request, format: str | None = FormatParam):
    """Overture Maps features near a point: places, buildings, transportation, or the
    administrative divisions containing it. Distances, areas and lengths are geodesic."""
    from geospark.tools.overture.client import OvertureError
    from geospark.tools.overture.client import query as overture_query

    try:
        result = overture_query(theme, request.lat, request.lon, radius_m=request.radius_m,
                                category=request.category, limit=request.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except OvertureError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return _geojson(result.to_geojson()) if _wants_geojson(http, format) else result


# --- Agent Endpoints ---


class AgentRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000, description="Natural language spatial goal")


class ReportRequest(BaseModel):
    location: str = Field(..., min_length=1, max_length=500, description="Location to analyze")
    radius_m: float = Field(2000, gt=0, le=10_000, description="Search radius in meters")


class SiteSelectRequest(BaseModel):
    within: str = Field(..., min_length=1, max_length=500, description="Search area (city/neighborhood)")
    near: list[str] = Field(default_factory=list, max_length=10, description="Amenity types to be near")
    avoid: list[str] = Field(default_factory=list, max_length=10, description="Amenity types to avoid")
    facility_type: str = Field("restaurant", max_length=100, description="Facility type to place")
    radius_m: float = Field(5000, gt=0, le=10_000, description="Search radius in meters")


@app.post("/api/v1/agent/run", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def agent_run(request: AgentRunRequest):
    """Run the autonomous spatial agent with a goal."""
    from geospark.agents import GeoAgent

    ag = GeoAgent(engine=get_engine())
    result = ag.run(request.goal)
    return result.model_dump()


@app.post("/api/v1/agent/report", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
async def agent_report(request: ReportRequest, http: Request, format: str | None = FormatParam):
    """Generate a spatial intelligence report for a location."""
    from geospark.agents import SpatialReport

    reporter = SpatialReport(engine=get_engine())
    # analyze() is synchronous and starts its own event loop for the weather
    # and air-quality channels, which fails inside this one. A worker thread
    # also keeps the server responsive during the ~20 s it takes.
    report = await asyncio.to_thread(
        reporter.analyze, request.location, radius_m=request.radius_m
    )
    if _wants_geojson(http, format):
        return _geojson(report.to_geojson())
    return report.model_dump()


@app.post("/api/v1/agent/site-select", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def agent_site_select(request: SiteSelectRequest):
    """Find optimal locations based on spatial criteria."""
    from geospark.agents import SiteSelector

    selector = SiteSelector(engine=get_engine())
    result = selector.find(
        within=request.within,
        near=request.near,
        avoid=request.avoid,
        facility_type=request.facility_type,
        radius_m=request.radius_m,
    )
    return result.model_dump()


# --- Spatial Intelligence (Memory) Endpoints ---


class MemoryRecallRequest(BaseModel):
    query: str = Field(..., max_length=1000, description="Search query for spatial memories")
    limit: int = Field(10, ge=1, le=50, description="Max results")
    memory_type: str | None = Field(None, description="Filter: 'fact' or 'episode'")


class MemoryFactRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="Spatial fact to remember")
    source: str = Field("", max_length=200, description="Source attribution")
    confidence: float = Field(1.0, ge=0, le=1, description="Confidence 0.0 to 1.0")
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemoryEpisodeRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="Spatial observation to remember")
    source: str = Field("", max_length=200, description="Source attribution")
    importance: float = Field(0.5, ge=0, le=1, description="Importance 0.0 to 1.0")
    tags: list[str] = Field(default_factory=list, max_length=20)


def _memory(http: Request):
    """The caller's memory space: a private sandbox, or the shared one for the operator."""
    namespace = namespace_for(http)
    return namespace, sandboxes.memory(namespace)


@app.post("/api/v1/memory/recall", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def memory_recall(request: MemoryRecallRequest, http: Request):
    """Recall spatial memories matching a query."""
    _, intel = _memory(http)
    results = intel.recall(
        request.query, limit=request.limit, memory_type=request.memory_type
    )
    return {"query": request.query, "results": results, "count": len(results)}


@app.post("/api/v1/memory/fact", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def memory_add_fact(request: MemoryFactRequest, http: Request):
    """Store a new spatial fact."""
    namespace, intel = _memory(http)
    check_memory_quota(namespace, intel)
    fact = intel.remember_fact(
        content=request.content,
        source=request.source,
        confidence=request.confidence,
        tags=request.tags,
    )
    return {"id": fact.id, "content": fact.content, "type": "fact"}


@app.post("/api/v1/memory/episode", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def memory_add_episode(request: MemoryEpisodeRequest, http: Request):
    """Store a timestamped spatial observation."""
    namespace, intel = _memory(http)
    check_memory_quota(namespace, intel)
    episode = intel.remember_episode(
        content=request.content,
        source=request.source,
        importance=request.importance,
        tags=request.tags,
    )
    return {"id": episode.id, "content": episode.content, "type": "episode"}


@app.get("/api/v1/memory/contradictions", dependencies=[Depends(verify_api_key)])
async def memory_contradictions(http: Request):
    """Find contradicting spatial facts."""
    _, intel = _memory(http)
    contradictions = intel.find_contradictions()
    return {
        "contradictions": [c.model_dump(mode="json") for c in contradictions],
        "count": len(contradictions),
    }


@app.get("/api/v1/memory/stats")
async def memory_stats(http: Request):
    """Spatial intelligence statistics."""
    _, intel = _memory(http)
    return intel.stats().model_dump()


@app.post("/api/v1/memory/compact", dependencies=[Depends(verify_api_key)])
def memory_compact(http: Request):
    """Compact old low-importance episodes."""
    _, intel = _memory(http)
    return intel.compact()


# --- Geospatial Context Database (Phase 7B) Endpoints ---


class ContextSaveRequest(BaseModel):
    uri: str = Field(..., description="Context URI (geospark://category/path)")
    category: str = Field(..., description="Category: missions, datasets, analysis_history")
    name: str = Field(..., description="Human-readable name")
    abstract: str = Field("", description="L0: short summary")
    overview: dict[str, Any] = Field(default_factory=dict, description="L1: structured outline")
    full_data: dict[str, Any] = Field(default_factory=dict, description="L2: complete data")
    parent_uri: str | None = Field(None)
    bounds_wgs84: list[float] | None = Field(None, description="[min_lon,min_lat,max_lon,max_lat]")
    tags: list[str] = Field(default_factory=list)
    source: str = Field("")


class ContextQueryRequest(BaseModel):
    query: str = Field("", description="Text query")
    bbox: list[float] | None = Field(None, description="Spatial filter")
    category: str | None = Field(None)
    limit: int = Field(10, ge=1, le=50)
    tier: str = Field("L0", description="L0, L1, or L2")
    include_archived: bool = Field(False)


def _contexts(http: Request):
    """(namespace, store, retriever) for the caller's context space."""
    namespace = namespace_for(http)
    store, retriever = sandboxes.contexts(namespace)
    return namespace, store, retriever


def _bad_uri(err: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(err))


@app.post("/api/v1/context/save", dependencies=[Depends(verify_api_key)])
async def context_save(request: ContextSaveRequest, http: Request):
    """Save a new geospatial context."""
    from geospark.context import GeoContext

    namespace, store, _ = _contexts(http)
    check_context_quota(namespace, store)
    try:
        ctx = GeoContext(
            uri=request.uri,
            category=request.category,
            name=request.name,
            abstract=request.abstract,
            overview=request.overview,
            full_data=request.full_data,
            parent_uri=request.parent_uri,
            bounds_wgs84=request.bounds_wgs84,
            tags=request.tags,
            source=request.source,
        )
        store.save(ctx)
    except ValueError as err:
        raise _bad_uri(err) from None
    return {"id": ctx.id, "uri": ctx.uri, "saved": True}


@app.get("/api/v1/context/load")
async def context_load(http: Request, uri: str, tier: str = "L1"):
    """Load a context by URI at a given tier."""
    from geospark.context import ContextTier

    _, store, _ = _contexts(http)
    try:
        ctx = store.load(uri, touch=True)
    except ValueError as err:
        raise _bad_uri(err) from None
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Context not found: {uri}")

    try:
        tier_enum = ContextTier(tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}") from None

    return {
        "uri": ctx.uri,
        "name": ctx.name,
        "summary": ctx.to_prompt_summary(tier_enum),
        "access_count": ctx.access_count,
        "is_archived": ctx.is_archived,
        "content": ctx.get_tier(tier_enum),
    }


@app.post("/api/v1/context/query", dependencies=[Depends(verify_api_key)])
async def context_query_endpoint(request: ContextQueryRequest, http: Request):
    """Query contexts with text, spatial, and category filters."""
    from geospark.context import ContextTier

    _, _, retriever = _contexts(http)
    try:
        tier = ContextTier(request.tier)
    except ValueError:
        tier = ContextTier.L0

    results, stats = retriever.retrieve(
        query=request.query,
        bbox=request.bbox,
        category=request.category,
        limit=request.limit,
        tier=tier,
        include_archived=request.include_archived,
    )
    return {
        "results": [
            {
                "uri": r.context.uri,
                "name": r.context.name,
                "abstract": r.context.abstract,
                "score": r.final_score,
                "semantic_score": r.semantic_score,
                "hotness_score": r.hotness_score,
                "parent_score": r.parent_score,
                "access_count": r.context.access_count,
                "category": r.context.category,
                "bounds_wgs84": r.context.bounds_wgs84,
            }
            for r in results
        ],
        "stats": stats.model_dump(),
    }


@app.get("/api/v1/context/list")
async def context_list_endpoint(
    http: Request, category: str | None = None, include_archived: bool = False
):
    """List all contexts, optionally filtered by category."""
    _, store, _ = _contexts(http)
    try:
        contexts = store.list_all(category=category, include_archived=include_archived)
    except ValueError as err:
        raise _bad_uri(err) from None
    return {
        "contexts": [
            {
                "uri": c.uri,
                "name": c.name,
                "category": c.category,
                "abstract": c.abstract,
                "access_count": c.access_count,
                "is_archived": c.is_archived,
                "bounds_wgs84": c.bounds_wgs84,
            }
            for c in contexts
        ],
        "count": len(contexts),
    }


@app.get("/api/v1/context/stats")
async def context_stats(http: Request):
    """Context database statistics."""
    _, store, retriever = _contexts(http)

    total = store.count()
    total_with_archive = store.count(include_archived=True)
    categories = store.list_categories()
    hottest = retriever.hottest(limit=5)

    return {
        "total_contexts": total,
        "archived": total_with_archive - total,
        "categories": categories,
        "hottest": [h.model_dump() for h in hottest],
    }


@app.post("/api/v1/context/archive-cold", dependencies=[Depends(verify_api_key)])
async def context_archive_cold(http: Request, threshold: float = Query(0.1, ge=0, le=1)):
    """Archive contexts with hotness below threshold."""
    _, _, retriever = _contexts(http)
    archived = retriever.archive_cold(threshold=threshold)
    return {"archived": archived, "count": len(archived)}


@app.delete("/api/v1/context/{uri:path}", dependencies=[Depends(verify_api_key)])
async def context_delete(uri: str, http: Request):
    """Delete a context permanently."""
    # URL-encoded URIs need decoding
    if not uri.startswith("geospark://"):
        uri = f"geospark://{uri}"
    _, store, _ = _contexts(http)
    try:
        deleted = store.delete(uri)
    except ValueError as err:
        raise _bad_uri(err) from None
    if deleted:
        return {"deleted": uri}
    raise HTTPException(status_code=404, detail=f"Context not found: {uri}")


# --- Multi-Agent Coordinator (Phase 7C) Endpoints ---


class CoordinateRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000, description="Natural language goal")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Optional structured parameters"
    )


def _get_coordinator():
    """Get or create the shared AgentCoordinator instance."""
    from geospark.agents import AgentCoordinator

    if not hasattr(_get_coordinator, "_instance"):
        _get_coordinator._instance = AgentCoordinator()
    return _get_coordinator._instance


@app.post("/api/v1/agent/coordinate", dependencies=[Depends(verify_api_key), Depends(llm_slot)])
def agent_coordinate(request: CoordinateRequest):
    """Route a goal through the multi-agent coordinator.

    The coordinator classifies the goal and dispatches to the right
    specialist agent (GeoAgent, SiteSelector, or SpatialReport).
    """
    coord = _get_coordinator()
    result = coord.run(request.goal, parameters=request.parameters)
    return result.model_dump(mode="json")


@app.get("/api/v1/agent/list")
async def agent_list_registered():
    """List registered specialist agents."""
    coord = _get_coordinator()
    return {
        "agents": [card.model_dump(mode="json") for card in coord.list_agents()],
    }


@app.post("/api/v1/agent/classify", dependencies=[Depends(verify_api_key)])
def agent_classify(request: CoordinateRequest):
    """Classify a goal without actually running it (for debugging routing)."""
    from geospark.agents import classify_intent

    coord = _get_coordinator()
    classification = classify_intent(request.goal, coord.registry)
    return classification.model_dump(mode="json")


# --- Admin Endpoints (Phase 8A) ---


def _check_audit_date(date: str | None) -> None:
    if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


@app.get("/api/v1/admin/audit", dependencies=[Depends(verify_admin)])
async def admin_audit(date: str | None = None, limit: int = Query(50, ge=1, le=1000)):
    """Query audit log entries for a specific date (or today)."""
    _check_audit_date(date)
    from geospark.middleware.audit_log import get_audit_store

    store = get_audit_store()
    entries = store.read_date(date, limit=limit) if date else store.read_today(limit=limit)
    return {"entries": entries, "count": len(entries)}


@app.get("/api/v1/admin/audit/stats", dependencies=[Depends(verify_admin)])
async def admin_audit_stats(date: str | None = None):
    """Summary statistics from the audit log."""
    _check_audit_date(date)
    from geospark.middleware.audit_log import get_audit_store

    store = get_audit_store()
    return store.stats(date=date)


@app.get("/api/v1/admin/audit/dates", dependencies=[Depends(verify_admin)])
async def admin_audit_dates():
    """List all dates that have audit log files."""
    from geospark.middleware.audit_log import get_audit_store

    store = get_audit_store()
    return {"dates": store.list_dates()}


@app.get("/api/v1/admin/usage", dependencies=[Depends(verify_admin)])
async def admin_usage():
    """Aggregated API usage statistics."""
    from geospark.middleware.usage_tracker import get_usage_tracker

    tracker = get_usage_tracker()
    return tracker.summary()


@app.get("/api/v1/admin/usage/keys", dependencies=[Depends(verify_admin)])
async def admin_usage_keys():
    """Usage breakdown per API key."""
    from geospark.middleware.usage_tracker import get_usage_tracker

    tracker = get_usage_tracker()
    return {"keys": tracker.all_keys()}
