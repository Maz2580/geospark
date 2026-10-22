"""Shared, policy-compliant access to Nominatim.

The public server (nominatim.openstreetmap.org) allows **at most 1 request per second**, needs an
identifying User-Agent, and expects clients to cache results
(https://operations.osmfoundation.org/policies/nominatim/). Every GeoSpark geocoding call goes
through here, so the whole process respects that, however many threads or agents are running.

Configuration (environment variables):
    GEOSPARK_NOMINATIM_URL           base URL (default the public server); point it at your own
                                     Nominatim to lift the limits
    GEOSPARK_NOMINATIM_MIN_INTERVAL  seconds between requests (default 1.0; 0 for a self-hosted server)
    GEOSPARK_NOMINATIM_CACHE_TTL     seconds to keep answers (default 86400)
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx

from geospark.utils import USER_AGENT

PUBLIC_URL = "https://nominatim.openstreetmap.org"
_CACHE_MAX = 2000

_lock = threading.Lock()
_last_request = 0.0
_cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()


def base_url() -> str:
    return os.getenv("GEOSPARK_NOMINATIM_URL", PUBLIC_URL).rstrip("/")


def _min_interval() -> float:
    return float(os.getenv("GEOSPARK_NOMINATIM_MIN_INTERVAL", "1.0"))


def _ttl() -> float:
    return float(os.getenv("GEOSPARK_NOMINATIM_CACHE_TTL", "86400"))


def get_json(path: str, params: dict[str, Any], timeout: float = 10) -> Any:
    """GET ``{base}/{path}`` with caching and the shared rate limit.

    Raises ``httpx.HTTPError`` (or ``ValueError`` for a non-JSON body) like a plain request,
    so callers keep their own error handling. Failures are never cached.
    """
    global _last_request
    url = f"{base_url()}/{path.lstrip('/')}"
    key = (url, tuple(sorted((k, str(v)) for k, v in params.items())))
    now = time.monotonic()

    from geospark.runs import record

    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < _ttl():
            _cache.move_to_end(key)
            record("data", f"nominatim/{path}", {"url": url, "params": params}, hit[1], "openstreetmap-nominatim")
            return hit[1]

        # Hold the lock while waiting, so concurrent callers queue up one second apart
        wait = _last_request + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                data = response.json()
        finally:
            _last_request = time.monotonic()

        _cache[key] = (time.monotonic(), data)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    record("data", f"nominatim/{path}", {"url": url, "params": params}, data, "openstreetmap-nominatim")
    return data


def reset() -> None:
    """Clear the cache and the rate-limit clock (for tests)."""
    global _last_request
    with _lock:
        _cache.clear()
        _last_request = 0.0
