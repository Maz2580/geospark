"""Structured audit logging middleware for FastAPI.

Logs every API request as a JSON Lines entry. One file per day under
~/.geospark/audit/YYYY-MM-DD.jsonl. Designed for compliance, debugging,
and usage analysis.

Logged fields (per request):
    timestamp, method, path, query, status_code, duration_ms,
    client_ip, api_key_hash (first 8 chars), user_agent, response_size

NOT logged (privacy/security):
    Request body, full API key, response body

Configuration:
    GEOSPARK_AUDIT_ENABLED = "true" (default "true")
    GEOSPARK_AUDIT_DIR = path to audit log directory (default ~/.geospark/audit)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Paths to skip in audit log (static assets, noisy health checks)
_SKIP_PREFIXES = (
    "/assets/",
    "/favicon.ico",
)


def _should_log(path: str) -> bool:
    """Determine if a request should be audit-logged."""
    return not any(path.startswith(p) for p in _SKIP_PREFIXES)


def _hash_key(api_key: str) -> str:
    """Hash an API key for the audit log (first 8 chars of SHA-256)."""
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode()).hexdigest()[:8]


def _extract_api_key(request: Request) -> str:
    """Extract the Bearer token from the Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 10:
        return auth[7:]
    return ""


class AuditEntry:
    """A single audit log entry."""

    __slots__ = (
        "api_key_hash",
        "client_ip",
        "duration_ms",
        "method",
        "path",
        "query",
        "response_size",
        "status_code",
        "timestamp",
        "user_agent",
    )

    def __init__(
        self,
        method: str,
        path: str,
        query: str,
        status_code: int,
        duration_ms: float,
        client_ip: str,
        api_key_hash: str,
        user_agent: str,
        response_size: int,
    ) -> None:
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.method = method
        self.path = path
        self.query = query
        self.status_code = status_code
        self.duration_ms = round(duration_ms, 1)
        self.client_ip = client_ip
        self.api_key_hash = api_key_hash
        self.user_agent = user_agent
        self.response_size = response_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "method": self.method,
            "path": self.path,
            "query": self.query,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "client_ip": self.client_ip,
            "api_key_hash": self.api_key_hash,
            "user_agent": self.user_agent,
            "response_size": self.response_size,
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


class AuditStore:
    """File-backed audit log store with daily rotation.

    Appends JSON Lines to ~/.geospark/audit/YYYY-MM-DD.jsonl.
    Thread-safe for asyncio (single-threaded event loop).
    """

    def __init__(self, audit_dir: str | Path | None = None) -> None:
        if audit_dir is None:
            audit_dir = os.getenv(
                "GEOSPARK_AUDIT_DIR",
                str(Path.home() / ".geospark" / "audit"),
            )
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str = ""
        self._file = None

    def _get_file(self):  # type: ignore[no-untyped-def]
        """Get the file handle for today's log, rotating if date changed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._file is not None:
                self._file.close()
            path = self._dir / f"{today}.jsonl"
            self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
            self._current_date = today
        return self._file

    def append(self, entry: AuditEntry) -> None:
        """Append an audit entry to today's log file."""
        f = self._get_file()
        f.write(entry.to_json_line() + "\n")
        f.flush()

    def read_today(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent entries from today's log."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.read_date(today, limit=limit)

    def read_date(self, date: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read entries from a specific date's log file.

        Args:
            date: Date string in YYYY-MM-DD format.
            limit: Maximum entries to return (from the end of the file).
        """
        path = self._dir / f"{date}.jsonl"
        if not path.exists():
            return []

        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]

    def list_dates(self) -> list[str]:
        """List all dates that have audit logs."""
        return sorted(
            p.stem for p in self._dir.glob("*.jsonl")
        )

    def stats(self, date: str | None = None) -> dict[str, Any]:
        """Summary stats for a day (or today if date is None)."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = self.read_date(date, limit=10000)
        if not entries:
            return {"date": date, "total_requests": 0}

        status_counts: dict[str, int] = {}
        path_counts: dict[str, int] = {}
        total_duration = 0.0

        for e in entries:
            sc = str(e.get("status_code", "?"))
            status_counts[sc] = status_counts.get(sc, 0) + 1
            path = e.get("path", "?")
            path_counts[path] = path_counts.get(path, 0) + 1
            total_duration += e.get("duration_ms", 0)

        top_paths = sorted(path_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "date": date,
            "total_requests": len(entries),
            "status_codes": status_counts,
            "avg_duration_ms": round(total_duration / len(entries), 1) if entries else 0,
            "top_paths": [{"path": p, "count": c} for p, c in top_paths],
            "unique_ips": len({e.get("client_ip") for e in entries}),
        }

    def close(self) -> None:
        """Close the current file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None
            self._current_date = ""


# Shared instance
_audit_store: AuditStore | None = None


def get_audit_store() -> AuditStore:
    """Get or create the shared AuditStore instance."""
    global _audit_store
    if _audit_store is None:
        _audit_store = AuditStore()
    return _audit_store


class AuditLogMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that logs every request as a structured audit entry.

    Captures timing, client identity, and response status without logging
    request/response bodies (for security).
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.enabled = os.getenv("GEOSPARK_AUDIT_ENABLED", "true").lower() == "true"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Log the request after it completes."""
        if not self.enabled or not _should_log(request.url.path):
            return await call_next(request)

        t0 = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - t0) * 1000

        # Extract client IP (prefer X-Forwarded-For for Cloudflare)
        forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else ""
        if not client_ip and request.client:
            client_ip = request.client.host

        api_key = _extract_api_key(request)

        # Content-Length is not always set — use 0 as default
        response_size = int(response.headers.get("content-length", "0"))

        entry = AuditEntry(
            method=request.method,
            path=request.url.path,
            query=str(request.url.query) if request.url.query else "",
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
            api_key_hash=_hash_key(api_key),
            user_agent=request.headers.get("user-agent", "")[:200],
            response_size=response_size,
        )
        get_audit_store().append(entry)

        return response
