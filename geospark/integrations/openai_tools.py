"""
OpenAI Integration.

Connects GeoSpark to OpenAI's GPT models with native function/tool calling.
Uses the same GeoSpark spatial tools and system prompt as all other integrations.

Usage:
    client = OpenAIClient(api_key="sk-...")
    answer = client.ask("What is the elevation of Mount Everest?")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from geospark.integrations.mcp_server import MCP_TOOLS, GeoSparkMCPHandler
from geospark.integrations.openrouter import GEOSPARK_SYSTEM_PROMPT, SpatialAnswer

logger = logging.getLogger(__name__)


class OpenAIClient:
    """
    OpenAI client for GeoSpark.

    Provides natural language spatial querying via OpenAI models (GPT-4o, etc.)
    with automatic tool calling for GeoSpark spatial operations.
    """

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        tools: list[str] | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model

        if not self.api_key:
            logger.warning(
                "OpenAI API key not set. Set OPENAI_API_KEY env var or pass api_key=. "
                "Client created but API calls will fail."
            )

        self.geo_handler = GeoSparkMCPHandler(tools=tools or ["geocoder", "terrain"])

        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )

    def ask(
        self,
        question: str,
        model: str | None = None,
    ) -> SpatialAnswer:
        """
        Ask a natural language spatial question.

        Sends the question to OpenAI with GeoSpark tools available.
        The model can call tools to answer spatial questions accurately.
        """
        use_model = model or self.model
        tools = self._build_tool_definitions()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GEOSPARK_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        response = self._chat_completion(use_model, messages, tools)
        message = response["choices"][0]["message"]

        max_rounds = 5
        tool_results: list[dict[str, Any]] = []

        for _ in range(max_rounds):
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                break

            messages.append(message)
            results = self._handle_tool_calls(tool_calls, messages)
            tool_results.extend(results)

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
        """Make a chat completion request to OpenAI."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = self.client.post(self.API_URL, json=payload)
        resp.raise_for_status()
        return resp.json()

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

    def _handle_tool_calls(
        self,
        tool_calls: list[dict],
        messages: list[dict],
    ) -> list[dict[str, Any]]:
        """Execute tool calls and append results to messages."""
        results: list[dict[str, Any]] = []

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

            result = self.geo_handler.handle_tool_call(fn_name, fn_args)
            results.append({"tool": fn_name, "args": fn_args, "result": result})

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", "call_0"),
                "content": json.dumps(result),
            })

        return results

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> OpenAIClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
