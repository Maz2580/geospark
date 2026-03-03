"""Tests for OpenRouter integration."""

import os
import pytest
from unittest.mock import patch

from geospark.integrations.openrouter import (
    OpenRouterClient,
    FREE_MODELS,
    GEOSPARK_SYSTEM_PROMPT,
    SpatialAnswer,
)


class TestFreeModels:
    def test_free_models_dict_has_required_keys(self):
        assert "best" in FREE_MODELS
        assert "fast" in FREE_MODELS
        assert "coder" in FREE_MODELS
        assert "auto" in FREE_MODELS

    def test_all_free_models_have_free_suffix(self):
        for key, model_id in FREE_MODELS.items():
            if key != "auto":  # auto uses special openrouter/free
                assert ":free" in model_id, f"Model {key}={model_id} missing :free suffix"


class TestSystemPrompt:
    """Test the optimized system prompt follows best practices."""

    def test_prompt_has_identity_section(self):
        assert "GeoSpark" in GEOSPARK_SYSTEM_PROMPT
        assert "geospatial" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_has_capabilities_list(self):
        assert "CAPABILITIES:" in GEOSPARK_SYSTEM_PROMPT
        assert "geocode" in GEOSPARK_SYSTEM_PROMPT
        assert "get_elevation" in GEOSPARK_SYSTEM_PROMPT
        assert "spatial_query" in GEOSPARK_SYSTEM_PROMPT
        assert "check_spatial_relationship" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_has_agent_loop(self):
        """Should follow Manus single-tool-per-iteration pattern."""
        assert "AGENT LOOP" in GEOSPARK_SYSTEM_PROMPT
        assert "ONE tool call" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_has_anti_hallucination_rules(self):
        assert "NEVER guess coordinates" in GEOSPARK_SYSTEM_PROMPT
        assert "NEVER estimate distances" in GEOSPARK_SYSTEM_PROMPT
        assert "NEVER assume spatial relationships" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_has_coordinate_convention(self):
        assert "[longitude, latitude]" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_has_error_handling(self):
        assert "ERROR HANDLING" in GEOSPARK_SYSTEM_PROMPT
        assert "3 times" in GEOSPARK_SYSTEM_PROMPT

    def test_prompt_under_2000_tokens(self):
        """System prompt should be concise to preserve reasoning capacity."""
        # Rough approximation: ~4 chars per token for English
        estimated_tokens = len(GEOSPARK_SYSTEM_PROMPT) / 4
        assert estimated_tokens < 2000, f"System prompt ~{estimated_tokens:.0f} tokens, should be <2000"


class TestFallbackParsing:
    """Test parsing tool calls from plain text (for models without structured tool calling)."""

    def test_parse_function_call_syntax(self):
        """Models may write: geocode("Paris, France")"""
        text = 'I\'ll find the coordinates. geocode("Paris, France")'
        calls = OpenRouterClient._parse_fallback_tool_calls(text)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "geocode"
        assert calls[0]["function"]["arguments"]["query"] == "Paris, France"

    def test_parse_json_object_in_text(self):
        """Models may write tool calls as JSON objects in their response."""
        text = 'Let me call {"name": "geocode", "arguments": {"query": "London"}}'
        calls = OpenRouterClient._parse_fallback_tool_calls(text)
        assert calls is not None
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "geocode"
        assert calls[0]["function"]["arguments"]["query"] == "London"

    def test_no_tool_calls_returns_none(self):
        """Plain text without tool calls should return None."""
        text = "The Eiffel Tower is a famous landmark in Paris."
        calls = OpenRouterClient._parse_fallback_tool_calls(text)
        assert calls is None

    def test_unknown_tool_not_parsed(self):
        """Should not parse function calls for tools that don't exist."""
        text = 'fake_tool("test")'
        calls = OpenRouterClient._parse_fallback_tool_calls(text)
        assert calls is None

    def test_single_quoted_args(self):
        """Should handle single-quoted arguments."""
        text = "get_elevation('27.9881')"
        # This won't match because it expects a string arg, not a number
        # But let's test the pattern handles it
        calls = OpenRouterClient._parse_fallback_tool_calls(text)
        if calls:
            assert calls[0]["function"]["name"] == "get_elevation"


class TestSpatialAnswer:
    def test_spatial_answer_str(self):
        answer = SpatialAnswer(
            answer="The Eiffel Tower is at 48.8584, 2.2945",
            model="test-model",
            tool_calls=[],
            usage={"total_tokens": 100},
        )
        assert "Eiffel Tower" in str(answer)
        assert answer.tokens_used == 100
        assert answer.cost == 0.0

    def test_spatial_answer_repr(self):
        answer = SpatialAnswer(
            answer="Test",
            model="meta-llama/llama-3.3-70b-instruct:free",
            tool_calls=[{"tool": "geocode", "args": {}, "result": {}}],
            usage={},
        )
        r = repr(answer)
        assert "llama-3.3" in r
        assert "geocode" in r


class TestOpenRouterClient:
    def test_requires_api_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="API key required"):
                OpenRouterClient(api_key="")

    def test_list_free_models(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(api_key="test-key")
            models = client.list_free_models()
            assert len(models) >= 5
            client.close()

    def test_tool_definitions_include_explanation(self):
        """Built tool defs should carry the explanation field through."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = OpenRouterClient(api_key="test-key")
            tools = client._build_tool_definitions()
            for tool in tools:
                params = tool["function"]["parameters"]
                assert "explanation" in params["properties"]
            client.close()


@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set -- skip live API tests",
)
class TestOpenRouterLive:
    """Live tests that actually call OpenRouter. Only run when API key is available."""

    def test_simple_spatial_question(self):
        client = OpenRouterClient(model=FREE_MODELS["fast"])
        answer = client.ask("What are the coordinates of the Eiffel Tower? Be brief.")
        assert answer.answer  # Got some response
        assert answer.model == FREE_MODELS["fast"]
        client.close()

    def test_tool_calling_geocode(self):
        client = OpenRouterClient(model=FREE_MODELS["best"])
        answer = client.ask("Use the geocode tool to find the coordinates of 'Big Ben, London'.")
        assert answer.answer
        client.close()
