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

import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/llm", include_in_schema=False)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


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


@router.get("/health")
async def llm_health():
    """Check Ollama connectivity and list loaded models."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        model_names = [m["name"] for m in data.get("models", [])]
        return {
            "status": "ok",
            "ollama_url": OLLAMA_URL,
            "models_available": len(model_names),
            "models": model_names,
        }
    except Exception as e:
        return {
            "status": "error",
            "ollama_url": OLLAMA_URL,
            "error": str(e),
        }
