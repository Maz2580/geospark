"""Spatial memory — persistent spatial knowledge that survives across sessions."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class SpatialMemoryEntry(BaseModel):
    """A single spatial memory entry."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    scope: Literal["session", "project", "global"] = "project"
    memory_type: Literal[
        "tool_result", "user_preference", "spatial_knowledge", "workflow_outcome"
    ] = "spatial_knowledge"
    content: str
    geometry: dict[str, Any] | None = None
    tags: list[str] = []
    score: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def matches_query(self, query: str) -> float:
        """Simple text-based relevance score (0-1).

        For production, replace with embedding-based similarity.
        """
        query_lower = query.lower()
        content_lower = self.content.lower()

        # Exact substring match
        if query_lower in content_lower:
            return 0.9

        # Word overlap
        query_words = set(query_lower.split())
        content_words = set(content_lower.split())
        overlap = len(query_words & content_words)
        if overlap == 0:
            return 0.0
        return min(overlap / len(query_words), 0.8)


class SpatialMemory:
    """Persistent spatial memory store.

    Stores spatial knowledge, user preferences, and tool results
    that persist across sessions. Enables GeoSpark to remember
    context like "user usually works with EPSG:32631" or
    "user's farm is at coordinates [2.35, 48.86]".

    Uses local file storage (JSON). For production, swap in Supabase.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".geospark" / "memory"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[SpatialMemoryEntry] = []
        self._load_all()

    def _load_all(self) -> None:
        """Load all memories from disk."""
        path = self.storage_dir / "memories.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._entries = [SpatialMemoryEntry.model_validate(e) for e in data]
            except (json.JSONDecodeError, KeyError):
                self._entries = []

    def _save_all(self) -> None:
        """Persist all memories to disk."""
        path = self.storage_dir / "memories.json"
        data = [e.model_dump(mode="json") for e in self._entries]
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def remember(
        self,
        content: str,
        memory_type: str = "spatial_knowledge",
        scope: str = "project",
        geometry: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SpatialMemoryEntry:
        """Store a new spatial memory."""
        entry = SpatialMemoryEntry(
            content=content,
            memory_type=memory_type,  # type: ignore[arg-type]
            scope=scope,  # type: ignore[arg-type]
            geometry=geometry,
            tags=tags or [],
        )
        self._entries.append(entry)
        self._save_all()
        return entry

    def recall(
        self,
        query: str,
        scope: str | None = None,
        memory_type: str | None = None,
        limit: int = 5,
    ) -> list[SpatialMemoryEntry]:
        """Retrieve relevant memories for a query.

        Uses text-based matching. For production, replace with
        embedding similarity + recency weighting.
        """
        candidates = self._entries

        # Filter by scope
        if scope:
            candidates = [e for e in candidates if e.scope == scope]

        # Filter by type
        if memory_type:
            candidates = [e for e in candidates if e.memory_type == memory_type]

        # Score and rank
        scored = []
        for entry in candidates:
            relevance = entry.matches_query(query)
            if relevance > 0.0:
                # Final score: similarity * 0.7 + recency * 0.3
                age_hours = (
                    datetime.now(timezone.utc) - entry.created_at
                ).total_seconds() / 3600
                recency = max(0.0, 1.0 - age_hours / (24 * 30))  # decay over 30 days
                final_score = relevance * 0.7 + recency * 0.3
                scored.append((final_score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def forget(self, memory_id: str) -> bool:
        """Remove a specific memory."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != memory_id]
        if len(self._entries) < before:
            self._save_all()
            return True
        return False

    def list_all(
        self,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[SpatialMemoryEntry]:
        """List all stored memories."""
        entries = self._entries
        if scope:
            entries = [e for e in entries if e.scope == scope]
        return entries[:limit]

    @property
    def count(self) -> int:
        """Number of stored memories."""
        return len(self._entries)

    def clear(self, scope: str | None = None) -> int:
        """Clear memories. If scope is given, only clear that scope."""
        if scope:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.scope != scope]
            removed = before - len(self._entries)
        else:
            removed = len(self._entries)
            self._entries = []
        self._save_all()
        return removed
