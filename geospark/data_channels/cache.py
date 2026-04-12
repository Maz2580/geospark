"""LRU cache with TTL for data channel results.

Caches ChannelResult objects to avoid redundant external API calls
during agent runs (which often query the same location multiple times).

Configuration:
    GEOSPARK_CHANNEL_CACHE_ENABLED = "true" (default "true")
    GEOSPARK_CHANNEL_CACHE_TTL = seconds (default 300 = 5 min)
    GEOSPARK_CHANNEL_CACHE_MAX = max entries (default 100)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from typing import Any

from geospark.data_channels.base import ChannelResult


def _make_cache_key(channel_name: str, kwargs: dict[str, Any]) -> str:
    """Create a deterministic cache key from channel name + search params.

    Sorts kwargs keys for consistency, then hashes the combined string.
    """
    # Filter out None values and sort for determinism
    filtered = {k: v for k, v in sorted(kwargs.items()) if v is not None}
    raw = f"{channel_name}:{json.dumps(filtered, sort_keys=True, default=str)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ChannelCache:
    """LRU cache with per-entry TTL for channel results.

    Entries expire after `ttl_seconds` and are evicted LRU-first when
    the cache exceeds `max_entries`.
    """

    def __init__(
        self,
        ttl_seconds: int | None = None,
        max_entries: int | None = None,
    ) -> None:
        self.enabled = os.getenv("GEOSPARK_CHANNEL_CACHE_ENABLED", "true").lower() == "true"
        self.ttl = ttl_seconds or int(os.getenv("GEOSPARK_CHANNEL_CACHE_TTL", "300"))
        self.max_entries = max_entries or int(os.getenv("GEOSPARK_CHANNEL_CACHE_MAX", "100"))
        self._cache: OrderedDict[str, tuple[float, ChannelResult]] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0

    def get(self, channel_name: str, kwargs: dict[str, Any]) -> ChannelResult | None:
        """Look up a cached result. Returns None on miss or expiry."""
        if not self.enabled:
            self._misses += 1
            return None

        key = _make_cache_key(channel_name, kwargs)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        timestamp, result = entry
        if time.time() - timestamp > self.ttl:
            # Expired — evict
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        return result

    def put(self, channel_name: str, kwargs: dict[str, Any], result: ChannelResult) -> None:
        """Store a result in the cache."""
        if not self.enabled:
            return

        key = _make_cache_key(channel_name, kwargs)
        self._cache[key] = (time.time(), result)
        self._cache.move_to_end(key)

        # Evict oldest if over capacity
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)

    def invalidate(self, channel_name: str | None = None) -> int:
        """Clear cached entries. If channel_name given, only that channel's entries.

        Returns number of entries removed.
        """
        if channel_name is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        # We hash the full key so we can't filter by channel name alone.
        # Clear all entries — conservative but correct. Channel-specific
        # invalidation would require storing channel alongside each entry.
        count = len(self._cache)
        self._cache.clear()
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        now = time.time()
        active = sum(1 for ts, _ in self._cache.values() if now - ts <= self.ttl)
        return {
            "enabled": self.enabled,
            "entries": len(self._cache),
            "active": active,
            "expired": len(self._cache) - active,
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(self._hits + self._misses, 1), 3),
        }

    @property
    def size(self) -> int:
        return len(self._cache)
