"""
Anthropic Integration.

Connects GeoSpark to Anthropic's Claude models with native tool use.
Anthropic uses a slightly different tool format than OpenAI (input_schema
instead of parameters), which this module handles.

Usage:
    client = AnthropicClient(api_key="sk-ant-...")
    answer = client.ask("Is the Eiffel Tower within 5km of the Louvre?")
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


class AnthropicClient:
    """
    Anthropic client for GeoSpark.

    Provides natural language spatial querying via Claude models
    with automatic tool use for GeoSpark spatial operations.
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        tools: list[str] | None = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model

        if not self.api_key:
            logger.warning(
                "Anthropic API key not set. Set ANTHROPIC_API_KEY env var or pass api_key=. "
                "Client created but API calls will fail."
            )

        self.geo_handler = GeoSparkMCPHandler(tools=tools or ["geocoder", "terrain"])

        self.client = httpx.Client(
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
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

        Sends the question to Anthropic with GeoSpark tools available.
        Claude can use tools to answer spatial questions accurately.
        """
        use_model = model or self.model
        tools = self._build_tool_definitions()

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": question},
        ]

        response = self._create_message(use_model, messages, tools)

        max_rounds = 5
        tool_results: list[dict[str, Any]] = []

        for _ in range(max_rounds):
            content = response.get("content", [])

            # Check if there are tool_use blocks
            tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
            if not tool_use_blocks:
                break

            # Append assistant response to messages
            messages.append({"role": "assistant", "content": content})

            # Execute tools and add results
            results = self._handle_tool_use(tool_use_blocks, messages)
            tool_results.extend(results)

            response = self._create_message(use_model, messages, tools)

        # Extract final text from content blocks
        answer_text = ""
        for block in response.get("content", []):
            if block.get("type") == "text":
                answer_text += block.get("text", "")

        return SpatialAnswer(
            answer=answer_text,
            model=use_model,
            tool_calls=tool_results,
            usage=response.get("usage", {}),
        )

    def _create_message(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Make a messages API request to Anthropic."""
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "system": GEOSPARK_SYSTEM_PROMPT,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        resp = self.client.post(self.API_URL, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _build_tool_definitions(self) -> list[dict]:
        """Convert GeoSpark MCP tools to Anthropic tool use format.

        Anthropic uses ``input_schema`` rather than ``parameters``,
        which is the key difference from the OpenAI format.
        """
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["inputSchema"],
            }
            for tool in MCP_TOOLS
        ]

    def _handle_tool_use(
        self,
        tool_use_blocks: list[dict],
        messages: list[dict],
    ) -> list[dict[str, Any]]:
        """Execute tool use blocks and append results to messages."""
        results: list[dict[str, Any]] = []
        tool_results_content: list[dict[str, Any]] = []

        for block in tool_use_blocks:
            fn_name = block["name"]
            fn_args = block.get("input", {})

            result = self.geo_handler.handle_tool_call(fn_name, fn_args)
            results.append({"tool": fn_name, "args": fn_args, "result": result})

            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": block.get("id", "tool_0"),
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results_content})
        return results

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> AnthropicClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
