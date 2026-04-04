"""
Channel registry — lazy-loaded, auto-discovery for data channels.

Similar to the tool registry pattern but for live data sources.
"""

from __future__ import annotations

from typing import Any

from geospark.data_channels.base import BaseChannel, ChannelStatus

# Registry of available channels: name → import path
CHANNEL_CLASSES: dict[str, str] = {
    "weather": "geospark.data_channels.weather.WeatherChannel",
}


class ChannelRegistry:
    """Manages available data channels with lazy loading."""

    def __init__(self) -> None:
        self._channels: dict[str, BaseChannel] = {}

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
    ):
        """Search a specific channel."""
        channel = self.load_channel(channel_name)
        return await channel.search(**kwargs)
