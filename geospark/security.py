"""Access control for the public GeoSpark API.

The hosted API is deliberately open: anyone can geocode, measure, query and run agents
without a key. This module keeps that openness from becoming a liability:

- **Operator routes** (admin stats, the LLM gateway, shared-memory writes) need
  ``GEOSPARK_ADMIN_TOKEN``, sent as ``X-Admin-Token`` or ``Authorization: Bearer``.
- **Model allowlist**: public callers may only pick the local Ollama model or free
  OpenRouter models, so nobody can spend the operator's paid API credit.
- **LLM concurrency cap**: a handful of slow LLM/agent calls can't monopolise the CPU
  that the server shares with other apps.
- **Client identity**: the real client IP behind the Cloudflare tunnel, trusted only when
  the request reaches us from a local proxy, and hashed before it is logged.

Configuration (environment variables):
    GEOSPARK_ADMIN_TOKEN         operator token; required when GEOSPARK_ENV=production
    GEOSPARK_GATEWAY_KEYS        comma-separated partner keys for the LLM gateway only
    GEOSPARK_ALLOWED_MODELS      extra comma-separated models public callers may use
    GEOSPARK_MAX_LLM_CONCURRENCY concurrent LLM/agent calls (default 2)
    GEOSPARK_IP_SALT             salt for hashed IPs (default: derived from the admin token)
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from collections.abc import Iterator

from fastapi import HTTPException, Request

ADMIN_HEADER = "x-admin-token"
SESSION_HEADER = "x-geospark-session"


def is_production() -> bool:
    return os.getenv("GEOSPARK_ENV", "").lower() == "production"


def _admin_token() -> str:
    return os.getenv("GEOSPARK_ADMIN_TOKEN", "")


def check_startup_config() -> None:
    """Refuse to serve in production without an admin token.

    Without one, operator routes would either be open to everyone or unusable.
    """
    if is_production() and not _admin_token():
        raise RuntimeError(
            "GEOSPARK_ADMIN_TOKEN must be set when GEOSPARK_ENV=production. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )


def _presented_token(request: Request) -> str:
    token = request.headers.get(ADMIN_HEADER, "")
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def is_admin(request: Request) -> bool:
    """True if the request carries the operator token.

    With no token configured outside production (local development), every caller is
    treated as the operator, matching the API's historical open behaviour.
    """
    expected = _admin_token()
    if not expected:
        return not is_production()
    presented = _presented_token(request)
    return bool(presented) and hmac.compare_digest(presented.encode(), expected.encode())


async def verify_admin(request: Request) -> None:
    """FastAPI dependency for operator-only routes."""
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin token required")


def _gateway_keys() -> list[str]:
    return [k.strip() for k in os.getenv("GEOSPARK_GATEWAY_KEYS", "").split(",") if k.strip()]


def has_gateway_access(request: Request) -> bool:
    """The operator, or a partner holding one of ``GEOSPARK_GATEWAY_KEYS``.

    Partner keys open only the LLM gateway, and each can be revoked on its own.
    """
    if is_admin(request):
        return True
    presented = _presented_token(request)
    if not presented:
        return False
    # Compare against every key, without stopping early, so timing reveals nothing.
    matched = False
    for key in _gateway_keys():
        matched |= hmac.compare_digest(presented.encode(), key.encode())
    return matched


async def verify_gateway(request: Request) -> None:
    """FastAPI dependency for the LLM gateway's chat/generate/embeddings routes."""
    if not has_gateway_access(request):
        raise HTTPException(status_code=401, detail="Gateway key or admin token required")


# --- Client identity ---------------------------------------------------------


def _is_local_peer(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host in ("localhost", "testclient")
    return addr.is_loopback or addr.is_private


def client_ip(request: Request) -> str:
    """The real client IP.

    Proxy headers are honoured only when the TCP peer is local (the Cloudflare tunnel or
    another reverse proxy on this host). A client connecting directly can't spoof them.
    """
    peer = request.client.host if request.client else ""
    if peer and _is_local_peer(peer):
        cf_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cf_ip:
            return cf_ip
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer or "unknown"


def _ip_salt() -> bytes:
    salt = os.getenv("GEOSPARK_IP_SALT") or _admin_token() or "geospark"
    return hashlib.sha256(("ip-salt:" + salt).encode()).digest()


def hash_ip(ip: str) -> str:
    """A stable, non-reversible identifier for an IP, safe to write to logs."""
    return hmac.new(_ip_salt(), ip.encode(), hashlib.sha256).hexdigest()[:16]


# --- Model allowlist ---------------------------------------------------------


def default_ollama_model() -> str:
    return os.getenv("GEOSPARK_OLLAMA_MODEL", "qwen2.5:7b")


def public_models() -> set[str]:
    """Models any caller may select explicitly."""
    from geospark.integrations.openrouter import FREE_MODELS

    allowed = {default_ollama_model(), *FREE_MODELS.keys(), *FREE_MODELS.values()}
    extra = os.getenv("GEOSPARK_ALLOWED_MODELS", "")
    allowed.update(m.strip() for m in extra.split(",") if m.strip())
    return allowed


def check_model(request: Request, model: str | None) -> None:
    """Reject a caller-chosen model that could cost money or load arbitrary weights.

    Free OpenRouter models (``:free`` suffix) are always allowed; the operator may use
    any model.
    """
    if model is None or is_admin(request):
        return
    if model in public_models() or model.endswith(":free"):
        return
    raise HTTPException(
        status_code=400,
        detail=f"Model '{model}' is not available on this server. "
        f"Allowed: {sorted(public_models())}",
    )


# --- LLM concurrency cap (shared with the MCP server; see geospark.utils.concurrency) ---

from geospark.utils.concurrency import (  # noqa: E402
    ServerBusyError,
    heavy_work_slot,
    reset_llm_slots,
)

__all__ = ["ServerBusyError", "heavy_work_slot", "reset_llm_slots"]


def llm_slot() -> Iterator[None]:
    """FastAPI dependency: hold one LLM slot for the request, or answer 503 at once."""
    try:
        with heavy_work_slot():
            yield
    except ServerBusyError:
        raise HTTPException(
            status_code=503,
            detail="The server is busy with other model requests. Please retry shortly.",
            headers={"Retry-After": "10"},
        ) from None
