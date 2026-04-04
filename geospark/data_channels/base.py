"""
Base channel protocol for geospatial data sources.

Every data channel implements this interface, enabling unified access
to weather, satellite, air quality, fire, census, and other data
through a single API pattern.

Inspired by Agent-Reach's modular channel architecture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ChannelResult(BaseModel):
    """Standardized result from any data channel."""

    channel: str
    query: dict[str, Any] = Field(default_factory=dict)
    features: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_results: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.features) == 0 and not self.errors


class ChannelStatus(BaseModel):
    """Health check result for a channel."""

    name: str
    status: str  # "ok", "warn", "error", "unconfigured"
    message: str = ""
    tier: int = 0


class BaseChannel(Protocol):
    """Protocol that all geospatial data channels must implement."""

    name: str
    description: str
    tier: int  # 0 = free/no auth, 1 = free API key, 2 = commercial

    def check(self) -> ChannelStatus:
        """Check if this channel is available and configured."""
        ...

    async def search(
        self,
        location: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ChannelResult:
        """Search for data matching spatial and temporal criteria."""
        ...
