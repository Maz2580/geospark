"""
LLM Gateway — Proxy local Ollama models as a standard API.

Provides OpenAI-compatible endpoints over local Ollama models,
enabling any app to use free local inference by changing one URL.

Usage:
    # Instead of: client = OpenAI(api_key="sk-...")
    client = OpenAI(base_url="https://geospark.terrascout.app/api/v1/llm", api_key="any")
    response = client.chat.completions.create(model="qwen2.5:7b", messages=[...])
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/llm", include_in_schema=False)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# In-flight request counter — tracks concurrent requests through this gateway.
# Used by /health to surface queue_depth to pre-flight checks.
# asyncio is single-threaded so simple int increments are safe.
_in_flight_requests: int = 0


@contextlib.contextmanager
def _track_inflight():
    """Increment in-flight counter for the duration of a request."""
    global _in_flight_requests
    _in_flight_requests += 1
    try:
        yield
    finally:
        _in_flight_requests -= 1


# --- Request/Response Models ---


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = Field("qwen2.5:7b", description="Ollama model name")
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


class GenerateRequest(BaseModel):
    model: str = Field("qwen2.5:7b", description="Ollama model name")
    prompt: str
    temperature: float = 0.7
    max_tokens: int | None = None


class EmbeddingRequest(BaseModel):
    model: str = Field("qwen2.5:7b", description="Ollama model name")
    input: str | list[str]


# --- Endpoints ---


@router.get("/models")
async def list_models():
    """List available local Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append({
                "id": m["name"],
                "object": "model",
                "owned_by": "local-ollama",
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "parameter_size": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", ""),
                "family": details.get("family", ""),
            })

        return {"object": "list", "data": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}") from e


@router.post("/chat")
async def chat_completion(request: ChatRequest):
    """OpenAI-compatible chat completion via local Ollama.

    Drop-in replacement: change base_url to geospark.terrascout.app/api/v1/llm
    """
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "stream": False,
        "options": {"temperature": request.temperature},
    }
    if request.max_tokens:
        payload["options"]["num_predict"] = request.max_tokens

    t0 = time.time()
    with _track_inflight():
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Model inference timed out") from None
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e}") from e

    message = data.get("message", {})
    duration = time.time() - t0

    # Return OpenAI-compatible format
    return {
        "id": f"chatcmpl-{int(t0)}",
        "object": "chat.completion",
        "created": int(t0),
        "model": request.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        },
        "duration_s": round(duration, 1),
    }


@router.post("/generate")
async def generate(request: GenerateRequest):
    """Simple text generation."""
    payload: dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": False,
        "options": {"temperature": request.temperature},
    }
    if request.max_tokens:
        payload["options"]["num_predict"] = request.max_tokens

    with _track_inflight():
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e}") from e

    return {
        "model": request.model,
        "response": data.get("response", ""),
        "done": data.get("done", True),
        "total_duration_ms": round(data.get("total_duration", 0) / 1e6),
    }


@router.post("/embeddings")
async def embeddings(request: EmbeddingRequest):
    """Generate text embeddings via Ollama.

    Returns embeddings compatible with OpenAI's embedding format.
    """
    inputs = request.input if isinstance(request.input, list) else [request.input]

    with _track_inflight():
        try:
            all_embeddings = []
            async with httpx.AsyncClient(timeout=60) as client:
                for i, text in enumerate(inputs):
                    resp = await client.post(
                        f"{OLLAMA_URL}/api/embed",
                        json={"model": request.model, "input": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    embs = data.get("embeddings", [[]])
                    all_embeddings.append({
                        "object": "embedding",
                        "index": i,
                        "embedding": embs[0] if embs else [],
                    })
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama embedding error: {e}") from e

    return {
        "object": "list",
        "data": all_embeddings,
        "model": request.model,
        "usage": {"prompt_tokens": sum(len(t.split()) for t in inputs), "total_tokens": 0},
    }


def _get_load_average() -> tuple[float, float, float]:
    """Return (1m, 5m, 15m) system load averages.

    Works on Linux (via /proc/loadavg, exposed by os.getloadavg).
    Returns (0.0, 0.0, 0.0) on platforms without load average support.
    """
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return (0.0, 0.0, 0.0)


def _estimate_cold_load_s(load_1m: float) -> int:
    """Estimate a typical cold-load cost in seconds based on CPU load.

    Empirical baseline: qwen2.5:7b cold-loads in ~8s on an idle CPU. Load
    scales roughly linearly with CPU contention because the model file
    has to be mmapped and the first forward pass warmed up.
    """
    return max(8, int(load_1m * 2))


def _compute_status(
    load_1m: float,
    queue_depth: int,
    ollama_reachable: bool,
) -> tuple[str, str]:
    """Return (status, reason) based on load + queue + reachability.

    Status values:
    - "ok"       = healthy, send requests freely
    - "degraded" = under load, requests may be slower than usual
    - "busy"     = saturated, prefer to back off and retry later

    Thresholds align with the UMAMI benchmark's abort signal at load_1m > 20.
    """
    if not ollama_reachable:
        return "busy", "Ollama unreachable"
    if load_1m > 20 or queue_depth > 10:
        return "busy", f"load_1m={load_1m:.1f}, queue={queue_depth}"
    if load_1m > 10 or queue_depth > 5:
        return "degraded", f"load_1m={load_1m:.1f}, queue={queue_depth}"
    return "ok", "healthy"


@router.get("/health")
async def llm_health():
    """Pre-flight health check for the LLM gateway and upstream Ollama.

    Returns a structured snapshot that clients can use to decide whether
    to send requests immediately, back off, or abort a benchmark early.

    Response schema:
    - status: "ok" | "degraded" | "busy"
    - loaded_models: currently loaded models in Ollama (from /api/ps)
    - load_average_1m, 5m, 15m: system load averages
    - estimated_cold_load_s: typical cold-load cost for a new model
    - queue_depth: in-flight requests through this gateway
    - ollama_reachable: whether Ollama answered the ping
    - reason: human-readable explanation of the status
    """
    load_1m, load_5m, load_15m = _get_load_average()
    queue_depth = _in_flight_requests

    loaded_models: list[dict[str, Any]] = []
    ollama_reachable = False
    error: str | None = None

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/ps")
            resp.raise_for_status()
            ps_data = resp.json()
            ollama_reachable = True

            for m in ps_data.get("models", []):
                loaded_models.append({
                    "name": m.get("name", ""),
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "expires_at": m.get("expires_at", ""),
                })
    except Exception as e:
        error = str(e)

    status, reason = _compute_status(load_1m, queue_depth, ollama_reachable)

    response: dict[str, Any] = {
        "status": status,
        "loaded_models": [m["name"] for m in loaded_models],
        "load_average_1m": round(load_1m, 2),
        "load_average_5m": round(load_5m, 2),
        "load_average_15m": round(load_15m, 2),
        "estimated_cold_load_s": _estimate_cold_load_s(load_1m),
        "queue_depth": queue_depth,
        "ollama_reachable": ollama_reachable,
        "reason": reason,
        "ollama_url": OLLAMA_URL,
        "loaded_models_detail": loaded_models,
    }
    if error:
        response["error"] = error
    return response
