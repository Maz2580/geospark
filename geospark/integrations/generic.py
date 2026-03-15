"""
Generic OpenAI-compatible Integration.

Connects GeoSpark to any OpenAI-compatible API server, including:
- vLLM, LMStudio, Together AI, Fireworks, Groq, etc.
- Any server that implements the /v1/chat/completions endpoint.

Usage:
    # vLLM
    client = GenericLLMClient(base_url="http://localhost:8000/v1", model="mistral-7b")

    # Together AI
    client = GenericLLMClient(
        base_url="https://api.together.xyz/v1",
        api_key="...",
        model="meta-llama/Llama-3-70b-chat-hf",
    )

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


class GenericLLMClient:
    """
    Generic OpenAI-compatible client for GeoSpark.

    Works with any API server that implements the OpenAI chat completions
    endpoint format. Provides spatial tool calling for GeoSpark operations.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str = "default",
        tools: list[str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model

        if not self.api_key:
            logger.info(
                "No API key provided. This is fine for local servers (vLLM, LMStudio)."
            )

        self.geo_handler = GeoSparkMCPHandler(tools=tools or ["geocoder", "terrain"])

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.Client(headers=headers, timeout=120)

    def ask(
        self,
        question: str,
        model: str | None = None,
    ) -> SpatialAnswer:
        """
        Ask a natural language spatial question.

        Sends the question to the configured API with GeoSpark tools.
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
                tool_results.append({"tool": fn_name, "args": fn_args, "result": result})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", "call_0"),
                    "content": json.dumps(result),
                })

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
        """Make a chat completion request to the configured API endpoint."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        resp = self.client.post(url, json=payload)
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

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> GenericLLMClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
