"""Chat-to-Flow builder: natural-language goal -> Flow DAG via LLM tool calling.

Phase 8B of GeoSpark. The user describes a spatial workflow in English; a
small LLM (Qwen 2.5 7B via Ollama, or any OpenAI-compatible provider) incrementally
constructs a Flow by invoking a fixed set of builder tools:

    add_step       - register a step in the DAG
    add_route      - add a conditional route between two steps
    set_trigger    - configure the flow trigger (manual / schedule / event)
    finish_flow    - validate the DAG and emit the final Flow object

Because each tool call is validated individually, malformed output never
reaches FlowRunner: bad inputs surface as error strings that the LLM can see
and correct on the next turn.

Validation level: Medium — steps exist, depends_on IDs resolve, route targets
resolve, no dependency cycles.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from geospark.agents.toolkit import Toolkit
from geospark.flows.flow_builder import FlowBuilder, FlowBuilderError
from geospark.flows.flow_schema import Flow
from geospark.flows.tool_catalog import TOOL_CATALOG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


ChatResponse = dict[str, Any]
"""Shape: {"content": str | None, "tool_calls": list[dict]}.

Each tool_call is {"id": str, "function": {"name": str, "arguments": dict | str}}.
Arguments may be a dict (already parsed) or a JSON string — the session
handles both.
"""

ChatFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], ChatResponse]
"""Signature: (messages, tools) -> response.

Any LLM provider can be adapted to this by wrapping its chat-completion
endpoint; see `make_ollama_chat_fn` below.
"""


@dataclass
class ToolCallRecord:
    """A single tool invocation made during a ChatFlowSession run."""

    tool: str
    arguments: dict[str, Any]
    result: str
    ok: bool


@dataclass
class ChatFlowResult:
    """Outcome of a ChatFlowSession.run()."""

    flow: Flow | None
    turns: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Medium DAG validator
# ---------------------------------------------------------------------------


def _validate_flow_dag(builder: FlowBuilder) -> list[str]:
    """Medium validation: every dep and route target resolves; no cycles.

    Returns a list of human-readable error messages. Empty list means the
    in-progress flow is structurally valid and safe to hand to FlowRunner.

    Checks performed:
        1. At least one step has been added.
        2. Every `depends_on` id references an existing step.
        3. Every `route.target_step_id` references an existing step.
        4. The step graph (edges from deps) has no cycles.
    """
    steps = list(builder._steps)  # noqa: SLF001 - internal-use by design
    errors: list[str] = []

    if not steps:
        errors.append("flow has no steps; add at least one step before finishing")
        return errors

    step_ids = {s.id for s in steps}

    for step in steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                errors.append(
                    f"step '{step.id}' depends on unknown step '{dep}'"
                )
        for route in step.routes:
            if route.target_step_id not in step_ids:
                errors.append(
                    f"step '{step.id}' has route to unknown step "
                    f"'{route.target_step_id}'"
                )

    # Cycle check via Kahn's algorithm on depends_on edges.
    in_degree = {s.id: len(s.depends_on) for s in steps}
    queue: deque[str] = deque(sid for sid, d in in_degree.items() if d == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for s in steps:
            if current in s.depends_on:
                in_degree[s.id] -= 1
                if in_degree[s.id] == 0:
                    queue.append(s.id)
    if visited != len(steps):
        errors.append(
            "dependency cycle detected; remove circular depends_on references"
        )

    return errors


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_TEMPLATE = """\
You are GeoSpark's Flow Builder assistant. Your job is to convert a natural
language spatial-analysis goal from the user into a Flow DAG by calling the
builder tools available to you.

Available builder tools:
  - add_step:     add one step to the flow
  - add_route:    add a conditional route between two already-added steps
  - set_trigger:  configure how the flow is triggered (default: manual)
  - finish_flow:  finalise the flow — CALL THIS LAST

Rules you MUST follow:
  1. Call exactly ONE builder tool per turn.
  2. Use short snake_case step_ids like "geocode", "ndvi", "alert".
  3. Add steps in dependency order (parents before children).
  4. Only add a route when both its source and target step already exist.
  5. Reference prior step output inside parameters using "{step_id.field}".
  6. Call finish_flow only once the DAG is complete and consistent.
  7. Never invent tool names — use only those in the catalog below.

__TOOL_CATALOG__

When you have finished the DAG, call finish_flow(name, description) to emit
the final Flow. If a tool call fails with an ERROR, read the message and
correct your next call — do not repeat the failing call unchanged.
"""


def build_system_prompt(tool_catalog: str | None = None) -> str:
    """Render the system prompt, optionally with a custom catalog override.

    Uses simple substitution (not str.format) because the prompt body contains
    literal "{step_id.field}" reference-syntax tokens that must survive
    rendering without being interpreted as format placeholders.
    """
    catalog = tool_catalog if tool_catalog is not None else TOOL_CATALOG
    return _SYSTEM_PROMPT_TEMPLATE.replace("__TOOL_CATALOG__", catalog)


# ---------------------------------------------------------------------------
# ChatFlowSession
# ---------------------------------------------------------------------------


class ChatFlowSession:
    """Stateful session that converts a goal into a Flow via LLM tool calls.

    Usage:
        session = ChatFlowSession(llm_fn=make_ollama_chat_fn("qwen2.5:7b"))
        result = session.run("Monitor vegetation in Valencia; alert if NDVI < 0.3")
        if result.flow is not None:
            FlowRunner().run(result.flow)
    """

    def __init__(
        self,
        llm_fn: ChatFn,
        *,
        system_prompt: str | None = None,
        tool_catalog: str | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.builder = FlowBuilder()
        self.toolkit = Toolkit()
        self._finished: Flow | None = None
        self._register_tools()
        self.system_prompt = system_prompt or build_system_prompt(tool_catalog)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        self.toolkit.register(self._add_step_tool, name="add_step")
        self.toolkit.register(self._add_route_tool, name="add_route")
        self.toolkit.register(self._set_trigger_tool, name="set_trigger")
        self.toolkit.register(self._finish_flow_tool, name="finish_flow")

    # ------------------------------------------------------------------
    # Tool implementations (closures over self.builder)
    # ------------------------------------------------------------------

    def _add_step_tool(
        self,
        step_id: str,
        name: str,
        tool: str = "",
        operation: str = "",
        parameters_json: str = "",
        depends_on_csv: str = "",
        agent_instructions: str = "",
    ) -> str:
        """Add a step to the flow DAG.

        Args:
            step_id: Unique snake_case identifier for this step.
            name: Human-readable step name.
            tool: Tool to execute (geocoder, ndvi, terrain, spatial_reasoner, etc.).
                Leave as empty string for a pure LLM / interpretation step.
            operation: Operation on the tool (geocode, distance, buffer, elevation, etc.).
                Leave as empty string for a pure LLM step.
            parameters_json: JSON object string of tool parameters. Reference prior
                step results using "{step_id.field}" syntax.
            depends_on_csv: Comma-separated step ids this step depends on.
            agent_instructions: Optional free-text guidance for LLM-style steps.

        Returns:
            Success or ERROR message.
        """
        try:
            params = json.loads(parameters_json) if parameters_json.strip() else {}
        except json.JSONDecodeError as err:
            return f"ERROR: parameters_json is not valid JSON: {err}"
        if not isinstance(params, dict):
            return "ERROR: parameters_json must encode a JSON object"
        deps = [d.strip() for d in depends_on_csv.split(",") if d.strip()]
        try:
            self.builder.add_step(
                name=name,
                step_id=step_id,
                tool=tool or None,
                operation=operation or None,
                parameters=params,
                depends_on=deps,
                agent_instructions=agent_instructions,
            )
        except FlowBuilderError as err:
            return f"ERROR: {err}"
        return f"OK: step '{step_id}' added"

    def _add_route_tool(
        self,
        from_step: str,
        to_step: str,
        condition: str,
        description: str = "",
    ) -> str:
        """Add a conditional route between two existing steps.

        Args:
            from_step: Source step id (must already exist).
            to_step: Target step id (must already exist before finish_flow).
            condition: Natural-language condition, e.g. "if ndvi < 0.3".
            description: Optional human-readable note about the route.

        Returns:
            Success or ERROR message.
        """
        try:
            self.builder.add_route(
                from_step=from_step,
                to_step=to_step,
                condition=condition,
                description=description,
            )
        except FlowBuilderError as err:
            return f"ERROR: {err}"
        return f"OK: route '{from_step}' -> '{to_step}' added"

    def _set_trigger_tool(
        self,
        trigger_type: str = "manual",
        schedule: str = "",
        event_type: str = "",
    ) -> str:
        """Set the flow trigger.

        Args:
            trigger_type: "manual", "schedule", or "event".
            schedule: Cron expression (required when trigger_type is "schedule").
            event_type: Webhook event name (required when trigger_type is "event").

        Returns:
            Success or ERROR message.
        """
        if trigger_type not in {"manual", "schedule", "event"}:
            return (
                f"ERROR: trigger_type must be manual|schedule|event, "
                f"got '{trigger_type}'"
            )
        try:
            self.builder.set_trigger(
                trigger_type=trigger_type,
                schedule=schedule or None,
                event_type=event_type or None,
            )
        except Exception as err:  # noqa: BLE001 — surface any pydantic error to LLM
            return f"ERROR: {err}"
        return f"OK: trigger set to {trigger_type}"

    def _finish_flow_tool(self, name: str, description: str = "") -> str:
        """Validate the DAG and emit the final Flow. Call this exactly once, last.

        Args:
            name: Flow name.
            description: Flow description.

        Returns:
            DONE on success; VALIDATION_ERROR with details if the DAG is invalid.
        """
        errors = _validate_flow_dag(self.builder)
        if errors:
            return "VALIDATION_ERROR: " + "; ".join(errors)
        try:
            self._finished = self.builder.build(name=name, description=description)
        except FlowBuilderError as err:
            return f"ERROR: {err}"
        return (
            f"DONE: flow '{name}' built with {len(self._finished.steps)} step(s)"
        )

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self, goal: str, *, max_turns: int = 20) -> ChatFlowResult:
        """Drive the LLM loop until the flow is finished or we run out of turns."""
        start = time.time()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": goal},
        ]
        tools = self.toolkit.list_openai_tools()
        tool_log: list[ToolCallRecord] = []

        turns = 0
        for turn in range(max_turns):
            turns = turn + 1
            response = self.llm_fn(messages, tools)
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []

            if not tool_calls:
                # LLM stopped talking; accept only if finish_flow already ran.
                if self._finished is not None:
                    break
                return ChatFlowResult(
                    flow=None,
                    turns=turns,
                    tool_calls=tool_log,
                    messages=messages,
                    duration_s=round(time.time() - start, 3),
                    error=f"LLM stopped without calling finish_flow: {content[:200]}",
                )

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args or {})

                try:
                    result_str = self.toolkit.invoke(name, **args)
                    ok = not (
                        result_str.startswith("ERROR")
                        or result_str.startswith("VALIDATION_ERROR")
                    )
                except KeyError:
                    result_str = f"ERROR: unknown builder tool '{name}'"
                    ok = False
                except TypeError as err:
                    result_str = f"ERROR: bad arguments for {name}: {err}"
                    ok = False

                tool_log.append(ToolCallRecord(
                    tool=name, arguments=args, result=result_str, ok=ok,
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": result_str,
                })

            if self._finished is not None:
                break

        if self._finished is None:
            return ChatFlowResult(
                flow=None,
                turns=turns,
                tool_calls=tool_log,
                messages=messages,
                duration_s=round(time.time() - start, 3),
                error=f"Max turns ({max_turns}) reached without finish_flow",
            )

        return ChatFlowResult(
            flow=self._finished,
            turns=turns,
            tool_calls=tool_log,
            messages=messages,
            duration_s=round(time.time() - start, 3),
        )


# ---------------------------------------------------------------------------
# Ollama adapter
# ---------------------------------------------------------------------------


def make_ollama_chat_fn(
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    timeout: float = 120.0,
) -> ChatFn:
    """Return a ChatFn backed by a local Ollama server.

    Matches the shape used elsewhere in geospark.integrations.ollama_tools.
    Ollama's /api/chat endpoint is OpenAI-compatible for tool calls.
    """

    base = base_url.rstrip("/")

    def _chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResponse:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        resp = httpx.post(f"{base}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        raw_calls = msg.get("tool_calls") or []
        tool_calls = [
            {
                "id": tc.get("id", f"tc_{i}"),
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", {}),
                },
            }
            for i, tc in enumerate(raw_calls)
        ]
        return {"content": msg.get("content"), "tool_calls": tool_calls}

    return _chat


__all__ = [
    "ChatFlowResult",
    "ChatFlowSession",
    "ChatFn",
    "ToolCallRecord",
    "build_system_prompt",
    "make_ollama_chat_fn",
]
