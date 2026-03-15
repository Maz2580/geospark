"""Session persistence — save and resume conversations with full spatial context."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single message in a conversation."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []


class Session(BaseModel):
    """A conversation session with full spatial context."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    messages: list[Message] = []
    tool_history: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Add a message to the session."""
        msg = Message(
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
        )
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)

        # Auto-generate title from first user message
        if not self.title and role == "user":
            self.title = content[:80].strip()

        return msg

    def add_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        """Record a tool call in the session history."""
        self.tool_history.append(
            {
                "tool": tool_name,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.updated_at = datetime.now(timezone.utc)

    @property
    def message_count(self) -> int:
        """Number of messages in the session."""
        return len(self.messages)

    def to_context_messages(self) -> list[dict[str, str]]:
        """Convert session to LLM context messages format."""
        return [{"role": m.role, "content": m.content} for m in self.messages]


class SessionStore:
    """Persistent storage for conversation sessions.

    Uses local file storage (JSON). For production, swap in Supabase backend.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".geospark" / "sessions"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: Session) -> Path:
        """Save a session to disk."""
        path = self.storage_dir / f"{session.id}.json"
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, session_id: str) -> Session | None:
        """Load a session by ID."""
        path = self.storage_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session.model_validate(data)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions with summaries."""
        sessions = []
        for path in sorted(self.storage_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(
                    {
                        "id": data["id"],
                        "title": data.get("title", "Untitled"),
                        "message_count": len(data.get("messages", [])),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue
            if len(sessions) >= limit:
                break
        return sessions

    def get_latest(self) -> Session | None:
        """Load the most recently updated session."""
        sessions = self.list_sessions(limit=1)
        if not sessions:
            return None
        return self.load(sessions[0]["id"])

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        path = self.storage_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
