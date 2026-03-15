"""Tests for LLM integrations (OpenAI, Anthropic, Ollama, Generic).

All tests run without actual API keys. HTTP calls are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from geospark.integrations.openai_tools import OpenAIClient
from geospark.integrations.anthropic_tools import AnthropicClient
from geospark.integrations.ollama_tools import OllamaClient
from geospark.integrations.generic import GenericLLMClient
from geospark.integrations.openrouter import SpatialAnswer


# ---------------------------------------------------------------------------
# Instantiation tests (no API key required)
# ---------------------------------------------------------------------------


class TestClientInstantiation:
    """All clients can be instantiated without API keys (warn, don't crash)."""

    def test_openai_client_no_key(self):
        client = OpenAIClient()
        assert client.model == "gpt-4o-mini"
        assert client.api_key == ""
        client.close()

    def test_anthropic_client_no_key(self):
        client = AnthropicClient()
        assert client.model == "claude-sonnet-4-20250514"
        assert client.api_key == ""
        client.close()

    def test_ollama_client_defaults(self):
        client = OllamaClient()
        assert client.model == "llama3.2"
        assert "11434" in client.base_url
        client.close()

    def test_generic_client_custom_url(self):
        client = GenericLLMClient(base_url="http://localhost:8000/v1")
        assert client.base_url == "http://localhost:8000/v1"
        assert client.model == "default"
        client.close()

    def test_openai_client_with_key(self):
        client = OpenAIClient(api_key="sk-test-123", model="gpt-4o")
        assert client.api_key == "sk-test-123"
        assert client.model == "gpt-4o"
        client.close()

    def test_anthropic_client_with_key(self):
        client = AnthropicClient(api_key="sk-ant-test", model="claude-haiku-4-20250514")
        assert client.api_key == "sk-ant-test"
        assert client.model == "claude-haiku-4-20250514"
        client.close()

    def test_ollama_custom_base_url(self):
        client = OllamaClient(base_url="http://gpu-server:11434/")
        assert client.base_url == "http://gpu-server:11434"
        client.close()

    def test_generic_with_api_key(self):
        client = GenericLLMClient(
            base_url="https://api.together.xyz/v1",
            api_key="tog-key",
            model="meta-llama/Llama-3-70b",
        )
        assert client.api_key == "tog-key"
        assert client.model == "meta-llama/Llama-3-70b"
        client.close()


# ---------------------------------------------------------------------------
# Tool definition tests
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Tool definitions are well-formed and follow each provider's format."""

    def test_openai_tool_format(self):
        client = OpenAIClient()
        tools = client._build_tool_definitions()
        assert len(tools) >= 4
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
            # OpenAI uses "parameters", not "input_schema"
            assert "properties" in tool["function"]["parameters"]
        client.close()

    def test_anthropic_tool_format(self):
        client = AnthropicClient()
        tools = client._build_tool_definitions()
        assert len(tools) >= 4
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            # Anthropic uses "input_schema", not "parameters"
            assert "input_schema" in tool
            assert "type" not in tool  # No wrapping "type": "function"
            assert "properties" in tool["input_schema"]
        client.close()

    def test_ollama_tool_format_matches_openai(self):
        client = OllamaClient()
        tools = client._build_tool_definitions()
        assert len(tools) >= 4
        for tool in tools:
            assert tool["type"] == "function"
            assert "parameters" in tool["function"]
        client.close()

    def test_generic_tool_format_matches_openai(self):
        client = GenericLLMClient(base_url="http://localhost:8000/v1")
        tools = client._build_tool_definitions()
        assert len(tools) >= 4
        for tool in tools:
            assert tool["type"] == "function"
            assert "parameters" in tool["function"]
        client.close()

    def test_all_tools_have_explanation_field(self):
        """All providers should carry through the explanation field."""
        openai_tools = OpenAIClient()._build_tool_definitions()
        anthropic_tools = AnthropicClient()._build_tool_definitions()

        for tool in openai_tools:
            assert "explanation" in tool["function"]["parameters"]["properties"]

        for tool in anthropic_tools:
            assert "explanation" in tool["input_schema"]["properties"]

    def test_anthropic_vs_openai_format_difference(self):
        """Key difference: Anthropic uses input_schema, OpenAI uses parameters."""
        openai_client = OpenAIClient()
        anthropic_client = AnthropicClient()

        openai_tools = openai_client._build_tool_definitions()
        anthropic_tools = anthropic_client._build_tool_definitions()

        # Same number of tools
        assert len(openai_tools) == len(anthropic_tools)

        # Same tool names
        openai_names = {t["function"]["name"] for t in openai_tools}
        anthropic_names = {t["name"] for t in anthropic_tools}
        assert openai_names == anthropic_names

        # Different format keys
        assert "parameters" in openai_tools[0]["function"]
        assert "input_schema" in anthropic_tools[0]

        openai_client.close()
        anthropic_client.close()


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestContextManagers:
    def test_openai_context_manager(self):
        with OpenAIClient() as client:
            assert client.model == "gpt-4o-mini"

    def test_anthropic_context_manager(self):
        with AnthropicClient() as client:
            assert client.model == "claude-sonnet-4-20250514"

    def test_ollama_context_manager(self):
        with OllamaClient() as client:
            assert client.model == "llama3.2"

    def test_generic_context_manager(self):
        with GenericLLMClient(base_url="http://localhost:8000/v1") as client:
            assert client.model == "default"


# ---------------------------------------------------------------------------
# Mocked ask() flow tests
# ---------------------------------------------------------------------------


class TestOpenAIAskFlow:
    """Test OpenAI ask() with mocked HTTP responses."""

    def test_ask_no_tool_calls(self):
        client = OpenAIClient(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "The Eiffel Tower is in Paris."}}],
            "usage": {"total_tokens": 42},
        }

        with patch.object(client.client, "post", return_value=mock_response):
            answer = client.ask("Where is the Eiffel Tower?")

        assert isinstance(answer, SpatialAnswer)
        assert "Paris" in answer.answer
        assert answer.model == "gpt-4o-mini"
        assert answer.tool_calls == []
        assert answer.tokens_used == 42
        client.close()

    def test_ask_with_tool_call(self):
        client = OpenAIClient(api_key="test-key")

        # First response: model wants to call geocode
        tool_call_response = MagicMock()
        tool_call_response.status_code = 200
        tool_call_response.raise_for_status = MagicMock()
        tool_call_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc",
                        "function": {
                            "name": "geocode",
                            "arguments": json.dumps({
                                "explanation": "Need coordinates",
                                "query": "Paris",
                            }),
                        },
                    }],
                },
            }],
            "usage": {"total_tokens": 30},
        }

        # Second response: model answers with tool result
        final_response = MagicMock()
        final_response.status_code = 200
        final_response.raise_for_status = MagicMock()
        final_response.json.return_value = {
            "choices": [{"message": {"content": "Paris is at 48.86, 2.35."}}],
            "usage": {"total_tokens": 80},
        }

        with patch.object(
            client.client, "post", side_effect=[tool_call_response, final_response]
        ):
            answer = client.ask("Geocode Paris")

        assert "Paris" in answer.answer
        assert len(answer.tool_calls) == 1
        assert answer.tool_calls[0]["tool"] == "geocode"
        client.close()


class TestAnthropicAskFlow:
    """Test Anthropic ask() with mocked HTTP responses."""

    def test_ask_no_tool_use(self):
        client = AnthropicClient(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Mount Everest is 8849m tall."}],
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }

        with patch.object(client.client, "post", return_value=mock_response):
            answer = client.ask("How tall is Mount Everest?")

        assert isinstance(answer, SpatialAnswer)
        assert "8849" in answer.answer
        assert answer.tool_calls == []
        client.close()

    def test_ask_with_tool_use(self):
        client = AnthropicClient(api_key="test-key")

        # First response: tool_use block
        tool_response = MagicMock()
        tool_response.status_code = 200
        tool_response.raise_for_status = MagicMock()
        tool_response.json.return_value = {
            "content": [
                {"type": "text", "text": "Let me look that up."},
                {
                    "type": "tool_use",
                    "id": "tu_01",
                    "name": "geocode",
                    "input": {"explanation": "Need coords", "query": "London"},
                },
            ],
            "usage": {"input_tokens": 30, "output_tokens": 20},
        }

        # Second response: final text
        final_response = MagicMock()
        final_response.status_code = 200
        final_response.raise_for_status = MagicMock()
        final_response.json.return_value = {
            "content": [{"type": "text", "text": "London is at 51.51, -0.13."}],
            "usage": {"input_tokens": 50, "output_tokens": 25},
        }

        with patch.object(
            client.client, "post", side_effect=[tool_response, final_response]
        ):
            answer = client.ask("Geocode London")

        assert "London" in answer.answer
        assert len(answer.tool_calls) == 1
        assert answer.tool_calls[0]["tool"] == "geocode"
        client.close()


class TestOllamaAskFlow:
    """Test Ollama ask() with mocked HTTP responses."""

    def test_ask_no_tool_calls(self):
        client = OllamaClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Tokyo is in Japan."},
        }

        with patch.object(client.client, "post", return_value=mock_response):
            answer = client.ask("Where is Tokyo?")

        assert isinstance(answer, SpatialAnswer)
        assert "Tokyo" in answer.answer
        assert answer.tool_calls == []
        client.close()

    def test_list_models_success(self):
        client = OllamaClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2:latest"},
                {"name": "mistral:latest"},
            ],
        }

        with patch.object(client.client, "get", return_value=mock_response):
            models = client.list_models()

        assert "llama3.2:latest" in models
        assert "mistral:latest" in models
        client.close()

    def test_list_models_connection_error(self):
        client = OllamaClient()

        with patch.object(
            client.client, "get", side_effect=Exception("Connection refused")
        ):
            models = client.list_models()

        assert models == []
        client.close()


class TestGenericAskFlow:
    """Test Generic client ask() with mocked HTTP responses."""

    def test_ask_simple(self):
        client = GenericLLMClient(
            base_url="http://localhost:8000/v1", api_key="test"
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Berlin is in Germany."}}],
            "usage": {"total_tokens": 20},
        }

        with patch.object(client.client, "post", return_value=mock_response):
            answer = client.ask("Where is Berlin?")

        assert isinstance(answer, SpatialAnswer)
        assert "Berlin" in answer.answer
        client.close()
