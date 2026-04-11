"""A2A messaging — Msg, AgentCard, MessageHub for agent-to-agent communication.

Inspired by AgentScope's Msg/AgentCard/MsgHub patterns.
Lightweight version: in-memory registry, no HTTP/Nacos discovery yet.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Msg — the unit of communication between agents
# ---------------------------------------------------------------------------


class Msg(BaseModel):
    """A message exchanged between agents or between a user and an agent.

    Unlike a plain string, Msg carries role, sender identity, structured
    content, and metadata for tracing.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: str = "user"  # "user" | "assistant" | "system" | "tool"
    sender: str = ""  # Name of the agent or user that sent this
    receiver: str = ""  # Name of the target agent (empty = broadcast)
    content: str = ""  # Human-readable content
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    invocation_id: str = ""  # Groups messages in a single workflow run
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# AgentCard — agent capability advertisement
# ---------------------------------------------------------------------------


class AgentCard(BaseModel):
    """Metadata describing what an agent can do.

    Used by the coordinator to decide which specialist to route a task to.
    """

    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)  # e.g. ["geocoding", "site_selection"]
    keywords: list[str] = Field(default_factory=list)  # Intent-matching keywords
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    version: str = "1.0"

    def matches_intent(self, text: str) -> float:
        """Score how well this agent matches a free-text intent (0.0 to 1.0).

        Simple keyword-overlap heuristic. Can be replaced by embeddings later.
        """
        if not self.keywords:
            return 0.0
        text_lower = text.lower()
        matches = sum(1 for kw in self.keywords if kw.lower() in text_lower)
        return min(matches / max(len(self.keywords), 1), 1.0)


# ---------------------------------------------------------------------------
# AgentRegistry — in-memory registry of callable agents
# ---------------------------------------------------------------------------


# An agent callable takes a Msg and returns a Msg (can be sync or async)
AgentFn = Callable[[Msg], Any]


class AgentRegistry:
    """Lightweight in-memory registry mapping agent names to callables + cards.

    This is the substrate for A2A discovery: agents register themselves,
    the coordinator queries the registry to find matching specialists.
    """

    def __init__(self) -> None:
        self._agents: dict[str, tuple[AgentFn, AgentCard]] = {}

    def register(self, card: AgentCard, agent_fn: AgentFn) -> None:
        """Register an agent with a card and callable."""
        self._agents[card.name] = (agent_fn, card)

    def unregister(self, name: str) -> bool:
        """Remove an agent by name. Returns True if found."""
        return self._agents.pop(name, None) is not None

    def get(self, name: str) -> tuple[AgentFn, AgentCard] | None:
        """Look up an agent by name."""
        return self._agents.get(name)

    def list_cards(self) -> list[AgentCard]:
        """List all registered agent cards."""
        return [card for _, card in self._agents.values()]

    def find_by_intent(self, text: str, top_k: int = 3) -> list[tuple[AgentCard, float]]:
        """Find agents whose keywords match a free-text intent.

        Returns cards sorted by match score descending. Only returns
        agents with score > 0.
        """
        scored = [
            (card, card.matches_intent(text))
            for _, card in self._agents.values()
        ]
        scored = [(card, score) for card, score in scored if score > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        """Find agents that advertise a specific capability."""
        return [
            card for _, card in self._agents.values()
            if capability in card.capabilities
        ]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def clear(self) -> None:
        """Remove all registered agents."""
        self._agents.clear()


# ---------------------------------------------------------------------------
# MessageHub — pub-sub broker for agent communications
# ---------------------------------------------------------------------------


class MessageHub:
    """In-memory message broker that captures the conversation history
    between multiple agents. Useful for debugging multi-agent workflows
    and for injecting shared context.

    Each message is appended to the log and optionally observed by
    subscribers (callbacks that receive each new message).
    """

    def __init__(self, invocation_id: str | None = None) -> None:
        self.invocation_id = invocation_id or uuid.uuid4().hex[:12]
        self._log: list[Msg] = []
        self._subscribers: list[Callable[[Msg], None]] = []

    def post(self, msg: Msg) -> None:
        """Post a message to the hub. Appends to log and notifies subscribers."""
        if not msg.invocation_id:
            msg.invocation_id = self.invocation_id
        self._log.append(msg)
        for sub in self._subscribers:
            try:
                sub(msg)
            except Exception:
                # Subscribers must not break the hub
                continue

    def subscribe(self, callback: Callable[[Msg], None]) -> None:
        """Register a callback to be notified on each new message."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Msg], None]) -> None:
        """Remove a previously registered callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    @property
    def log(self) -> list[Msg]:
        """The full log of messages in this hub."""
        return list(self._log)

    def messages_from(self, sender: str) -> list[Msg]:
        """All messages posted by a specific sender."""
        return [m for m in self._log if m.sender == sender]

    def messages_to(self, receiver: str) -> list[Msg]:
        """All messages addressed to a specific receiver."""
        return [m for m in self._log if m.receiver == receiver]

    def last(self, n: int = 1) -> list[Msg]:
        """Return the last N messages."""
        return self._log[-n:]

    def clear(self) -> None:
        """Clear the log."""
        self._log.clear()

    def __len__(self) -> int:
        return len(self._log)
