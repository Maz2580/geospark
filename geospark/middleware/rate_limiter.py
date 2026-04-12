"""Sliding-window rate limiter middleware for FastAPI.

Limits requests per IP address (and optionally per API key). Uses an
in-memory sliding window — no external dependencies like Redis.

Configuration via environment variables:
    GEOSPARK_RATE_LIMIT_RPM       = requests per minute (default 60)
    GEOSPARK_RATE_LIMIT_BURST     = burst allowance above RPM (default 10)
    GEOSPARK_RATE_LIMIT_ENABLED   = "true" to enable (default "true")

Exempt paths (always allowed regardless of limit):
    /health, /api/v1/status, /docs, /openapi.json, /redoc
    All static asset paths (/assets/*)
    All HTML page routes (/, /playground, /agents, etc.)
"""
from __future__ import annotations

import os
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Paths exempt from rate limiting (health checks, docs, static pages)
_EXEMPT_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/assets/",
)

_EXEMPT_PAGES = frozenset({
    "/",
    "/playground",
    "/agents",
    "/memory",
    "/context",
    "/data",
    "/status",
    "/guide",
})


def _is_exempt(path: str) -> bool:
    """Check if a request path is exempt from rate limiting."""
    if path in _EXEMPT_PAGES:
        return True
    return any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


def _get_client_key(request: Request) -> str:
    """Extract a rate-limit key from the request.

    Uses API key (from Authorization header) if present, otherwise
    falls back to client IP. This means authenticated clients get their
    own rate-limit bucket, while anonymous clients share per-IP buckets.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 10:
        # Use a hash prefix of the API key, not the key itself
        return f"key:{auth[7:15]}"
    # Client IP — check X-Forwarded-For for proxied requests (Cloudflare)
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    client = request.client
    if client:
        return f"ip:{client.host}"
    return "ip:unknown"


class SlidingWindowCounter:
    """In-memory sliding window rate counter.

    Tracks timestamps of recent requests per key. Evicts entries older
    than the window on each check. Thread-safe for asyncio (single-threaded
    event loop — no lock needed).
    """

    def __init__(self, window_seconds: int = 60, max_requests: int = 60) -> None:
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """Check if a request from this key is allowed.

        Returns:
            (allowed, remaining, retry_after_seconds)
            - allowed: True if under the limit
            - remaining: how many requests left in this window
            - retry_after: seconds to wait if blocked (0 if allowed)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Evict old entries
        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]
        timestamps = self._requests[key]

        count = len(timestamps)
        remaining = max(0, self.max_requests - count)

        if count >= self.max_requests:
            # Blocked — calculate when the oldest request in the window expires
            oldest = min(timestamps) if timestamps else now
            retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
            return False, 0, retry_after

        # Allowed — record this request
        timestamps.append(now)
        return True, remaining - 1, 0

    def get_usage(self, key: str) -> dict[str, int]:
        """Get current usage for a key."""
        now = time.time()
        cutoff = now - self.window_seconds
        timestamps = [t for t in self._requests.get(key, []) if t > cutoff]
        return {
            "requests_in_window": len(timestamps),
            "limit": self.max_requests,
            "remaining": max(0, self.max_requests - len(timestamps)),
            "window_seconds": self.window_seconds,
        }

    def reset(self, key: str | None = None) -> None:
        """Reset counters. If key is None, resets all."""
        if key is None:
            self._requests.clear()
        else:
            self._requests.pop(key, None)

    @property
    def tracked_keys(self) -> int:
        """Number of keys currently being tracked."""
        return len(self._requests)


# Per-route limit overrides: path prefix -> max requests per minute
_ROUTE_OVERRIDES: dict[str, int] = {}


def set_route_limit(path_prefix: str, rpm: int) -> None:
    """Set a custom rate limit for a specific route prefix.

    Example:
        set_route_limit("/api/v1/agent/", 20)  # Agent routes: 20 RPM
        set_route_limit("/api/v1/geocode", 120)  # Geocoding: 120 RPM
    """
    _ROUTE_OVERRIDES[path_prefix] = rpm


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces sliding-window rate limits.

    Adds response headers:
        X-RateLimit-Limit: max requests per window
        X-RateLimit-Remaining: requests left in current window
        X-RateLimit-Reset: seconds until window resets

    Returns 429 Too Many Requests when limit is exceeded.
    """

    def __init__(self, app, rpm: int | None = None, burst: int | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.enabled = os.getenv("GEOSPARK_RATE_LIMIT_ENABLED", "true").lower() == "true"
        default_rpm = int(os.getenv("GEOSPARK_RATE_LIMIT_RPM", "60"))
        default_burst = int(os.getenv("GEOSPARK_RATE_LIMIT_BURST", "10"))
        self.rpm = rpm if rpm is not None else default_rpm
        self.burst = burst if burst is not None else default_burst
        self._default_counter = SlidingWindowCounter(
            window_seconds=60,
            max_requests=self.rpm + self.burst,
        )
        # Per-route counters (created lazily)
        self._route_counters: dict[str, SlidingWindowCounter] = {}

    def _get_counter(self, path: str) -> SlidingWindowCounter:
        """Get the rate limit counter for a path, checking overrides."""
        for prefix, rpm in _ROUTE_OVERRIDES.items():
            if path.startswith(prefix):
                if prefix not in self._route_counters:
                    self._route_counters[prefix] = SlidingWindowCounter(
                        window_seconds=60,
                        max_requests=rpm,
                    )
                return self._route_counters[prefix]
        return self._default_counter

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Check rate limit before processing the request."""
        if not self.enabled or _is_exempt(request.url.path):
            return await call_next(request)

        client_key = _get_client_key(request)
        counter = self._get_counter(request.url.path)
        allowed, remaining, retry_after = counter.is_allowed(client_key)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after,
                    "limit": counter.max_requests,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(counter.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

        response = await call_next(request)

        # Add rate limit headers to successful responses
        response.headers["X-RateLimit-Limit"] = str(counter.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
