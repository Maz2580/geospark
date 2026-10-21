"""Per-visitor sandboxes for the memory and context demos on the public API.

Every visitor gets an isolated, size-capped, auto-expiring memory and context space, so
the demo pages stay interactive without anyone being able to read, poison or wipe
another visitor's data. The operator (admin token) works on the shared global space.

A visitor is identified by the ``X-GeoSpark-Session`` header (a random id the web UI keeps
in localStorage), or by their hashed IP for API clients that don't send one.

Configuration (environment variables):
    GEOSPARK_DATA_DIR               root for persistent state (default ~/.geospark)
    GEOSPARK_SANDBOX_TTL_DAYS       delete sandboxes idle this long (default 7)
    GEOSPARK_SANDBOX_MAX_MEMORIES   facts + episodes per sandbox (default 200)
    GEOSPARK_SANDBOX_MAX_CONTEXTS   contexts per sandbox (default 100)
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from geospark.security import SESSION_HEADER, client_ip, hash_ip, is_admin

GLOBAL_NAMESPACE = "global"
_SESSION_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")
_MAX_CACHED = 128
_SWEEP_INTERVAL_S = 3600


def data_dir() -> Path:
    return Path(os.getenv("GEOSPARK_DATA_DIR") or Path.home() / ".geospark")


def sandbox_root() -> Path:
    return data_dir() / "sandboxes"


def max_memories() -> int:
    return int(os.getenv("GEOSPARK_SANDBOX_MAX_MEMORIES", "200"))


def max_contexts() -> int:
    return int(os.getenv("GEOSPARK_SANDBOX_MAX_CONTEXTS", "100"))


def namespace_for(request: Request) -> str:
    """The storage namespace this request reads and writes."""
    if is_admin(request):
        return GLOBAL_NAMESPACE
    session = request.headers.get(SESSION_HEADER, "")
    if _SESSION_RE.match(session):
        return "s-" + hashlib.sha256(session.encode()).hexdigest()[:24]
    return "ip-" + hash_ip(client_ip(request))


class _Sandboxes:
    """LRU cache of per-namespace stores plus idle-sandbox expiry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory: OrderedDict[str, Any] = OrderedDict()
        self._contexts: OrderedDict[str, tuple[Any, Any]] = OrderedDict()
        self._last_sweep = 0.0

    def _dir(self, namespace: str) -> Path:
        if namespace == GLOBAL_NAMESPACE:
            return data_dir()
        path = sandbox_root() / namespace
        path.mkdir(parents=True, exist_ok=True)
        os.utime(path)  # mark as recently used, for expiry
        return path

    def _remember(self, cache: OrderedDict, namespace: str, value: Any) -> Any:
        cache[namespace] = value
        cache.move_to_end(namespace)
        while len(cache) > _MAX_CACHED:
            cache.popitem(last=False)
        return value

    def memory(self, namespace: str) -> Any:
        from geospark.memory.intelligence import SpatialIntelligence

        with self._lock:
            self._maybe_sweep()
            base = self._dir(namespace)
            if namespace in self._memory:
                self._memory.move_to_end(namespace)
                return self._memory[namespace]
            intel = SpatialIntelligence(
                storage_dir=base / "intelligence",
                ollama_url=os.getenv("OLLAMA_BASE_URL"),
            )
            return self._remember(self._memory, namespace, intel)

    def contexts(self, namespace: str) -> tuple[Any, Any]:
        """(ContextStore, ContextRetriever) for a namespace."""
        from geospark.context import ContextRetriever, ContextStore

        with self._lock:
            self._maybe_sweep()
            base = self._dir(namespace)
            if namespace in self._contexts:
                self._contexts.move_to_end(namespace)
                return self._contexts[namespace]
            store = ContextStore(storage_dir=base / "contexts")
            pair = (store, ContextRetriever(store))
            return self._remember(self._contexts, namespace, pair)

    def _maybe_sweep(self) -> None:
        now = time.time()
        if now - self._last_sweep < _SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        root = sandbox_root()
        if not root.is_dir():
            return
        ttl_s = float(os.getenv("GEOSPARK_SANDBOX_TTL_DAYS", "7")) * 86400
        for path in root.iterdir():
            try:
                if path.is_dir() and now - path.stat().st_mtime > ttl_s:
                    self._memory.pop(path.name, None)
                    self._contexts.pop(path.name, None)
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def reset(self) -> None:
        with self._lock:
            self._memory.clear()
            self._contexts.clear()
            self._last_sweep = 0.0


sandboxes = _Sandboxes()


def check_memory_quota(namespace: str, intel: Any) -> None:
    if namespace == GLOBAL_NAMESPACE:
        return
    stats = intel.stats()
    if stats.total_facts + stats.total_episodes >= max_memories():
        raise HTTPException(
            status_code=409,
            detail=f"This demo sandbox holds at most {max_memories()} memories. "
            "Compact or start a new session to continue.",
        )


def check_context_quota(namespace: str, store: Any) -> None:
    if namespace == GLOBAL_NAMESPACE:
        return
    if store.count(include_archived=True) >= max_contexts():
        raise HTTPException(
            status_code=409,
            detail=f"This demo sandbox holds at most {max_contexts()} contexts.",
        )
