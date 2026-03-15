"""
OpenRouter Integration.

Connects GeoSpark to any LLM via OpenRouter, supporting 300+ models.
Uses free models by default -- zero cost for development and demos.

Key advantage: OpenRouter provides a unified OpenAI-compatible API
for models from Meta, Google, Mistral, NVIDIA, Qwen, and more.
All with tool/function calling support.

System prompt design follows best practices from analysis of:
- Manus Agent (single-tool-per-iteration, "What+When+Returns" descriptions)
- Devin AI (<think> scratchpad for reasoning chains)
- Cursor (required `explanation` field, retry limits)
- Claude Code (negative guidance, structured tool routing)
- Codex CLI (progress updates, sandbox patterns)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from geospark.integrations.mcp_server import MCP_TOOLS, GeoSparkMCPHandler

# Best free models ranked by quality for geospatial tasks
FREE_MODELS = {
    "best": "meta-llama/llama-3.3-70b-instruct:free",       # 128K ctx, tool calling
    "coder": "qwen/qwen3-coder:free",                        # 262K ctx, structured output
    "large": "openai/gpt-oss-120b:free",                     # 131K ctx, largest free
    "fast": "mistralai/mistral-small-3.1-24b-instruct:free", # 128K ctx, fast
    "long_context": "nvidia/nemotron-3-nano-30b-a3b:free",   # 256K ctx
    "vision": "nvidia/nemotron-nano-12b-v2-vl:free",         # 128K ctx, vision+tools
    "auto": "openrouter/free",                                # Auto-routes to best free
}


# Structured system prompt optimized for free/smaller models.
# Follows Manus pattern: Identity → Capabilities → Loop → Rules → Error handling.
# Target: under 2000 tokens to preserve reasoning capacity on small context windows.
GEOSPARK_SYSTEM_PROMPT = """\
You are GeoSpark, a geospatial intelligence assistant. You provide ground-truth spatial \
reasoning that LLMs alone get wrong ~80% of the time.

CAPABILITIES:
- geocode: Convert place names to coordinates
- get_elevation: Get terrain height at any location
- spatial_query: Buffer, distance, area, centroid, find nearby features
- check_spatial_relationship: Test if geometries contain, intersect, overlap (100% accurate)

AGENT LOOP (follow this every turn):
1. REASON: What is the user's geographic question? What data do I have vs need?
2. CALL: Make exactly ONE tool call with an explanation of why.
3. OBSERVE: Read the result. If status is "error", read the suggestion and adjust.
4. REPEAT steps 1-3 until the question is fully answered.
5. RESPOND: Present the final answer clearly with coordinates and units.

SPATIAL DATA RULES:
- NEVER guess coordinates. ALWAYS use the geocode tool for place names.
- NEVER estimate distances mentally. ALWAYS use spatial_query with operation "distance".
- NEVER assume spatial relationships. ALWAYS use check_spatial_relationship.
- Coordinates are in [longitude, latitude] order (GeoJSON standard).
- If the user says "lat, lon", swap to [lon, lat] before passing to tools.
- Information priority: tool results > user-provided data > your internal knowledge.

ERROR HANDLING:
- If a tool fails, read the error message and adjust parameters.
- If the same tool fails 3 times, report the error to the user.
- NEVER call the same tool with identical parameters after a failure.
- If geocode fails, ask the user to provide coordinates directly.

RESPONSE FORMAT:
- State the answer clearly with specific numbers (coordinates, distances, areas).
- Always include units (meters, km, degrees).
- Reference the tool that provided the data for transparency.\
"""


class OpenRouterClient:
    """
    OpenRouter client for GeoSpark.

    Provides natural language spatial querying via any OpenRouter model,
    with automatic tool calling for GeoSpark spatial operations.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.model = model or os.getenv("GEOSPARK_DEFAULT_MODEL", FREE_MODELS["best"])

        if not self.api_key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY env var or pass api_key="
            )

        # GeoSpark tool handler
        self.geo_handler = GeoSparkMCPHandler(tools=tools or ["geocoder", "terrain"])

        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://geospark.dev",
                "X-Title": "GeoSpark",
            },
            timeout=60,
        )

    def ask(
        self,
        question: str,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> SpatialAnswer:
        """
        Ask a natural language spatial question.

        The LLM receives GeoSpark tools and can call them to answer
        questions about locations, distances, spatial relationships, etc.

        Examples:
            client.ask("What is the elevation of Mount Everest?")
            client.ask("Is the Eiffel Tower within 5km of the Louvre?")
            client.ask("Geocode 'Tokyo Tower, Japan'")
        """
        use_model = model or self.model
        sys_prompt = system_prompt or GEOSPARK_SYSTEM_PROMPT
        tools = self._build_tool_definitions()

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": question},
        ]

        # Initial LLM call
        response = self._chat_completion(use_model, messages, tools)
        message = response["choices"][0]["message"]

        # Tool call loop (single-tool-per-iteration for reliability with free models)
        max_rounds = 5
        round_num = 0
        tool_results = []

        while round_num < max_rounds:
            tool_calls = message.get("tool_calls")

            # Fallback: try to parse tool calls from plain text
            # (some free models write tool calls as text instead of structured format)
            if not tool_calls and message.get("content"):
                tool_calls = self._parse_fallback_tool_calls(message["content"])

            if not tool_calls:
                break

            round_num += 1
            messages.append(message)

            for tool_call in tool_calls:
                fn_name = tool_call["function"]["name"]
                try:
                    fn_args = (
                        json.loads(tool_call["function"]["arguments"])
                        if isinstance(tool_call["function"]["arguments"], str)
                        else tool_call["function"]["arguments"]
                    )
                except json.JSONDecodeError:
                    fn_args = {}

                # Execute GeoSpark tool
                result = self.geo_handler.handle_tool_call(fn_name, fn_args)
                tool_results.append({"tool": fn_name, "args": fn_args, "result": result})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{round_num}"),
                    "content": json.dumps(result),
                })

            # Get LLM's response after tool use
            response = self._chat_completion(use_model, messages, tools)
            message = response["choices"][0]["message"]

        return SpatialAnswer(
            answer=message.get("content", ""),
            model=use_model,
            tool_calls=tool_results,
            usage=response.get("usage", {}),
        )

    def _chat_completion(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Make a chat completion request to OpenRouter with retry on rate limit."""
        import time

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        max_retries = 3
        for attempt in range(max_retries):
            resp = self.client.post("/chat/completions", json=payload)
            if resp.status_code == 429:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                if attempt < max_retries - 1:
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()  # Will raise on last attempt
        return {}

    def _build_tool_definitions(self) -> list[dict]:
        """Convert GeoSpark MCP tools to OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                },
            }
            for tool in MCP_TOOLS
        ]

    @staticmethod
    def _parse_fallback_tool_calls(text: str) -> list[dict] | None:
        """
        Parse tool calls from plain text when models don't use structured format.

        Some free models write tool calls as text like:
            geocode("Paris, France")
            I'll call geocode with query "Paris"
            {"name": "geocode", "arguments": {"query": "Paris"}}

        Returns a list of synthetic tool_call dicts, or None if no calls found.
        """
        tool_names = {t["name"] for t in MCP_TOOLS}
        calls = []

        # Pattern 1: function_name("arg") or function_name(key="value")
        fn_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(n) for n in tool_names) + r')\s*\(\s*["\']([^"\']+)["\']\s*\)'
        )
        for match in fn_pattern.finditer(text):
            name, arg = match.group(1), match.group(2)
            # Infer the first required param
            tool_def = next(t for t in MCP_TOOLS if t["name"] == name)
            required = [p for p in tool_def["inputSchema"].get("required", []) if p != "explanation"]
            param_name = required[0] if required else "query"
            calls.append({
                "id": f"fallback_{name}",
                "function": {
                    "name": name,
                    "arguments": {param_name: arg, "explanation": "parsed from plain text"},
                },
            })

        # Pattern 2: JSON object in text {"name": "...", "arguments": {...}}
        json_pattern = re.compile(r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*"arguments"\s*:\s*(\{[^{}]*\})[^{}]*\}')
        for match in json_pattern.finditer(text):
            name = match.group(1)
            if name in tool_names:
                try:
                    args = json.loads(match.group(2))
                    args.setdefault("explanation", "parsed from JSON in text")
                    calls.append({
                        "id": f"fallback_{name}",
                        "function": {"name": name, "arguments": args},
                    })
                except json.JSONDecodeError:
                    pass

        return calls if calls else None

    def list_free_models(self) -> dict[str, str]:
        """Return available free models."""
        return FREE_MODELS.copy()

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> OpenRouterClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class SpatialAnswer:
    """The result of a natural language spatial query."""

    def __init__(
        self,
        answer: str,
        model: str,
        tool_calls: list[dict],
        usage: dict,
    ):
        self.answer = answer
        self.model = model
        self.tool_calls = tool_calls
        self.usage = usage

    def __repr__(self) -> str:
        tools_used = [tc["tool"] for tc in self.tool_calls]
        return (
            f"SpatialAnswer(model='{self.model}', "
            f"tools_used={tools_used}, "
            f"answer='{self.answer[:100]}...')"
        )

    def __str__(self) -> str:
        return self.answer

    @property
    def tokens_used(self) -> int:
        return self.usage.get("total_tokens", 0)

    @property
    def cost(self) -> float:
        """Cost in USD. Should be 0 for free models."""
        # OpenRouter returns cost in the response for paid models
        return 0.0  # Free models
