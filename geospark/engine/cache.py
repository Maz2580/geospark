"""
Spatial Cache.

In-memory LRU cache with TTL support and spatial-aware key generation.
Designed for caching SpatialQuery results to avoid redundant computation.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from typing import Any

from geospark.protocol.schema import SpatialQuery


class SpatialCache:
    """
    In-memory cache with TTL and LRU eviction.

    Features:
    - Deterministic key generation from SpatialQuery
    - Time-to-live (TTL) expiration
    - LRU eviction when max size is reached
    - Hit/miss statistics

    Usage:
        cache = SpatialCache(max_size=256)
        key = cache.make_key(query)
        cache.set(key, result, ttl=3600)
        cached = cache.get(key)
    """

    def __init__(self, max_size: int = 256):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        """
        Retrieve a cached value by key.

        Returns None if the key is missing or expired.

        Args:
            key: Cache key string.

        Returns:
            Cached value, or None.
        """
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """
        Store a value in the cache.

        Args:
            key: Cache key string.
            value: Value to cache.
            ttl: Time-to-live in seconds (default 3600).
        """
        expires_at = time.time() + ttl

        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = (value, expires_at)
        else:
            if len(self._store) >= self._max_size:
                self._store.popitem(last=False)  # Evict LRU
            self._store[key] = (value, expires_at)

    def make_key(self, query: SpatialQuery) -> str:
        """
        Generate a deterministic cache key from a SpatialQuery.

        Args:
            query: The spatial query to hash.

        Returns:
            Hex digest string suitable as a cache key.
        """
        payload = query.model_dump_json(exclude_none=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def invalidate(self, pattern: str) -> int:
        """
        Invalidate all keys matching a regex pattern.

        Args:
            pattern: Regex pattern to match against keys.

        Returns:
            Number of keys invalidated.
        """
        compiled = re.compile(pattern)
        keys_to_delete = [k for k in self._store if compiled.search(k)]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    def stats(self) -> dict[str, int]:
        """
        Return cache hit/miss statistics.

        Returns:
            Dict with hits, misses, size, and max_size.
        """
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
            "max_size": self._max_size,
        }
