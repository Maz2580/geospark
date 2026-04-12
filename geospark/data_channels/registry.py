"""
Channel registry — lazy-loaded, auto-discovery for data channels.

Similar to the tool registry pattern but for live data sources.
Includes transparent LRU+TTL caching to avoid redundant API calls.
"""

from __future__ import annotations

from typing import Any

from geospark.data_channels.base import BaseChannel, ChannelResult, ChannelStatus
from geospark.data_channels.cache import ChannelCache

# Registry of available channels: name → import path
CHANNEL_CLASSES: dict[str, str] = {
    "weather": "geospark.data_channels.weather.WeatherChannel",
    "air-quality": "geospark.data_channels.air_quality.AirQualityChannel",
    "fires": "geospark.data_channels.fires.FiresChannel",
}


class ChannelRegistry:
    """Manages available data channels with lazy loading and result caching."""

    def __init__(self, cache: ChannelCache | None = None) -> None:
        self._channels: dict[str, BaseChannel] = {}
        self._cache = cache or ChannelCache()

    def load_channel(self, name: str) -> BaseChannel:
        """Load a channel by name."""
        if name in self._channels:
            return self._channels[name]

        if name not in CHANNEL_CLASSES:
            raise ValueError(
                f"Unknown channel: {name}. Available: {list(CHANNEL_CLASSES.keys())}"
            )

        module_path, class_name = CHANNEL_CLASSES[name].rsplit(".", 1)
        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            channel = cls()
            self._channels[name] = channel
            return channel
        except Exception as e:
            raise RuntimeError(f"Failed to load channel '{name}': {e}") from e

    def load_all(self) -> list[BaseChannel]:
        """Load all registered channels."""
        channels = []
        for name in CHANNEL_CLASSES:
            try:
                channels.append(self.load_channel(name))
            except RuntimeError:
                continue
        return channels

    def list_channels(self) -> list[str]:
        """List all registered channel names."""
        return list(CHANNEL_CLASSES.keys())

    def check_all(self) -> list[ChannelStatus]:
        """Health check all channels."""
        results = []
        for name in CHANNEL_CLASSES:
            try:
                channel = self.load_channel(name)
                results.append(channel.check())
            except Exception as e:
                results.append(
                    ChannelStatus(name=name, status="error", message=str(e))
                )
        return results

    async def search(
        self,
        channel_name: str,
        **kwargs: Any,
    ) -> ChannelResult:
        """Search a specific channel with transparent caching.

        Returns cached result if available and fresh, otherwise queries
        the channel and caches the result.
        """
        cached = self._cache.get(channel_name, kwargs)
        if cached is not None:
            return cached

        channel = self.load_channel(channel_name)
        result = await channel.search(**kwargs)
        self._cache.put(channel_name, kwargs, result)
        return result

    def cache_stats(self) -> dict[str, Any]:
        """Return cache hit/miss statistics."""
        return self._cache.stats()

    def invalidate_cache(self, channel_name: str | None = None) -> int:
        """Clear cached results. Returns count of entries removed."""
        return self._cache.invalidate(channel_name)
