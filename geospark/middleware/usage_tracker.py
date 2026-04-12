"""Usage tracking middleware — per-endpoint and per-key counters.

Tracks API usage in-memory with periodic persistence to disk.
Provides aggregated stats for dashboards and quota enforcement.

Configuration:
    GEOSPARK_USAGE_ENABLED = "true" (default "true")
    GEOSPARK_USAGE_DIR = path to usage data (default ~/.geospark/usage)
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class UsageTracker:
    """In-memory usage counters with disk persistence.

    Tracks:
    - Total requests per endpoint
    - Total requests per API key (hashed)
    - Per-key per-endpoint breakdown
    - Last activity timestamp per key
    - Hourly snapshots persisted to disk
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = os.getenv(
                "GEOSPARK_USAGE_DIR",
                str(Path.home() / ".geospark" / "usage"),
            )
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

        # Counters
        self._endpoint_counts: dict[str, int] = defaultdict(int)
        self._key_counts: dict[str, int] = defaultdict(int)
        self._key_endpoint_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._key_last_active: dict[str, str] = {}
        self._status_counts: dict[int, int] = defaultdict(int)
        self._total_requests: int = 0
        self._started_at: str = datetime.now(timezone.utc).isoformat()
        self._last_persist: float = time.time()

        # Load existing data if present
        self._load()

    def record(
        self,
        path: str,
        api_key_hash: str,
        status_code: int,
    ) -> None:
        """Record a single API request."""
        self._total_requests += 1
        self._endpoint_counts[path] += 1
        self._status_counts[status_code] += 1

        if api_key_hash:
            self._key_counts[api_key_hash] += 1
            self._key_endpoint_counts[api_key_hash][path] += 1
            self._key_last_active[api_key_hash] = datetime.now(timezone.utc).isoformat()

        # Auto-persist every 5 minutes
        if time.time() - self._last_persist > 300:
            self.persist()

    def summary(self) -> dict[str, Any]:
        """Return aggregated usage summary."""
        top_endpoints = sorted(
            self._endpoint_counts.items(), key=lambda x: x[1], reverse=True
        )[:15]

        return {
            "total_requests": self._total_requests,
            "tracking_since": self._started_at,
            "unique_keys": len(self._key_counts),
            "unique_endpoints": len(self._endpoint_counts),
            "status_codes": dict(self._status_counts),
            "top_endpoints": [
                {"path": p, "count": c} for p, c in top_endpoints
            ],
        }

    def key_usage(self, api_key_hash: str) -> dict[str, Any]:
        """Return usage breakdown for a specific API key."""
        if api_key_hash not in self._key_counts:
            return {"key": api_key_hash, "total_requests": 0, "endpoints": {}}

        endpoints = dict(self._key_endpoint_counts.get(api_key_hash, {}))
        return {
            "key": api_key_hash,
            "total_requests": self._key_counts[api_key_hash],
            "last_active": self._key_last_active.get(api_key_hash, ""),
            "endpoints": endpoints,
        }

    def all_keys(self) -> list[dict[str, Any]]:
        """Return usage summary for all tracked API keys."""
        return [
            {
                "key": k,
                "total_requests": self._key_counts[k],
                "last_active": self._key_last_active.get(k, ""),
            }
            for k in sorted(self._key_counts, key=lambda k: self._key_counts[k], reverse=True)
        ]

    def persist(self) -> Path:
        """Write current counters to disk."""
        data = {
            "total_requests": self._total_requests,
            "started_at": self._started_at,
            "persisted_at": datetime.now(timezone.utc).isoformat(),
            "endpoint_counts": dict(self._endpoint_counts),
            "key_counts": dict(self._key_counts),
            "key_endpoint_counts": {
                k: dict(v) for k, v in self._key_endpoint_counts.items()
            },
            "key_last_active": dict(self._key_last_active),
            "status_counts": {str(k): v for k, v in self._status_counts.items()},
        }
        path = self._dir / "usage.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._last_persist = time.time()
        return path

    def _load(self) -> None:
        """Load persisted counters from disk."""
        path = self._dir / "usage.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._total_requests = data.get("total_requests", 0)
            self._started_at = data.get("started_at", self._started_at)
            for k, v in data.get("endpoint_counts", {}).items():
                self._endpoint_counts[k] = v
            for k, v in data.get("key_counts", {}).items():
                self._key_counts[k] = v
            for k, eps in data.get("key_endpoint_counts", {}).items():
                for ep, c in eps.items():
                    self._key_endpoint_counts[k][ep] = c
            self._key_last_active = data.get("key_last_active", {})
            for k, v in data.get("status_counts", {}).items():
                self._status_counts[int(k)] = v
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    def reset(self) -> None:
        """Reset all counters."""
        self._endpoint_counts.clear()
        self._key_counts.clear()
        self._key_endpoint_counts.clear()
        self._key_last_active.clear()
        self._status_counts.clear()
        self._total_requests = 0
        self._started_at = datetime.now(timezone.utc).isoformat()


# Shared instance
_usage_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    """Get or create the shared UsageTracker instance."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker


# Paths to skip (same as audit log — static assets)
_SKIP_PREFIXES = (
    "/assets/",
    "/favicon.ico",
)


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that counts requests per endpoint and per API key."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.enabled = os.getenv("GEOSPARK_USAGE_ENABLED", "true").lower() == "true"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Record the request in usage counters after it completes."""
        path = request.url.path
        if not self.enabled or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)

        # Extract API key hash
        auth = request.headers.get("authorization", "")
        api_key_hash = ""
        if auth.startswith("Bearer ") and len(auth) > 10:
            import hashlib

            api_key_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:8]

        get_usage_tracker().record(
            path=path,
            api_key_hash=api_key_hash,
            status_code=response.status_code,
        )

        return response
