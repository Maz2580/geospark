"""AgentCoordinator — routes natural language goals to specialist agents.

Phase 7C of GeoSpark. Inspired by AgentScope's MsgHub + ReAct coordinator
pattern. Lightweight implementation: rule-based intent classification,
in-memory agent registry, optional streaming progress updates.
"""
from __future__ import annotations

import re
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

from pydantic import BaseModel, Field

from geospark.agents.messaging import AgentCard, AgentRegistry, MessageHub, Msg

# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


# Rule-based intent patterns: each agent advertises keywords, but we also
# use structural patterns for common query shapes.
_SITE_SELECT_PATTERNS = [
    r"\bbest\s+(?:\w+\s+)*(?:location|place|spot|site)\b",  # "best cafe spot", "best location"
    r"\bwhere\s+(?:to|should)\s+(?:put|place|open|build)\b",
    r"\bsite\s+(?:select|selection)\b",
    r"\boptimal\s+(?:\w+\s+)*(?:location|site|spot|place)\b",  # "optimal restaurant location"
    r"\bfind\s+(?:the\s+)?(?:best|ideal)\s+(?:\w+\s+)*(?:location|place|spot|site)\b",
]
_REPORT_PATTERNS = [
    r"\banalyze\s+(?:this\s+)?(?:location|place|area)\b",
    # "Analyze Federation Square", "Profile Fitzroy, Melbourne", "Report on Bondi Beach"
    r"^\s*(?:please\s+)?(?:analy[sz]e|profile|assess|describe|report\s+on|give\s+me\s+a\s+report\s+on)\s+\S",
    r"\bwhat\s+is\s+(?:it\s+)?like\s+(?:around|near|in|at)\b",
    r"\b(?:location|area)\s+(?:report|intelligence|profile|dossier)\b",
    r"\btell\s+me\s+about\s+(?:this|the)\b",
    r"\bwhat.s\s+(?:near|around|in)\b.*\?",
]


# --- turning a sentence into an agent's parameters ---------------------------------------------

_REPORT_VERB = re.compile(
    r"^\s*(?:please\s+)?(?:analy[sz]e|profile|assess|describe|report\s+on|give\s+me\s+a\s+report\s+on|"
    r"tell\s+me\s+about|what\s+is\s+(?:it\s+)?like\s+(?:around|near|in|at))\s+(?:the\s+area\s+(?:around|of)\s+)?",
    re.IGNORECASE,
)


def report_location(goal: str) -> str:
    """The place in a report request: "Analyze Federation Square, Melbourne" -> "Federation Square, Melbourne"."""
    return _REPORT_VERB.sub("", goal).strip().rstrip("?.!").strip() or goal.strip()


_CLAUSE = r"\s+(?:near|close\s+to|next\s+to|around|away\s+from|far\s+from|avoid(?:ing)?|but|with|that|which|within)\b"
_STOP = r"(?=" + _CLAUSE + r"|[,.?!]|$)"
_STOP_KEEP_COMMAS = r"(?=" + _CLAUSE + r"|[.?!]|$)"  # "in Fitzroy, Melbourne" keeps its comma


def _singular(word: str) -> str:
    w = word.strip().lower()
    if w.endswith("ies") and len(w) > 4:  # pharmacies, libraries, universities
        return w[:-3] + "y"
    if w.endswith("ches") or w.endswith("shes") or w.endswith("sses"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _things(text: str) -> list[str]:
    """ "schools and hospitals" / "a school, a park" -> ["school", "hospital"] (OSM amenity values)."""
    parts = re.split(r"\s*(?:,|\band\b|\bor\b|&)\s*", text)
    out = []
    for part in parts:
        part = re.sub(r"^(?:a|an|the|some|any)\s+", "", part.strip(), flags=re.IGNORECASE)
        if part:
            out.append(_singular(part).replace(" ", "_"))
    return list(dict.fromkeys(out))


def parse_site_goal(goal: str) -> dict[str, Any]:
    """Site-selection parameters from a sentence.

    "Find the best location for a cafe in Melbourne CBD near schools" ->
    {"facility_type": "cafe", "within": "Melbourne CBD", "near": ["school"], "avoid": []}
    """
    out: dict[str, Any] = {}
    facility = re.search(
        r"\b(?:for|(?:to|should\s+(?:i|we)|could\s+(?:i|we)|can\s+(?:i|we))\s+(?:open|put|place|build|start|locate))"
        r"\s+(?:a|an|the|my|our)?\s*([a-z][a-z\s]*?)(?=\s+in\b|" + _CLAUSE + r"|[,.?!]|$)",
        goal, re.IGNORECASE)
    if facility:
        out["facility_type"] = _singular(facility.group(1)).replace(" ", "_")
    within = re.search(r"\bin\s+(.+?)" + _STOP_KEEP_COMMAS, goal, re.IGNORECASE)
    if within:
        out["within"] = within.group(1).strip()
    near = re.search(r"\b(?:near|close\s+to|next\s+to|around)\s+(.+?)(?=\s+(?:but|away\s+from|far\s+from|avoid(?:ing)?|in)\b|[.?!]|$)",
                     goal, re.IGNORECASE)
    if near:
        out["near"] = _things(near.group(1))
    avoid = re.search(r"\b(?:away\s+from|far\s+from|avoid(?:ing)?)\s+(.+?)(?=\s+(?:but|near|close\s+to|in)\b|[.?!]|$)",
                      goal, re.IGNORECASE)
    if avoid:
        out["avoid"] = _things(avoid.group(1))
    return out


class IntentClassification(BaseModel):
    """Result of classifying a user goal to an agent."""

    goal: str
    matched_agent: str = ""
    score: float = 0.0
    reason: str = ""
    candidates: list[tuple[str, float]] = Field(default_factory=list)


def classify_intent(
    goal: str,
    registry: AgentRegistry,
) -> IntentClassification:
    """Classify a user goal and return the best-matching agent name.

    Uses a combination of:
    1. Structural regex patterns (for "find the best place" etc.)
    2. AgentCard keyword matching from the registry
    3. Falls back to the generic 'geo_agent' if nothing else matches.
    """
    goal_lower = goal.lower()
    result = IntentClassification(goal=goal)

    # Structural pattern matching (high confidence)
    for pattern in _SITE_SELECT_PATTERNS:
        if re.search(pattern, goal_lower) and "site_selector" in registry:
            result.matched_agent = "site_selector"
            result.score = 0.95
            result.reason = f"Matched site-selection pattern: {pattern!r}"
            return result

    for pattern in _REPORT_PATTERNS:
        if re.search(pattern, goal_lower) and "spatial_report" in registry:
            result.matched_agent = "spatial_report"
            result.score = 0.9
            result.reason = f"Matched report pattern: {pattern!r}"
            return result

    # Keyword scoring via AgentCards
    keyword_matches = registry.find_by_intent(goal, top_k=3)
    result.candidates = [(card.name, score) for card, score in keyword_matches]
    if keyword_matches:
        best_card, best_score = keyword_matches[0]
        result.matched_agent = best_card.name
        result.score = best_score
        result.reason = f"Best keyword match: {best_card.name} (score={best_score:.2f})"
        return result

    # Fallback: generic geo agent
    if "geo_agent" in registry:
        result.matched_agent = "geo_agent"
        result.score = 0.5
        result.reason = "Fallback to generic geo_agent"
    return result


# ---------------------------------------------------------------------------
# Progress events for streaming
# ---------------------------------------------------------------------------


class ProgressEvent(BaseModel):
    """A streaming progress event from the coordinator."""

    event_type: str  # "classify" | "dispatch" | "agent_start" | "agent_done" | "complete" | "error"
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Coordination result
# ---------------------------------------------------------------------------


class CoordinationResult(BaseModel):
    """Final result from an AgentCoordinator run."""

    goal: str
    agent_used: str = ""
    classification: IntentClassification | None = None
    response: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    duration_s: float = 0.0
    error: str | None = None
    conversation: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AgentCoordinator
# ---------------------------------------------------------------------------


class AgentCoordinator:
    """Multi-agent coordinator that routes goals to specialist agents.

    Wraps a registry of specialist agents, classifies incoming goals,
    dispatches to the right specialist, and aggregates the response.

    Supports:
    - Synchronous run() for simple one-shot dispatch
    - Async stream() that yields ProgressEvent objects as work progresses
    - MessageHub logging for debugging multi-agent conversations
    - Built-in registration of GeoSpark's standard specialists
    """

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        hub: MessageHub | None = None,
        auto_register_defaults: bool = True,
    ) -> None:
        self.registry = registry or AgentRegistry()
        self.hub = hub or MessageHub()
        if auto_register_defaults:
            self._register_defaults()

    # -------------------------------------------------------------------
    # Default agent registration
    # -------------------------------------------------------------------

    def _register_defaults(self) -> None:
        """Register GeoSpark's standard specialist agents.

        Uses lazy imports so coordinator can be used even when specialist
        dependencies (like OSM loaders) aren't installed.
        """
        # GeoAgent — generic spatial reasoning
        try:
            from geospark.agents.geo_agent import GeoAgent

            geo_card = AgentCard(
                name="geo_agent",
                description="Autonomous spatial reasoning for open-ended geographic questions.",
                capabilities=["geocoding", "distance", "topology", "spatial_query"],
                keywords=[
                    "find", "near", "within", "distance", "how far",
                    "what is", "where is", "query", "search",
                ],
            )

            def _geo_fn(msg: Msg) -> Msg:
                agent = GeoAgent()
                result = agent.run(msg.content)
                return Msg(
                    role="assistant",
                    sender="geo_agent",
                    receiver=msg.sender,
                    content=result.summary,
                    metadata={
                        "steps": [s.model_dump(mode="json") for s in result.steps],
                        "findings": result.findings,
                        "duration_s": result.total_duration_s,
                    },
                )

            self.registry.register(geo_card, _geo_fn)
        except ImportError:
            pass

        # SiteSelector — optimal location finding
        try:
            from geospark.agents.site_selector import SiteSelector

            site_card = AgentCard(
                name="site_selector",
                description="Find optimal locations matching spatial criteria (near X, avoid Y).",
                capabilities=["site_selection", "multi_criteria", "ranking"],
                keywords=[
                    "best location", "optimal site", "where to build",
                    "where to open", "place a", "site selection", "ideal spot",
                ],
            )

            def _site_fn(msg: Msg) -> Msg:
                selector = SiteSelector()
                # Explicit parameters win; anything missing is read from the sentence itself
                params = {**parse_site_goal(msg.content), **msg.metadata.get("parameters", {})}
                within = params.get("within", "")
                if not within:
                    return Msg(role="assistant", sender="site_selector", receiver=msg.sender,
                               content="Which area should I search? Add it to the request, for example "
                                       "'... in Melbourne CBD'.",
                               metadata={"candidates": [], "duration_s": 0.0})

                result = selector.find(
                    within=within,
                    near=params.get("near", []),
                    avoid=params.get("avoid", []),
                    facility_type=params.get("facility_type", "restaurant"),
                    radius_m=params.get("radius_m", 5000),
                )
                return Msg(
                    role="assistant",
                    sender="site_selector",
                    receiver=msg.sender,
                    content=result.summary,
                    metadata={
                        "candidates": [c.model_dump(mode="json") for c in result.candidates[:10]],
                        "parameters": {"within": within, "near": params.get("near", []),
                                       "avoid": params.get("avoid", []),
                                       "facility_type": params.get("facility_type", "restaurant")},
                        "data_gaps": result.data_gaps,
                        "caveats": result.caveats,
                        "duration_s": result.duration_s,
                    },
                )

            self.registry.register(site_card, _site_fn)
        except ImportError:
            pass

        # SpatialReport — location dossier
        try:
            from geospark.agents.spatial_report import SpatialReport

            report_card = AgentCard(
                name="spatial_report",
                description="Generate a comprehensive intelligence report for a location.",
                capabilities=["location_report", "amenity_analysis", "accessibility"],
                keywords=[
                    "analyze location", "location report", "tell me about",
                    "what's near", "profile", "dossier", "area report",
                ],
            )

            def _report_fn(msg: Msg) -> Msg:
                reporter = SpatialReport()
                params = msg.metadata.get("parameters", {})
                location = params.get("location") or report_location(msg.content)
                result = reporter.analyze(
                    location=location,
                    radius_m=params.get("radius_m", 2000),
                )
                return Msg(
                    role="assistant",
                    sender="spatial_report",
                    receiver=msg.sender,
                    content=result.summary,
                    metadata={
                        "address": result.address,
                        "coordinates": result.coordinates,
                        "nearby": [n.model_dump(mode="json") for n in result.nearby[:20]],
                        "accessibility": [a.model_dump(mode="json") for a in result.accessibility],
                        "data_gaps": result.data_gaps,
                        "caveats": result.caveats,
                        "duration_s": result.duration_s,
                    },
                )

            self.registry.register(report_card, _report_fn)
        except ImportError:
            pass

    # -------------------------------------------------------------------
    # Custom agent registration
    # -------------------------------------------------------------------

    def register_agent(
        self, card: AgentCard, agent_fn: Callable[[Msg], Msg]
    ) -> None:
        """Register a custom agent in the coordinator's registry."""
        self.registry.register(card, agent_fn)

    # -------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------

    def run(
        self,
        goal: str,
        parameters: dict[str, Any] | None = None,
    ) -> CoordinationResult:
        """Classify the goal, dispatch to the matching agent, return result.

        Args:
            goal: Natural-language goal for the multi-agent system.
            parameters: Optional structured parameters passed to the specialist.
        """
        start = time.time()
        result = CoordinationResult(goal=goal)

        # 1. Classify
        classification = classify_intent(goal, self.registry)
        result.classification = classification

        user_msg = Msg(
            role="user",
            sender="user",
            receiver=classification.matched_agent or "coordinator",
            content=goal,
            metadata={"parameters": parameters or {}},
        )
        self.hub.post(user_msg)

        if not classification.matched_agent:
            result.error = "No matching agent found"
            result.summary = "Coordinator could not route the goal to any specialist."
            result.duration_s = round(time.time() - start, 3)
            result.conversation = [m.to_dict() for m in self.hub.last(5)]
            return result

        # 2. Dispatch
        lookup = self.registry.get(classification.matched_agent)
        if lookup is None:
            result.error = f"Agent disappeared from registry: {classification.matched_agent}"
            result.duration_s = round(time.time() - start, 3)
            return result

        agent_fn, card = lookup
        result.agent_used = card.name

        try:
            reply = agent_fn(user_msg)
            if not isinstance(reply, Msg):
                # Allow lightweight agents to return a string
                reply = Msg(
                    role="assistant",
                    sender=card.name,
                    receiver="user",
                    content=str(reply),
                )
            self.hub.post(reply)
            result.response = reply.metadata
            result.summary = reply.content
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.summary = f"Specialist '{card.name}' failed: {result.error}"

        result.duration_s = round(time.time() - start, 3)
        result.conversation = [m.to_dict() for m in self.hub.last(10)]
        return result

    async def stream(
        self,
        goal: str,
        parameters: dict[str, Any] | None = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Yield progress events as the coordinator works through a goal.

        Useful for long-running workflows where the user wants to see
        partial progress.

        Events emitted:
        - classify: intent classification started
        - dispatch: agent selected and message prepared
        - agent_start: specialist agent invoked
        - agent_done: specialist returned
        - complete: final result
        - error: failure
        """
        yield ProgressEvent(
            event_type="classify",
            message=f"Classifying goal: {goal[:80]}",
        )

        classification = classify_intent(goal, self.registry)
        yield ProgressEvent(
            event_type="dispatch",
            message=f"Routing to '{classification.matched_agent}' (score={classification.score:.2f})",
            data={"classification": classification.model_dump()},
        )

        if not classification.matched_agent:
            yield ProgressEvent(
                event_type="error",
                message="No matching agent found",
            )
            return

        user_msg = Msg(
            role="user",
            sender="user",
            receiver=classification.matched_agent,
            content=goal,
            metadata={"parameters": parameters or {}},
        )
        self.hub.post(user_msg)

        lookup = self.registry.get(classification.matched_agent)
        if lookup is None:
            yield ProgressEvent(
                event_type="error",
                message=f"Agent disappeared: {classification.matched_agent}",
            )
            return

        agent_fn, card = lookup
        yield ProgressEvent(
            event_type="agent_start",
            message=f"Running {card.name}",
            data={"agent": card.name},
        )

        try:
            reply = agent_fn(user_msg)
            if not isinstance(reply, Msg):
                reply = Msg(
                    role="assistant",
                    sender=card.name,
                    receiver="user",
                    content=str(reply),
                )
            self.hub.post(reply)

            yield ProgressEvent(
                event_type="agent_done",
                message=f"{card.name} finished",
                data={"summary": reply.content},
            )
            yield ProgressEvent(
                event_type="complete",
                message=reply.content,
                data={
                    "agent": card.name,
                    "metadata": reply.metadata,
                },
            )
        except Exception as exc:
            yield ProgressEvent(
                event_type="error",
                message=f"{type(exc).__name__}: {exc}",
            )

    # -------------------------------------------------------------------
    # Introspection
    # -------------------------------------------------------------------

    def list_agents(self) -> list[AgentCard]:
        """Return the cards of all registered specialist agents."""
        return self.registry.list_cards()

    def describe(self) -> dict[str, Any]:
        """Return a summary of the coordinator state."""
        return {
            "registered_agents": [
                {
                    "name": card.name,
                    "description": card.description,
                    "capabilities": card.capabilities,
                }
                for card in self.registry.list_cards()
            ],
            "message_count": len(self.hub),
        }
