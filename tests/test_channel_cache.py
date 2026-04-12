"""Tests for the data channel LRU+TTL cache (Phase 8A-4a)."""
from __future__ import annotations

import time

from geospark.data_channels.base import ChannelResult
from geospark.data_channels.cache import ChannelCache, _make_cache_key


class TestMakeCacheKey:
    """Tests for deterministic cache key generation."""

    def test_same_args_same_key(self) -> None:
        k1 = _make_cache_key("weather", {"location": "Paris"})
        k2 = _make_cache_key("weather", {"location": "Paris"})
        assert k1 == k2

    def test_different_args_different_key(self) -> None:
        k1 = _make_cache_key("weather", {"location": "Paris"})
        k2 = _make_cache_key("weather", {"location": "London"})
        assert k1 != k2

    def test_different_channels_different_key(self) -> None:
        k1 = _make_cache_key("weather", {"location": "Paris"})
        k2 = _make_cache_key("fires", {"location": "Paris"})
        assert k1 != k2

    def test_none_values_filtered(self) -> None:
        k1 = _make_cache_key("weather", {"location": "Paris", "bbox": None})
        k2 = _make_cache_key("weather", {"location": "Paris"})
        assert k1 == k2

    def test_key_order_independent(self) -> None:
        k1 = _make_cache_key("weather", {"a": 1, "b": 2})
        k2 = _make_cache_key("weather", {"b": 2, "a": 1})
        assert k1 == k2

    def test_key_is_short_hex(self) -> None:
        key = _make_cache_key("weather", {"location": "test"})
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)


class TestChannelCache:
    """Tests for the LRU+TTL cache."""

    def _make_result(self, channel: str = "weather") -> ChannelResult:
        return ChannelResult(
            channel=channel,
            features=[{"temp": 22}],
            total_results=1,
        )

    def test_miss_on_empty_cache(self) -> None:
        cache = ChannelCache()
        assert cache.get("weather", {"location": "Paris"}) is None

    def test_put_and_get(self) -> None:
        cache = ChannelCache()
        result = self._make_result()
        cache.put("weather", {"location": "Paris"}, result)
        cached = cache.get("weather", {"location": "Paris"})
        assert cached is not None
        assert cached.features == [{"temp": 22}]

    def test_hit_increments_counter(self) -> None:
        cache = ChannelCache()
        result = self._make_result()
        cache.put("weather", {"location": "Paris"}, result)
        cache.get("weather", {"location": "Paris"})
        cache.get("weather", {"location": "Paris"})
        assert cache._hits == 2
        assert cache._misses == 0

    def test_miss_increments_counter(self) -> None:
        cache = ChannelCache()
        cache.get("weather", {"location": "nope"})
        assert cache._misses == 1
        assert cache._hits == 0

    def test_ttl_expiration(self) -> None:
        cache = ChannelCache(ttl_seconds=1)
        cache.put("weather", {"location": "Paris"}, self._make_result())
        assert cache.get("weather", {"location": "Paris"}) is not None
        time.sleep(1.1)
        assert cache.get("weather", {"location": "Paris"}) is None

    def test_lru_eviction(self) -> None:
        cache = ChannelCache(max_entries=2)
        cache.put("weather", {"location": "A"}, self._make_result())
        cache.put("weather", {"location": "B"}, self._make_result())
        cache.put("weather", {"location": "C"}, self._make_result())
        # A should be evicted (oldest)
        assert cache.get("weather", {"location": "A"}) is None
        assert cache.get("weather", {"location": "B"}) is not None
        assert cache.get("weather", {"location": "C"}) is not None
        assert cache.size == 2

    def test_invalidate_all(self) -> None:
        cache = ChannelCache()
        cache.put("weather", {"location": "A"}, self._make_result())
        cache.put("fires", {"location": "B"}, self._make_result("fires"))
        removed = cache.invalidate()
        assert removed == 2
        assert cache.size == 0

    def test_stats(self) -> None:
        cache = ChannelCache(ttl_seconds=300)
        cache.put("weather", {"location": "A"}, self._make_result())
        cache.get("weather", {"location": "A"})
        cache.get("weather", {"location": "miss"})
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["enabled"] is True

    def test_disabled_cache(self) -> None:
        cache = ChannelCache()
        cache.enabled = False
        cache.put("weather", {"location": "A"}, self._make_result())
        assert cache.get("weather", {"location": "A"}) is None
        assert cache.size == 0

    def test_size_property(self) -> None:
        cache = ChannelCache()
        assert cache.size == 0
        cache.put("weather", {"location": "A"}, self._make_result())
        assert cache.size == 1
