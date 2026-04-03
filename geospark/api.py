"""
GeoSpark REST API.

FastAPI server exposing GeoSpark capabilities via HTTP.
Designed to run in Docker or standalone.

Usage:
    uvicorn geospark.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from geospark import __version__
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import (
    Point,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)

load_dotenv()

# Global engine instance
_engine: Engine | None = None
_start_time: float = time.time()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(tools=["geocoder", "terrain"])
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize engine on startup."""
    get_engine()
    yield


app = FastAPI(
    title="GeoSpark API",
    description="The Open-Source Geospatial Intelligence Engine. Give any AI model a spatial mind.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

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
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Request/Response Models ---


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    tools: list[str] = []


class GeocodeRequest(BaseModel):
    query: str = Field(..., description="Address or place name to geocode")
    limit: int = Field(5, description="Max results")


class SpatialQueryRequest(BaseModel):
    operation: str = Field(..., description="Spatial operation to perform")
    latitude: float | None = Field(None, description="Latitude")
    longitude: float | None = Field(None, description="Longitude")
    radius_m: float | None = Field(None, description="Radius in meters")
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


class DistanceRequest(BaseModel):
    lat_a: float = Field(..., description="Latitude of point A")
    lon_a: float = Field(..., description="Longitude of point A")
    lat_b: float = Field(..., description="Latitude of point B")
    lon_b: float = Field(..., description="Longitude of point B")


class DistanceResponse(BaseModel):
    distance_m: float
    distance_km: float
    note: str = "Geodesic distance on WGS84 ellipsoid"


class ElevationRequest(BaseModel):
    latitude: float = Field(..., description="Latitude")
    longitude: float = Field(..., description="Longitude")


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural language spatial question")
    model: str | None = Field(None, description="Override LLM model")


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


@app.post("/api/v1/geocode", response_model=SpatialResult, dependencies=[Depends(verify_api_key)])
async def geocode(request: GeocodeRequest):
    """Geocode an address or place name."""
    engine = get_engine()
    query = SpatialQuery(
        operation=SpatialOperation.GEOCODE,
        metadata={"query": request.query},
        limit=request.limit,
    )
    return engine.execute(query)


@app.post("/api/v1/query", response_model=SpatialResult, dependencies=[Depends(verify_api_key)])
async def spatial_query(request: SpatialQueryRequest):
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
    )
    return engine.execute(query)


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
        return RelationshipResponse(
            relationship=request.relationship,
            result=result,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/v1/ask", response_model=AskResponse, dependencies=[Depends(verify_api_key)])
async def ask(request: AskRequest):
    """
    Ask a natural language spatial question.

    Tries local Ollama (Qwen 2.5 7B) first, falls back to OpenRouter.
    """
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
    return DistanceResponse(distance_m=round(d, 2), distance_km=round(d / 1000, 3))


@app.post("/api/v1/elevation", dependencies=[Depends(verify_api_key)])
async def elevation(request: ElevationRequest):
    """Get elevation at a point (meters above sea level)."""
    engine = get_engine()
    query = SpatialQuery(
        operation=SpatialOperation.ELEVATION,
        geometry=Point.from_latlon(request.latitude, request.longitude),
    )
    result = engine.execute(query)
    if result.errors:
        raise HTTPException(status_code=502, detail=result.errors[0])
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "elevation_m": result.features[0].properties.get("elevation_m") if result.features else None,
        "source": "Open Elevation API",
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


@app.post("/api/v1/flows/templates/{template_name}/run", dependencies=[Depends(verify_api_key)])
async def flow_run_template(template_name: str, request: TemplateRunRequest):
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


@app.post("/api/v1/flows", dependencies=[Depends(verify_api_key)])
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


@app.delete("/api/v1/flows/{flow_id}", dependencies=[Depends(verify_api_key)])
async def flow_delete(flow_id: str):
    """Delete a saved flow and its runs."""
    store = _get_store()
    deleted = store.delete_flow(flow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"deleted": flow_id}


@app.post("/api/v1/flows/{flow_id}/run", dependencies=[Depends(verify_api_key)])
async def flow_run_saved(flow_id: str):
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


# --- Agent Endpoints ---


class AgentRunRequest(BaseModel):
    goal: str = Field(..., description="Natural language spatial goal")


class ReportRequest(BaseModel):
    location: str = Field(..., description="Location to analyze")
    radius_m: float = Field(2000, description="Search radius in meters")


class SiteSelectRequest(BaseModel):
    within: str = Field(..., description="Search area (city/neighborhood)")
    near: list[str] = Field(default_factory=list, description="Amenity types to be near")
    avoid: list[str] = Field(default_factory=list, description="Amenity types to avoid")
    facility_type: str = Field("restaurant", description="Facility type to place")
    radius_m: float = Field(5000, description="Search radius in meters")


@app.post("/api/v1/agent/run", dependencies=[Depends(verify_api_key)])
async def agent_run(request: AgentRunRequest):
    """Run the autonomous spatial agent with a goal."""
    from geospark.agents import GeoAgent

    ag = GeoAgent(engine=get_engine())
    result = ag.run(request.goal)
    return result.model_dump()


@app.post("/api/v1/agent/report", dependencies=[Depends(verify_api_key)])
async def agent_report(request: ReportRequest):
    """Generate a spatial intelligence report for a location."""
    from geospark.agents import SpatialReport

    reporter = SpatialReport(engine=get_engine())
    report = reporter.analyze(request.location, radius_m=request.radius_m)
    return report.model_dump()


@app.post("/api/v1/agent/site-select", dependencies=[Depends(verify_api_key)])
async def agent_site_select(request: SiteSelectRequest):
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
