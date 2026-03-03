"""
GeoSpark REST API.

FastAPI server exposing GeoSpark capabilities via HTTP.
Designed to run in Docker or standalone.

Usage:
    uvicorn geospark.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.protocol.schema import (
    Point,
    SpatialFeature,
    SpatialOperation,
    SpatialQuery,
    SpatialResult,
)

load_dotenv()

# Global engine instance
_engine: Engine | None = None


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
    version="0.1.0",
    lifespan=lifespan,
)


# --- Request/Response Models ---


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
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


@app.get("/api/v1/info")
async def info():
    """System information."""
    return {
        "name": "GeoSpark",
        "version": "0.1.0",
        "protocol": "GSP v0.1",
        "tools": get_engine().available_tools,
        "database": os.getenv("GEOSPARK_DB_BACKEND", "memory"),
    }


@app.post("/api/v1/geocode", response_model=SpatialResult)
async def geocode(request: GeocodeRequest):
    """Geocode an address or place name."""
    engine = get_engine()
    query = SpatialQuery(
        operation=SpatialOperation.GEOCODE,
        metadata={"query": request.query},
        limit=request.limit,
    )
    return engine.execute(query)


@app.post("/api/v1/query", response_model=SpatialResult)
async def spatial_query(request: SpatialQueryRequest):
    """Execute a spatial query."""
    engine = get_engine()

    geometry = None
    if request.latitude is not None and request.longitude is not None:
        geometry = Point.from_latlon(request.latitude, request.longitude)

    try:
        op = SpatialOperation(request.operation)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown operation: {request.operation}. "
            f"Available: {[o.value for o in SpatialOperation]}",
        )

    query = SpatialQuery(
        operation=op,
        geometry=geometry,
        radius_m=request.radius_m,
    )
    return engine.execute(query)


@app.post("/api/v1/check-relationship", response_model=RelationshipResponse)
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
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """
    Ask a natural language spatial question.

    Uses OpenRouter free models + GeoSpark tools for grounded answers.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY not configured. Set it in .env",
        )

    try:
        from geospark.integrations.openrouter import OpenRouterClient

        client = OpenRouterClient(model=request.model)
        answer = client.ask(request.question)
        client.close()

        return AskResponse(
            answer=answer.answer,
            model=answer.model,
            tools_used=[tc["tool"] for tc in answer.tool_calls],
            tokens_used=answer.tokens_used,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
