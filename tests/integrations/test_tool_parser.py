"""Regression tests for the shared fallback tool-call parser.

These cases capture the v2-benchmark plain-text variants that the Ollama
integration previously dropped silently. Each test names the open-weight
model whose transcripts motivated it.
"""
from __future__ import annotations

from geospark.integrations.tool_parser import parse_fallback_tool_calls


# ---- existing-coverage parity -------------------------------------------

class TestExistingVariants:
    def test_single_string_arg_positional(self):
        """Qwen 2.5 7B — geocode("Paris, France")."""
        calls = parse_fallback_tool_calls('I will geocode("Paris, France")')
        assert calls is not None and len(calls) == 1
        c = calls[0]["function"]
        assert c["name"] == "geocode"
        assert c["arguments"]["query"] == "Paris, France"

    def test_json_literal_in_prose(self):
        """Mistral 7B — JSON tool call embedded in narrative text."""
        text = 'Let me call {"name": "geocode", "arguments": {"query": "London"}}'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None and len(calls) == 1
        assert calls[0]["function"]["arguments"]["query"] == "London"

    def test_prose_only_returns_none(self):
        """Negative: free-text without any call syntax must not synthesise."""
        calls = parse_fallback_tool_calls(
            "The Eiffel Tower is a famous landmark in Paris."
        )
        assert calls is None

    def test_unknown_tool_ignored(self):
        """Negative: unknown function names must not synthesise calls."""
        calls = parse_fallback_tool_calls('fake_tool("test")')
        assert calls is None


# ---- the four new variants ----------------------------------------------

class TestKeywordMultiArg:
    """Variant 1: Llama 3.1 8B / Gemma 2 9B keyword form."""

    def test_geocode_with_kwarg(self):
        calls = parse_fallback_tool_calls('geocode(query="Eiffel Tower")')
        assert calls is not None
        assert calls[0]["function"]["arguments"]["query"] == "Eiffel Tower"

    def test_get_elevation_with_numeric_kwargs(self):
        calls = parse_fallback_tool_calls(
            'get_elevation(latitude=27.9881, longitude=86.9250)'
        )
        assert calls is not None
        args = calls[0]["function"]["arguments"]
        assert args["latitude"] == 27.9881
        assert args["longitude"] == 86.9250

    def test_kwargs_inject_explanation(self):
        calls = parse_fallback_tool_calls('geocode(query="Paris")')
        assert calls is not None
        assert "explanation" in calls[0]["function"]["arguments"]


class TestPositionalMultiArg:
    """Variant 2: Llama 3.1 8B distance cell — name("a", "b")."""

    def test_get_elevation_positional(self):
        # get_elevation requires (latitude, longitude) — bind by position.
        calls = parse_fallback_tool_calls('get_elevation("27.9881", "86.9250")')
        assert calls is not None
        args = calls[0]["function"]["arguments"]
        assert args["latitude"] == 27.9881
        assert args["longitude"] == 86.9250

    def test_too_many_positional_args_drops_call(self):
        """Conservative: when args overflow slots, drop rather than guess."""
        calls = parse_fallback_tool_calls(
            'geocode("Paris", "France", "Europe", "Earth")'
        )
        # geocode has 1 non-explanation required slot; this is ambiguous, so drop.
        assert calls is None


class TestCodeBlockStripping:
    """Variant 3: triple-backtick fences around calls (most CoT models)."""

    def test_python_code_block(self):
        text = '```python\nresult = geocode("Tokyo Tower")\n```'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        assert calls[0]["function"]["arguments"]["query"] == "Tokyo Tower"

    def test_inline_code_wrap(self):
        text = 'I will use `geocode("Mount Everest")` to find the location.'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        assert calls[0]["function"]["arguments"]["query"] == "Mount Everest"

    def test_markdown_bold_tool_name(self):
        text = '**geocode**("Sydney Opera House")'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        assert calls[0]["function"]["arguments"]["query"] == "Sydney Opera House"


class TestSemicolonSeparator:
    """Variant 4: Llama 3.1 8B — geocode("X"; mode=normal)."""

    def test_semicolon_kwargs(self):
        text = 'geocode(query="Eiffel Tower"; mode="normal")'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        args = calls[0]["function"]["arguments"]
        assert args["query"] == "Eiffel Tower"
        # Either "mode" got recovered, or the parser at least found geocode.
        assert calls[0]["function"]["name"] == "geocode"

    def test_semicolon_outside_parens_not_substituted(self):
        """Negative: prose semicolons elsewhere must stay alone (no spurious
        synthesis from sentence-level punctuation)."""
        text = "It's cold; the model agreed. No tool call here."
        assert parse_fallback_tool_calls(text) is None


# ---- dedupe / shape -----------------------------------------------------

class TestSyntheticShape:
    def test_duplicate_calls_deduped(self):
        text = 'geocode("Paris") and again geocode("Paris")'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        assert len(calls) == 1

    def test_distinct_calls_preserved(self):
        text = 'geocode("Paris") and geocode("London")'
        calls = parse_fallback_tool_calls(text)
        assert calls is not None
        names = [c["function"]["arguments"]["query"] for c in calls]
        assert sorted(names) == ["London", "Paris"]

    def test_synthetic_id_prefix(self):
        calls = parse_fallback_tool_calls('geocode("Paris")')
        assert calls is not None
        assert calls[0]["id"].startswith("fallback_geocode")
