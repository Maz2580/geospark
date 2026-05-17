"""
Ollama Integration.

Connects GeoSpark to locally-running Ollama models with tool calling.
Ollama uses an OpenAI-compatible tool format, making it straightforward
to add spatial reasoning to local LLMs at zero cost.

Usage:
    client = OllamaClient(model="llama3.2")
    answer = client.ask("What is the elevation of Mount Everest?")
    print(client.list_models())  # See available local models
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from geospark.integrations.openrouter import GEOSPARK_SYSTEM_PROMPT, SpatialAnswer
from geospark.integrations.tool_parser import parse_fallback_tool_calls
from geospark.mcp_servers.launcher import MCPServerLauncher

logger = logging.getLogger(__name__)


class OllamaClient:
    """
    Ollama client for GeoSpark.

    Provides natural language spatial querying via locally-running models
    with automatic tool calling for GeoSpark spatial operations.
    Requires Ollama to be running at the specified base_url.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        tools: list[str] | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

        self._launcher = MCPServerLauncher()

        self.client = httpx.Client(
            headers={"Content-Type": "application/json"},
            timeout=120,  # Local models can be slow
        )

    def ask(
        self,
        question: str,
        model: str | None = None,
    ) -> SpatialAnswer:
        """
        Ask a natural language spatial question.

        Sends the question to a local Ollama model with GeoSpark tools.
        The model can call tools to answer spatial questions accurately.
        """
        use_model = model or self.model
        tools = self._build_tool_definitions()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GEOSPARK_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        response = self._chat(use_model, messages, tools)
        message = response.get("message", {})

        max_rounds = 5
        tool_results: list[dict[str, Any]] = []

        for _ in range(max_rounds):
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                # Plain-text fallback. Some open-weight models (Llama 3.1 8B,
                # Mistral 7B, Gemma 2 9B) emit calls as text instead of via
                # Ollama's structured tool_calls field. Without this the v2
                # benchmark cells silently lost most of their tool augmentation.
                recovered = parse_fallback_tool_calls(message.get("content", ""))
                if not recovered:
                    break
                tool_calls = recovered
                message = dict(message, tool_calls=recovered)

            messages.append(message)

            for tool_call in tool_calls:
                fn = tool_call.get("function", {})
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", {})
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        fn_args = {}

                result = self._launcher.handle_tool_call(fn_name, fn_args)
                tool_results.append({"tool": fn_name, "args": fn_args, "result": result})

                messages.append({
                    "role": "tool",
                    "content": json.dumps(result),
                })

            response = self._chat(use_model, messages, tools)
            message = response.get("message", {})

        return SpatialAnswer(
            answer=message.get("content", ""),
            model=use_model,
            tool_calls=tool_results,
            usage={},
        )

    def _chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Make a chat request to the Ollama API."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/api/chat"
        resp = self.client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _build_tool_definitions(self) -> list[dict]:
        """Convert GeoSpark MCP tools to Ollama tool format (OpenAI-compatible)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                },
            }
            for tool in self._launcher.get_all_tools()
        ]

    def list_models(self) -> list[str]:
        """List available local Ollama models."""
        url = f"{self.base_url}/api/tags"
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            logger.warning("Could not connect to Ollama at %s", self.base_url)
            return []

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
